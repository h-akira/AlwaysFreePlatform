#!/usr/bin/env python3
"""Value conversion helpers for scripts/*.sh (Python standard library only).

Subcommands:
  variables TFVARS_JSON [KEYS]
                             Print Resource Manager stack variables as JSON.
                             KEYS (comma separated) limits them to those keys,
                             which must all be set, except those ending in "?"
                             (passed only when set). Without KEYS (the main
                             stack), all of them.
  get TFVARS_JSON KEY        Print one top-level value from the tfvars file.
  outputs                    Read a Terraform state from stdin and print
                             outputs as KEY=VALUE lines.
  execution                  Read a Run Command execution (oci instance-agent
                             command-execution get) from stdin; print
                             "STATE EXIT_CODE" and then the output text.
  command-content SCRIPT     Print the --content of a Run Command for SCRIPT
                             (wrapped to return only the end of its output).
  build-services PREFIX      Read `docker compose config --format json` from
                             stdin; print "SERVICE REPOSITORY" for each service
                             with build:, whose image must be PREFIX/<name>:<tag>.
  json-get KEY               Print one top-level value of the JSON on stdin.
  has-project NAME           Read afp.json on stdin; fail unless NAME is listed.
  pack-terraform DIR OUT     Zip DIR (terraform/) as it is on disk into OUT and
                             print the hash of its contents (12 hex digits).
  pack-platform ROOT OUT     Pack the platform code that the VM and the DevOps
                             build use (PLATFORM_DIRS of ROOT) into OUT, a
                             tar.gz; print the archive's sha256 (12 hex digits),
                             as afp-bootstrap names it on the VM.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any


def to_rm_variables(tfvars: dict[str, Any]) -> dict[str, str]:
    """Convert tfvars values to Resource Manager variables (strings only).

    Strings stay as they are; everything else (lists, maps, numbers, booleans)
    becomes JSON text, which Terraform parses for complex-typed variables.
    """
    result: dict[str, str] = {}
    for key, value in tfvars.items():
        if value is None:
            raise ValueError(f"variable {key!r} is null; remove it to use the default")
        result[key] = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return result


def select_keys(tfvars: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Keep only the given keys; each must be present, except optional ones
    written with a trailing "?" (e.g. "budget_amount?"), kept only if present."""
    required = [key for key in keys if not key.endswith("?")]
    missing = [key for key in required if key not in tfvars]
    if missing:
        raise ValueError(f"not set: {', '.join(missing)}")
    names = [key[:-1] if key.endswith("?") else key for key in keys]
    return {key: tfvars[key] for key in names if key in tfvars}


def state_outputs(state: dict[str, Any]) -> dict[str, str]:
    """Extract outputs from a Terraform state as strings."""
    result: dict[str, str] = {}
    for key, output in state.get("outputs", {}).items():
        if output.get("sensitive"):
            continue
        value = output.get("value")
        result[key] = value if isinstance(value, str) else json.dumps(value)
    return result


def execution_result(execution: dict[str, Any]) -> tuple[str, str, str]:
    """State, exit code ("-" if none yet) and output text of an execution."""
    data = execution.get("data", execution)
    content = data.get("content") or {}
    code = content.get("exit-code")
    return str(data.get("lifecycle-state")), "-" if code is None else str(code), content.get("text") or ""


# Run Command returns about 1 KB of the output, cut at its start (measured
# 2026-11-14, although the documentation says the last 1 KB). The script is
# wrapped so that only its end, where afp prints its summary, comes back.
OUTPUT_TAIL_BYTES = 900


# On a new VM the agent takes commands before the first boot has written
# /etc/sudoers.d/afp (measured 2026-11-14), so `sudo -n` fails for a few
# minutes. Wrapped scripts wait for that rule first.
SUDO_CHECK = "sudo -n -l /usr/local/sbin/afp-bootstrap"
SUDO_WAIT_TRIES = 60
SUDO_WAIT_INTERVAL = 10


def wrap_script(script: str, *, tries: int = SUDO_WAIT_TRIES, interval: int = SUDO_WAIT_INTERVAL) -> str:
    """POSIX sh: wait for the sudo rule, run SCRIPT, print the end of its
    output, keep its exit code."""
    return (
        "i=0\n"
        f"until {SUDO_CHECK} > /dev/null 2>&1; do\n"
        f"  i=$((i + 1)); if [ \"$i\" -ge {tries} ]; then\n"
        "    echo 'sudo is not allowed for this user yet (is the first boot still running?)'; exit 1\n"
        "  fi\n"
        f"  sleep {interval}\n"
        "done\n"
        f"out=$( {{ {script}\n}} 2>&1 ); rc=$?\n"
        f"printf '%s\\n' \"$out\" | tail -c {OUTPUT_TAIL_BYTES}\n"
        "exit $rc\n"
    )


def command_content(script: str) -> dict[str, Any]:
    return {"source": {"sourceType": "TEXT", "text": wrap_script(script)}, "output": {"outputType": "TEXT"}}


