"""A fake VM for afp tests: answers the oci and docker commands afp runs.

It keeps a bucket (objects), the secrets, and which tag of which compose
project is running. Tags in `broken` fail to start.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afp import cli  # noqa: E402
from afp.errors import AfpError  # noqa: E402
from afp.log import Log  # noqa: E402
from afp.oci import Oci  # noqa: E402

REGION = "us-ashburn-1"
DB_PASSWORD = "Ab3-xyz_DEF.ghi~jkl"
ADMIN_PASSWORD = "Admin-Pass_1"
SIGNING_KEY = "sign-Key_123"
API_KEY = "api'key$with\"quotes"


def afp_json(projects: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "region": REGION,
        "namespace": "ns",
        "bucket": "bucket-afp-main",
        "platform_repository": "https://github.com/example/platform",
        "db": {"host": "10.0.1.10", "port": 3306, "admin_user": "afpadmin", "admin_secret_id": "ocid1.vaultsecret.oc1..admin"},
        "image_prefix_base": "iad.ocir.io/ns",
        "compartment_id": "ocid1.compartment.oc1..afp",
        "projects": projects
        if projects is not None
        else [
            {"name": "hello", "domain": "hello.example.com", "secret_id": "ocid1.vaultsecret.oc1..hello", "manual_secret_ids": {}},
            {"name": "app-a", "domain": "app-a.example.net", "secret_id": "ocid1.vaultsecret.oc1..appa",
             "manual_secret_ids": {"API_KEY": "ocid1.vaultsecret.oc1..apikey"}},
        ],
    }


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class World:
    def __init__(self, afp: dict[str, Any] | None = None) -> None:
        self.objects: dict[str, str] = {"afp.json": json.dumps(afp if afp is not None else afp_json())}
        self.secrets = {
            "ocid1.vaultsecret.oc1..admin": ADMIN_PASSWORD,
            "ocid1.vaultsecret.oc1..hello": json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD}),
            "ocid1.vaultsecret.oc1..appa": json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD, "SIGNING_KEY": SIGNING_KEY}),
            "ocid1.vaultsecret.oc1..apikey": API_KEY,
        }
        self.files: dict[str, bytes] = {}  # binary objects (source archives)
        self.repositories: set[str] = set()  # OCIR repositories
        self.pushed: list[tuple[str, str, list[str]]] = []  # (project, tag, services)
        self.compose_config: dict[str, Any] | None = None  # answer of `docker compose config`
        self.running: dict[str, str] = {}  # compose project -> tag
        self.broken: set[str] = set()
        self.broken_build: set[str] = set()  # tags whose build fails
        self.calls: list[dict[str, Any]] = []

    def release(self, project: str, tag: str) -> None:
        self.objects[f"releases/{project}/{tag}/compose.afp.yaml"] = f"# {project} {tag}\n"

    def source(self, project: str, tag: str, files: dict[str, str] | None = None) -> None:
        """Put the tag's source archive, as the DevOps build does."""
        import tarfile as _tarfile
        buf = io.BytesIO()
        with _tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, text in (files or {"compose.afp.yaml": "services: {}\n", "app.py": "print(1)\n"}).items():
                data = text.encode()
                info = _tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.files[f"releases/{project}/{tag}/source.tar.gz"] = buf.getvalue()

    def state(self, project: str) -> dict[str, Any] | None:
        text = self.objects.get(f"state/{project}.json")
        return json.loads(text) if text else None

    # Runner interface ------------------------------------------------------

    def run(self, args: list[str], *, stdin: str | None = None, env: dict[str, str] | None = None,
            check: bool = True, quiet: bool = False, secret_output: bool = False,
            stdout_path: Path | None = None) -> subprocess.CompletedProcess[str]:
        args = list(args)
        self.calls.append({"args": args, "stdin": stdin, "env": env, "secret_output": secret_output})
        code, out, err = self._answer(args, env or {}, stdout_path)
        if check and code != 0:
            raise AfpError(f"{args[0]} {args[1]} failed ({code}): {err}")
        return subprocess.CompletedProcess(args, code, out, err)

    def _answer(self, args: list[str], env: dict[str, str], stdout_path: Path | None) -> tuple[int, str, str]:
        line = " ".join(args)
        if args[0] == "oci":
            if "os object get" in line and args[args.index("--file") + 1] != "-":
                name = args[args.index("--name") + 1]
                if name in self.files:
                    Path(args[args.index("--file") + 1]).write_bytes(self.files[name])
                    return 0, "", ""
                return 1, "", '{\n    "status": 404,\n}'
            if "artifacts container repository list" in line:
                name = args[args.index("--display-name") + 1]
                return 0, "1" if name in self.repositories else "0", ""
            if "artifacts container repository create" in line:
                self.repositories.add(args[args.index("--display-name") + 1])
                return 0, "", ""
            if "os object get" in line:
                name = args[args.index("--name") + 1]
                if name in self.objects:
                    return 0, self.objects[name], ""
                # What the real CLI prints (head_object first; code is null).
                return 1, "", ('ServiceError:\n{\n    "code": null,\n    "message": "The service returned error code 404",\n'
                               '    "operation_name": "head_object",\n    "status": 404,\n}')
            if "os object put" in line:
                name = args[args.index("--name") + 1]
                data = Path(args[args.index("--file") + 1]).read_bytes()
                self.objects[name] = data.decode() if not name.endswith(".gz") else "<gzip>"
                return 0, "", ""
            if "secret-bundle get" in line:
                return 0, b64(self.secrets[args[args.index("--secret-id") + 1]]), ""
            if "raw-request" in line:
                return 0, json.dumps({"data": {"token": "tok", "expires_in": 3600}}), ""
        if args[:2] == ["docker", "compose"]:
            project = args[args.index("-p") + 1] if "-p" in args else None
            if "ls" in args:
                return 0, json.dumps([{"Name": n} for n in sorted(self.running)]), ""
            if "pull" in args:
                return 0, "", ""
            if "config" in args:
                prefix = env["AFP_IMAGE_PREFIX"]
                config = self.compose_config or {"services": {
                    "web": {"build": {"context": "."}, "image": f"{prefix}/web:{env['AFP_TAG']}"},
                    "redis": {"image": "redis:7"},
                }}
                return 0, json.dumps(config), ""
            if "build" in args:
                if env["AFP_TAG"] in self.broken_build:
                    return 1, "", "failed to solve: process did not complete successfully"
                return 0, "", ""
            if "push" in args:
                names = [a for a in args[args.index("push") + 1:] if not a.startswith("-")]
                self.pushed.append((project or "", env["AFP_TAG"], names))
                return 0, "", ""
            if "up" in args:
                if project == "afp-caddy":
                    return 0, "", ""
                tag = env["AFP_TAG"]
                self.running[project] = tag
                if tag in self.broken:
                    return 1, "", f"container {project}-web-1 failed to start"
                return 0, "", ""
            if "down" in args:
                self.running.pop(project, None)
                return 0, "", ""
            if "ps" in args:
                return 0, ("abc123\n" if project in self.running else ""), ""
            return 0, "", ""  # exec caddy reload
        if args[:2] == ["docker", "run"] and "mysqldump" in args:
            assert stdout_path is not None
            stdout_path.write_text("-- dump\n")
            return 0, "", ""
        if args[0] == "docker":
            return 0, "", ""  # run mysql, login, network
        return 9, "", f"unexpected command: {line}"


def make_ctx(tmp_path: Path, world: Any) -> cli.Context:
    paths = cli.Paths(code=ROOT, caddy_dir=tmp_path / "caddy", run_dir=tmp_path / "run", log_dir=tmp_path / "log",
                      projects_dir=tmp_path / "projects", work_dir=tmp_path / "work")
    log = Log(paths.log_dir / "test.log", echo=io.StringIO())
    return cli.Context(paths=paths, log=log, runner=world, oci=Oci(world, REGION))  # type: ignore[arg-type]
