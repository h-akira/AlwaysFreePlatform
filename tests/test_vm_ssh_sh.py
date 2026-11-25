"""Tests for scripts/vm-ssh.sh that do not touch OCI (fake `oci` and `ssh` on PATH)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vm-ssh.sh"

FAKE_OCI = r'''
import json, os, sys
from pathlib import Path
d = Path(os.environ["FAKE_DIR"])
args = sys.argv[1:]
with open(d / "oci.log", "a") as f:
    f.write(json.dumps(args) + "\n")
line = " ".join(args)
if os.environ.get("FAKE_OCI_FAIL"):
    print("NotAuthenticated", file=sys.stderr)
    sys.exit(1)
if "stack list" in line:
    print("ocid1.ormstack.oc1..stack")
elif "get-stack-tf-state" in line:
    print(json.dumps({"outputs": {k: {"value": v} for k, v in {
        "bastion_id": "ocid1.bastion.oc1..b", "vm_id": "ocid1.instance.oc1..vm",
        "vm_private_ip": "10.0.0.5",
    }.items()}}))
elif "create-managed-ssh" in line:
    (d / "session.json").write_text(json.dumps(args))
    key = args[args.index("--ssh-public-key-file") + 1]
    (d / "session-key.pub").write_text(Path(key).read_text())
    print("ocid1.bastionsession.oc1..s")
elif "session get" in line:
    print("ACTIVE")
elif "session delete" in line:
    (d / "deleted").touch()
else:
    print("fake oci: unexpected " + line, file=sys.stderr)
    sys.exit(9)
'''

FAKE_SSH = r'''
import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_DIR"], "ssh.json").write_text(json.dumps(sys.argv[1:]))
'''


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config"
    config.mkdir()
    (config / "terraform.tfvars.json").write_text(
        json.dumps({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"})
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, code in (("oci", FAKE_OCI), ("ssh", FAKE_SSH)):
        (bin_dir / name).write_text(f"#!{sys.executable}\n{code}")
        (bin_dir / name).chmod(0o755)
    result = dict(os.environ)
    result.update({"AFP_CONFIG_DIR": str(config), "FAKE_DIR": str(tmp_path), "BASTION_KEY_WAIT_SECONDS": "0",
                   "PATH": f"{bin_dir}{os.pathsep}{result['PATH']}"})
    return result


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def test_one_throwaway_key_for_a_managed_ssh_session(env: dict[str, str], tmp_path: Path) -> None:
    result = run(env, "uptime")
    assert result.returncode == 0, result.stderr
    session = json.loads((tmp_path / "session.json").read_text())
    for flag, value in (("--target-resource-id", "ocid1.instance.oc1..vm"), ("--target-private-ip", "10.0.0.5"),
                        ("--target-port", "22"), ("--target-os-username", "opc")):
        assert session[session.index(flag) + 1] == value
    assert "afp-vm-ssh" in (tmp_path / "session-key.pub").read_text()
    ssh = json.loads((tmp_path / "ssh.json").read_text())
    assert ssh[-2:] == ["opc@10.0.0.5", "uptime"]
    key = ssh[ssh.index("-i") + 1]
    proxy = next(a.split("=", 1)[1] for a in ssh if a.startswith("ProxyCommand="))
    # The same throwaway key for the Bastion hop and the VM hop.
    assert f"-i {key} " in proxy and "IdentitiesOnly=yes" in proxy
    assert "ocid1.bastionsession.oc1..s@host.bastion.us-ashburn-1.oci.oraclecloud.com" in proxy
    assert (tmp_path / "deleted").exists()
    assert not Path(key).exists()


def test_afp_ssh_command_runs_without_arguments(env: dict[str, str], tmp_path: Path) -> None:
    env["AFP_SSH_COMMAND"] = "df -h"
    assert run(env).returncode == 0
    assert json.loads((tmp_path / "ssh.json").read_text())[-1] == "df -h"


def test_cli_failure_stops_without_a_session(env: dict[str, str], tmp_path: Path) -> None:
    env["FAKE_OCI_FAIL"] = "1"
    result = run(env)
    assert result.returncode == 1
    assert "cannot read the stack outputs" in result.stderr
    assert "create-managed-ssh" not in (tmp_path / "oci.log").read_text()