def build_services(config: dict[str, Any], prefix: str) -> list[tuple[str, str]]:
    """Services that make deploy builds, with their OCIR repository names.

    prefix is AFP_IMAGE_PREFIX, e.g. iad.ocir.io/<namespace>/repo-afp-<project>;
    the repository is the image path after the namespace, without the tag
    (repo-afp-<project>/<name>).
    """
    result: list[tuple[str, str]] = []
    for name, service in sorted((config.get("services") or {}).items()):
        if "build" not in service:
            continue
        image = service.get("image") or ""
        path, _, tag = image.rpartition(":")
        if not image.startswith(prefix + "/") or not tag or "/" in tag:
            raise ValueError(f"service {name}: image must be ${{AFP_IMAGE_PREFIX}}/<name>:${{AFP_TAG}}, not {image!r}")
        repository = path.split("/", 2)[2]  # drop the registry host and the namespace
        result.append((name, repository))
    if not result:
        raise ValueError("no service has build:; nothing to build")
    return result


# Code is sent as it is on disk, committed or not (ADR 038). Local state and
# caches are left out.
SKIP_DIRS = {".terraform", "__pycache__", ".pytest_cache", ".git"}
SKIP_SUFFIXES = (".pyc", ".tfstate", ".tfstate.backup")
# What the VM (afp-bootstrap) and the DevOps build (devops-release.sh) use.
PLATFORM_DIRS = ("afp", "bin", "caddy", "mysql", "scripts")


def _files(top: Path) -> list[Path]:
    """Files under top, sorted by their relative path, without SKIP_*."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            if not name.endswith(SKIP_SUFFIXES):
                found.append(Path(dirpath) / name)
    return sorted(found, key=lambda p: p.relative_to(top).as_posix())


def _content_hash(entries: list[tuple[str, bytes, int]]) -> str:
    """Hash of (relative path, executable bit, bytes) of every file."""
    h = hashlib.sha256()
    for name, data, mode in entries:
        h.update(f"{name}\0{1 if mode & 0o111 else 0}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest()[:12]


def _entries(files: list[Path], base: Path) -> list[tuple[str, bytes, int]]:
    return [(p.relative_to(base).as_posix(), p.read_bytes(), p.stat().st_mode) for p in files]


def pack_terraform(top: Path, out: Path) -> str:
    """Zip terraform/ as it is (the root modules reach ../modules)."""
    entries = _entries(_files(top), top)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (mode & 0o777) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return _content_hash(entries)


def pack_platform(root: Path, out: Path) -> str:
    """tar.gz of PLATFORM_DIRS, the same bytes for the same files."""
    files: list[Path] = []
    for d in PLATFORM_DIRS:
        if not (root / d).is_dir():
            raise ValueError(f"{root / d} is not a directory")
        files += _files(root / d)
    entries = _entries(files, root)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if mode & 0o111 else 0o644
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))
    out.write_bytes(buf.getvalue())
    # The hash of the archive itself, which afp-bootstrap names the VM's copy
    # after (the archive is the same bytes for the same files).
    return hashlib.sha256(buf.getvalue()).hexdigest()[:12]


def _load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    return data


def main(argv: list[str]) -> int:
    if len(argv) in (2, 3) and argv[0] == "variables":
        tfvars = _load_json(argv[1])
        if len(argv) == 3:
            tfvars = select_keys(tfvars, [key for key in argv[2].split(",") if key])
        print(json.dumps(to_rm_variables(tfvars)))
    elif len(argv) == 3 and argv[0] == "get":
        value = _load_json(argv[1]).get(argv[2])
        if value is None:
            print(f"{argv[1]}: {argv[2]} is not set", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
    elif len(argv) == 1 and argv[0] == "execution":
        state, code, text = execution_result(json.load(sys.stdin))
        print(f"{state} {code}")
        print(text, end="" if text.endswith("\n") or not text else "\n")
    elif len(argv) == 2 and argv[0] == "command-content":
        print(json.dumps(command_content(argv[1])))
    elif len(argv) == 2 and argv[0] == "build-services":
        for name, repository in build_services(json.load(sys.stdin), argv[1]):
            print(f"{name} {repository}")
    elif len(argv) == 2 and argv[0] == "json-get":
        value = json.load(sys.stdin).get(argv[1])
        if value is None:
            print(f"{argv[1]} is not set", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
    elif len(argv) == 2 and argv[0] == "has-project":
        names = [p.get("name") for p in json.load(sys.stdin).get("projects") or []]
        if argv[1] not in names:
            print(f"project {argv[1]} is not in afp.json (listed: {', '.join(names) or 'none'})", file=sys.stderr)
            return 1
    elif len(argv) == 3 and argv[0] == "pack-terraform":
        print(pack_terraform(Path(argv[1]), Path(argv[2])))
    elif len(argv) == 3 and argv[0] == "pack-platform":
        print(pack_platform(Path(argv[1]), Path(argv[2])))
    elif len(argv) == 1 and argv[0] == "outputs":
        for key, value in state_outputs(json.load(sys.stdin)).items():
            print(f"{key}={value}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as e:
        print(f"rm_values.py: {e}", file=sys.stderr)
        sys.exit(1)
