import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rm_values  # noqa: E402

SCRIPT = Path(rm_values.__file__)


def test_strings_stay_and_others_become_json() -> None:
    tfvars = {
        "home_cidrs": ["192.0.2.10/32", "198.51.100.0/24"],
        "db_admin_username": "afpadmin",
        "availability_domain_index": 1,
        "flag": True,
    }
    assert rm_values.to_rm_variables(tfvars) == {
        "home_cidrs": '["192.0.2.10/32","198.51.100.0/24"]',
        "db_admin_username": "afpadmin",
        "availability_domain_index": "1",
        "flag": "true",
    }


def test_tenancy_and_region_are_passed() -> None:
    # Stacks created from the CLI do not get these from Resource Manager.
    tfvars = {"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"}
    assert rm_values.to_rm_variables(tfvars) == tfvars


def test_null_is_rejected() -> None:
    with pytest.raises(ValueError):
        rm_values.to_rm_variables({"x": None})


def test_select_keys_keeps_only_given_keys() -> None:
    tfvars = {"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}
    assert rm_values.select_keys(tfvars, ["tenancy_ocid", "region"]) == {
        "tenancy_ocid": "ocid1.tenancy.oc1..xxxx",
        "region": "us-ashburn-1",
    }


def test_select_keys_rejects_missing() -> None:
    with pytest.raises(ValueError, match="region"):
        rm_values.select_keys({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx"}, ["tenancy_ocid", "region"])


def test_state_outputs_skips_sensitive() -> None:
    state = {
        "outputs": {
            "db_ip": {"value": "10.0.1.5", "type": "string"},
            "db_port": {"value": 3306, "type": "number"},
            "secret": {"value": "s3cr3t", "type": "string", "sensitive": True},
        }
    }
    assert rm_values.state_outputs(state) == {"db_ip": "10.0.1.5", "db_port": "3306"}


def test_cli_get_and_variables(tmp_path: Path) -> None:
    path = tmp_path / "terraform.tfvars.json"
    path.write_text(json.dumps({"region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}))

    got = subprocess.run([sys.executable, SCRIPT, "get", path, "region"], capture_output=True, text=True, check=True)
    assert got.stdout.strip() == "us-ashburn-1"

    missing = subprocess.run([sys.executable, SCRIPT, "get", path, "nope"], capture_output=True, text=True)
    assert missing.returncode == 1

    variables = subprocess.run([sys.executable, SCRIPT, "variables", path], capture_output=True, text=True, check=True)
    assert json.loads(variables.stdout) == {"region": "us-ashburn-1", "home_cidrs": '["192.0.2.10/32"]'}


def test_cli_variables_take_everything_from_the_file(tmp_path: Path) -> None:
    # The main stack: the notification email is in the (private) file too,
    # and nothing comes from the environment.
    path = tmp_path / "terraform.tfvars.json"
    path.write_text(json.dumps({"region": "us-ashburn-1", "notification_email": "admin@example.com", "dns_zone": "afp.example.com"}))
    env = {**os.environ, "AFP_NOTIFICATION_EMAIL": "other@example.net"}
    main = subprocess.run([sys.executable, SCRIPT, "variables", path], capture_output=True, text=True, env=env, check=True)
    assert json.loads(main.stdout) == {"region": "us-ashburn-1", "notification_email": "admin@example.com", "dns_zone": "afp.example.com"}

    # The base stack selects its keys and gets no email.
    base = subprocess.run([sys.executable, SCRIPT, "variables", path, "region,dns_zone"], capture_output=True, text=True, check=True)
    assert json.loads(base.stdout) == {"region": "us-ashburn-1", "dns_zone": "afp.example.com"}


def test_cli_variables_with_keys(tmp_path: Path) -> None:
    path = tmp_path / "terraform.tfvars.json"
    path.write_text(json.dumps({"region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}))

    only = subprocess.run(
        [sys.executable, SCRIPT, "variables", path, "region"], capture_output=True, text=True, check=True
    )
    assert json.loads(only.stdout) == {"region": "us-ashburn-1"}

    missing = subprocess.run([sys.executable, SCRIPT, "variables", path, "region,tenancy_ocid"], capture_output=True, text=True)
    assert missing.returncode == 1
    assert "not set: tenancy_ocid" in missing.stderr
    assert "Traceback" not in missing.stderr

    # An empty key list selects nothing.
    empty = subprocess.run([sys.executable, SCRIPT, "variables", path, ","], capture_output=True, text=True, check=True)
    assert json.loads(empty.stdout) == {}


def test_execution_result() -> None:
    done = {"data": {"lifecycle-state": "FAILED", "content": {"exit-code": 3, "text": "boom"}}}
    assert rm_values.execution_result(done) == ("FAILED", "3", "boom")
    waiting = {"data": {"lifecycle-state": "ACCEPTED", "content": None}}
    assert rm_values.execution_result(waiting) == ("ACCEPTED", "-", "")


@pytest.fixture
def sudo_env(tmp_path: Path) -> dict[str, str]:
    """PATH with a fake sudo that allows `-l` once the file `allowed` exists,
    and counts its calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "sudo"
    fake.write_text(f'#!/bin/sh\necho x >> "{tmp_path}/calls"\n[ -e "{tmp_path}/allowed" ]\n')
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def test_command_content_keeps_the_end_and_the_exit_code(sudo_env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "allowed").touch()
    script = "seq 1 2000; echo \"done $((1+1))\" 'x'; exit 3"
    out = subprocess.run([sys.executable, str(SCRIPT), "command-content", script],
                         capture_output=True, text=True, check=True).stdout
    text = json.loads(out)["source"]["text"]
    result = subprocess.run(["sh", "-c", text], capture_output=True, text=True, env=sudo_env)
    assert result.returncode == 3
    assert result.stdout.endswith("2000\ndone 2 x\n")
    assert len(result.stdout.encode()) <= rm_values.OUTPUT_TAIL_BYTES


def test_wrapped_script_passes_success(sudo_env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "allowed").touch()
    result = subprocess.run(["sh", "-c", rm_values.wrap_script("echo ok >&2")], capture_output=True, text=True, env=sudo_env)
    assert (result.returncode, result.stdout) == (0, "ok\n")


def test_wrapped_script_waits_for_the_sudo_rule(sudo_env: dict[str, str], tmp_path: Path) -> None:
    # The rule appears while the wrapper waits (written by the 2nd sleep's end).
    script = rm_values.wrap_script("echo ran", tries=5, interval=0).replace(
        "  sleep 0\n", f'  sleep 0; [ "$i" -ge 2 ] && touch "{tmp_path}/allowed"\n')
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=sudo_env)
    assert (result.returncode, result.stdout) == (0, "ran\n")
    assert len((tmp_path / "calls").read_text().splitlines()) == 3


def test_wrapped_script_gives_up_without_running(sudo_env: dict[str, str]) -> None:
    result = subprocess.run(["sh", "-c", rm_values.wrap_script("echo ran", tries=3, interval=0)],
                            capture_output=True, text=True, env=sudo_env)
    assert result.returncode == 1
    assert "ran" not in result.stdout and "first boot" in result.stdout


PREFIX = "iad.ocir.io/ns/repo-afp-hello"


def test_build_services_takes_only_built_ones() -> None:
    config = {"services": {
        "web": {"build": {"context": "."}, "image": f"{PREFIX}/web:v1"},
        "worker": {"build": {"context": "."}, "image": f"{PREFIX}/worker:v1"},
        "redis": {"image": "redis:7"},
    }}
    assert rm_values.build_services(config, PREFIX) == [("web", "repo-afp-hello/web"), ("worker", "repo-afp-hello/worker")]


@pytest.mark.parametrize("image", ["", "web:v1", f"{PREFIX}/web", "iad.ocir.io/ns/repo-afp-other/web:v1"])
def test_build_services_refuses_other_images(image: str) -> None:
    with pytest.raises(ValueError):
        rm_values.build_services({"services": {"web": {"build": {}, "image": image}}}, PREFIX)


def test_build_services_needs_one() -> None:
    with pytest.raises(ValueError, match="nothing to build"):
        rm_values.build_services({"services": {"redis": {"image": "redis:7"}}}, PREFIX)


def _tree(top: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = top / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return top


def test_pack_terraform_takes_the_files_as_they_are(tmp_path: Path) -> None:
    # Not a git repository: what is on disk is sent (ADR 038).
    top = _tree(tmp_path / "terraform", {
        "main/main.tf": "a", "modules/x/main.tf": "b",
        "main/.terraform/providers/p": "cache", "main/terraform.tfstate": "state",
    })
    first = rm_values.pack_terraform(top, tmp_path / "a.zip")
    with zipfile.ZipFile(tmp_path / "a.zip") as z:
        assert sorted(z.namelist()) == ["main/main.tf", "modules/x/main.tf"]
    # The same files give the same hash; a change gives another.
    assert rm_values.pack_terraform(top, tmp_path / "b.zip") == first
    assert (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()
    (top / "main" / "main.tf").write_text("changed")
    assert rm_values.pack_terraform(top, tmp_path / "c.zip") != first


def test_pack_platform_takes_what_the_vm_uses(tmp_path: Path) -> None:
    root = _tree(tmp_path / "platform", {name: "x" for name in [
        "afp/cli.py", "afp/__pycache__/cli.cpython-39.pyc", "bin/afp", "caddy/compose.yaml",
        "mysql/VERSION", "scripts/devops-release.sh", "tests/test_x.py", "terraform/main/main.tf",
    ]})
    (root / "bin" / "afp").chmod(0o755)
    first = rm_values.pack_platform(root, tmp_path / "a.tar.gz")
    with tarfile.open(tmp_path / "a.tar.gz") as tar:
        assert sorted(tar.getnames()) == ["afp/cli.py", "bin/afp", "caddy/compose.yaml",
                                          "mysql/VERSION", "scripts/devops-release.sh"]
        assert tar.getmember("bin/afp").mode == 0o755 and tar.getmember("afp/cli.py").mode == 0o644
    assert rm_values.pack_platform(root, tmp_path / "b.tar.gz") == first
    assert (tmp_path / "a.tar.gz").read_bytes() == (tmp_path / "b.tar.gz").read_bytes()
    (root / "bin" / "afp").chmod(0o644)  # the executable bit counts
    assert rm_values.pack_platform(root, tmp_path / "c.tar.gz") != first


def test_pack_platform_needs_every_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path / "platform", {"afp/cli.py": "x"})
    with pytest.raises(ValueError, match="bin"):
        rm_values.pack_platform(root, tmp_path / "a.tar.gz")
