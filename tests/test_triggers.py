"""Tests for scripts/triggers.py against a fake `oci` on PATH (no OCI access)."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "triggers.py"
SECRET = "s3cr3t-webhook-value"

# Fake CLI: keeps the triggers and the Vault secrets in state.json, logs every
# call to calls.jsonl, and copies the --from-json file of a secret creation
# (deleted right after by triggers.py) to secret-put.json. FAIL_ON names a
# subcommand that fails.
FAKE_OCI = r'''#!{python}
import json, os, sys
from pathlib import Path
d = Path({dir!r})
args = sys.argv[1:]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(args) + "\n")
state = json.loads((d / "state.json").read_text())
triggers, secrets = state["triggers"], state["secrets"]
cmd = args[2:5]  # after --region R
def opt(name):
    return args[args.index(name) + 1]
if os.environ.get("FAIL_ON") and os.environ["FAIL_ON"] in args:
    print("ServiceError: fake failure", file=sys.stderr); sys.exit(1)
if cmd == ["devops", "trigger", "list"]:
    print(json.dumps({{"data": {{"items": [{{"display-name": n, "id": t["id"]}} for n, t in triggers.items()]}}}}))
elif cmd == ["devops", "trigger", "get"]:
    t = next(t for t in triggers.values() if t["id"] == opt("--trigger-id"))
    f = {{"events": t.get("events", ["PUSH"]), "include": {{"head-ref": t.get("head_ref", "release")}}}}
    print(json.dumps({{"data": {{"actions": [{{"build-pipeline-id": t["pipeline"], "filter": f}}]}}}}))
elif cmd == ["devops", "trigger", "update-github-trigger"]:
    t = next(t for t in triggers.values() if t["id"] == opt("--trigger-id"))
    a = json.loads(opt("--actions"))[0]
    t["pipeline"] = a["buildPipelineId"]
    t["events"] = a["filter"]["events"]
    t["head_ref"] = a["filter"]["include"]["headRef"]
elif cmd == ["devops", "trigger", "delete"]:
    tid = opt("--trigger-id")
    state["triggers"] = {{n: t for n, t in triggers.items() if t["id"] != tid}}
elif cmd == ["devops", "trigger", "create-github-trigger"]:
    name = opt("--display-name")
    pipeline = json.loads(opt("--actions"))[0]["buildPipelineId"]
    tid = "ocid1.devopstrigger.oc1..new-" + name
    triggers[name] = {{"id": tid, "pipeline": pipeline}}
    print(json.dumps({{"data": {{"id": tid, "trigger-url": "https://devops.example.com/" + name, "secret": {secret!r}}}}}))
elif cmd == ["vault", "secret", "list"]:
    items = [{{"id": i, "secret-name": s["name"], "freeform-tags": s["tags"]}}
             for i, s in secrets.items() if s["state"] == "ACTIVE"]
    print(json.dumps({{"data": items}}))
elif cmd == ["vault", "secret", "create-base64"]:
    path = opt("--from-json").removeprefix("file://")
    body = json.loads(Path(path).read_text())
    (d / "secret-put.json").write_text(json.dumps(body))
    (d / "secret-mode").write_text(oct(os.stat(path).st_mode & 0o777))
    sid = "ocid1.vaultsecret.oc1..new-" + body["secretName"]
    secrets[sid] = {{"name": body["secretName"], "tags": body["freeformTags"], "state": "ACTIVE"}}
    print(json.dumps({{"data": {{"id": sid}}}}))
elif cmd == ["vault", "secret", "schedule-secret-deletion"]:
    secrets[opt("--secret-id")]["state"] = "PENDING_DELETION"
else:
    print("unexpected: " + " ".join(args), file=sys.stderr); sys.exit(3)
(d / "state.json").write_text(json.dumps(state))
'''

OUTPUTS = {
    "devops_project_id": "ocid1.devopsproject.oc1..p",
    "devops_connection_id": "ocid1.devopsconnection.oc1..c",
    "compartment_id": "ocid1.compartment.oc1..afp",
    "vault_id": "ocid1.vault.oc1..v",
    "key_id": "ocid1.key.oc1..k",
    "pipelines": json.dumps({"hello": {"build_pipeline_id": "ocid1.devopsbuildpipeline.oc1..hello"}}),
}
HELLO_SECRET = {"ocid1.vaultsecret.oc1..wh": {"name": "secret-afp-hello-webhook-abcd", "tags": {"afp-webhook": "hello"}, "state": "ACTIVE"}}
# A secret the administrator made by hand; never touched here.
OTHER_SECRET = {"ocid1.vaultsecret.oc1..token": {"name": "github-token", "tags": {}, "state": "ACTIVE"}}


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        config = tmp_path / "config"
        config.mkdir()
        self.tfvars = config / "terraform.tfvars.json"
        self.set_projects([{"name": "hello", "repository": "https://github.com/example/afp-hello"}, {"name": "app-b"}])
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "oci"
        fake.write_text(FAKE_OCI.format(python=sys.executable, dir=str(tmp_path), secret=SECRET))
        fake.chmod(0o755)
        self.set_state({}, dict(OTHER_SECRET))
        self.env = dict(os.environ, AFP_CONFIG_DIR=str(config), PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    def set_projects(self, projects: list[dict[str, Any]]) -> None:
        self.tfvars.write_text(json.dumps({"region": "us-ashburn-1", "projects": projects}))

    def set_state(self, triggers: dict[str, dict[str, Any]], secrets: dict[str, dict[str, Any]]) -> None:
        (self.dir / "state.json").write_text(json.dumps({"triggers": triggers, "secrets": secrets}))

    def state(self) -> dict[str, Any]:
        return json.loads((self.dir / "state.json").read_text())

    def triggers(self) -> dict[str, dict[str, Any]]:
        return self.state()["triggers"]

    def active_secrets(self) -> dict[str, dict[str, Any]]:
        return {i: s for i, s in self.state()["secrets"].items() if s["state"] == "ACTIVE"}

    def calls(self) -> list[list[str]]:
        path = self.dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run(self, command: str, outputs: dict[str, str] | None = None, **env: str) -> subprocess.CompletedProcess[str]:
        text = "".join(f"{k}={v}\n" for k, v in (OUTPUTS if outputs is None else outputs).items())
        return subprocess.run([sys.executable, str(SCRIPT), command], input=text, env={**self.env, **env}, capture_output=True, text=True)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_create_makes_the_trigger_and_its_secret_without_printing_it(world: World) -> None:
    result = world.run("create")
    assert result.returncode == 0, result.stderr
    assert world.triggers() == {"trigger-afp-hello": {"id": "ocid1.devopstrigger.oc1..new-trigger-afp-hello", "pipeline": "ocid1.devopsbuildpipeline.oc1..hello"}}
    put = json.loads((world.dir / "secret-put.json").read_text())
    assert put["secretContentContent"] == base64.b64encode(SECRET.encode()).decode()
    assert (put["compartmentId"], put["vaultId"], put["keyId"]) == ("ocid1.compartment.oc1..afp", "ocid1.vault.oc1..v", "ocid1.key.oc1..k")
    assert put["freeformTags"] == {"afp-webhook": "hello"} and put["secretName"].startswith("secret-afp-hello-webhook-")
    assert (world.dir / "secret-mode").read_text() == "0o600"
    # The secret never reaches the output nor the command line of any process.
    assert SECRET not in result.stdout + result.stderr
    assert not any(SECRET in " ".join(c) for c in world.calls())
    assert "Payload URL: https://devops.example.com/trigger-afp-hello" in result.stdout
    sid = "ocid1.vaultsecret.oc1..new-" + put["secretName"]
    assert f"--region us-ashburn-1 --secret-id {sid} --query 'data.\"secret-bundle-content\".content' --raw-output | base64 -d" in result.stdout
    create = next(c for c in world.calls() if "create-github-trigger" in c)
    acts = json.loads(create[create.index("--actions") + 1])
    assert acts[0]["filter"] == {"triggerSource": "GITHUB", "events": ["PUSH"], "include": {"headRef": "release"}}
    assert "--wait-for-state" not in create  # with it, the CLI would not return the secret
    assert "ocid1.vaultsecret.oc1..token" in world.active_secrets()  # untouched


def test_create_is_idempotent(world: World) -> None:
    world.set_state({"trigger-afp-hello": {"id": "t1", "pipeline": "ocid1.devopsbuildpipeline.oc1..hello"}}, {**OTHER_SECRET, **HELLO_SECRET})
    result = world.run("create")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not any("create-github-trigger" in c or "delete" in c or "create-base64" in c for c in world.calls())


def test_create_recreates_a_trigger_without_its_secret(world: World) -> None:
    # E.g. a trigger whose secret Terraform used to hold (before ADR 039).
    world.set_state({"trigger-afp-hello": {"id": "t1", "pipeline": "ocid1.devopsbuildpipeline.oc1..hello"}}, dict(OTHER_SECRET))
    result = world.run("create")
    assert result.returncode == 0, result.stderr
    assert "has no webhook secret of its own; recreating it" in result.stdout
    assert world.triggers()["trigger-afp-hello"]["id"] != "t1"
    assert [s["tags"] for s in world.active_secrets().values()].count({"afp-webhook": "hello"}) == 1


def test_create_updates_the_filter_in_place(world: World) -> None:
    world.set_state({"trigger-afp-hello": {"id": "t1", "pipeline": "ocid1.devopsbuildpipeline.oc1..hello", "head_ref": "refs/tags/v*"}}, dict(HELLO_SECRET))
    result = world.run("create")
    assert result.returncode == 0, result.stderr
    # Same trigger (same URL and secret), new filter; no webhook to register again.
    assert world.triggers() == {"trigger-afp-hello": {"id": "t1", "pipeline": "ocid1.devopsbuildpipeline.oc1..hello", "events": ["PUSH"], "head_ref": "release"}}
    assert "Updating the filter" in result.stdout
    assert "Payload URL" not in result.stdout
    assert not any("create-github-trigger" in c or "delete" in c for c in world.calls())
    update = next(c for c in world.calls() if "update-github-trigger" in c)
    assert "--wait-for-state" in update


def test_create_replaces_a_trigger_of_another_pipeline_and_its_secret(world: World) -> None:
    world.set_state({"trigger-afp-hello": {"id": "t-old", "pipeline": "ocid1.devopsbuildpipeline.oc1..old"}}, dict(HELLO_SECRET))
    result = world.run("create")
    assert result.returncode == 0, result.stderr
    assert world.triggers()["trigger-afp-hello"]["pipeline"] == "ocid1.devopsbuildpipeline.oc1..hello"
    assert "recreating" in result.stdout
    assert "ocid1.vaultsecret.oc1..wh" not in world.active_secrets()  # the old secret goes with the old trigger


def test_create_deletes_the_trigger_when_the_secret_cannot_be_made(world: World) -> None:
    result = world.run("create", FAIL_ON="create-base64")
    assert result.returncode == 1
    assert world.triggers() == {}
    assert SECRET not in result.stdout + result.stderr


def test_create_fails_without_the_outputs_it_needs(world: World) -> None:
    result = world.run("create", outputs={"pipelines": OUTPUTS["pipelines"], "devops_connection_id": "null"})
    assert result.returncode == 1
    assert "devops_project_id" in result.stderr and "devops_connection_id" in result.stderr and "vault_id" in result.stderr


def test_create_does_nothing_without_pipelines(world: World) -> None:
    result = world.run("create", outputs={"pipelines": "{}"})
    assert result.returncode == 0, result.stderr
    assert world.calls() == []


def test_prune_deletes_only_triggers_and_secrets_of_projects_without_a_repository(world: World) -> None:
    app_b = {"ocid1.vaultsecret.oc1..whb": {"name": "secret-afp-app-b-webhook-ef01", "tags": {"afp-webhook": "app-b"}, "state": "ACTIVE"}}
    world.set_state({"trigger-afp-hello": {"id": "t1", "pipeline": "p1"}, "trigger-afp-app-b": {"id": "t2", "pipeline": "p2"}},
                    {**OTHER_SECRET, **HELLO_SECRET, **app_b})
    result = world.run("prune")
    assert result.returncode == 0, result.stderr
    assert set(world.triggers()) == {"trigger-afp-hello"}
    assert set(world.active_secrets()) == {"ocid1.vaultsecret.oc1..token", "ocid1.vaultsecret.oc1..wh"}


def test_prune_does_nothing_before_the_devops_project_exists(world: World) -> None:
    result = world.run("prune", outputs={})
    assert result.returncode == 0, result.stderr
    assert world.calls() == []


def test_delete_all_deletes_the_triggers_and_their_secrets(world: World) -> None:
    world.set_state({"trigger-afp-hello": {"id": "t1", "pipeline": "p1"}, "trigger-afp-app-b": {"id": "t2", "pipeline": "p2"}},
                    {**OTHER_SECRET, **HELLO_SECRET})
    result = world.run("delete-all")
    assert result.returncode == 0, result.stderr
    assert world.triggers() == {}
    assert set(world.active_secrets()) == {"ocid1.vaultsecret.oc1..token"}  # only what was made by hand stays
    deletes = [c for c in world.calls() if c[2:5] == ["devops", "trigger", "delete"]]
    assert all("--wait-for-state" in c for c in deletes)


def test_cli_failure_is_reported(world: World) -> None:
    result = world.run("create", FAIL_ON="list")
    assert result.returncode == 1
    assert "fake failure" in result.stderr


def test_usage(world: World) -> None:
    result = world.run("nope")
    assert result.returncode == 2
    assert "Usage: triggers.py" in result.stderr
