#!/usr/bin/env python3
"""Keep the GitHub triggers of OCI DevOps in line with the projects (stdlib only).

Terraform cannot make these triggers: the API returns a trigger's webhook
secret only in the response to its creation, and the OCI provider drops it.
scripts/stack.sh therefore runs this around its Resource Manager jobs, so that
make apply and make destroy still bring everything in line with the settings.

Usage: triggers.py prune|create|delete-all
  prune       Before apply: delete the triggers of projects that no longer have
              a repository in terraform.tfvars.json.
  create      After apply: create the trigger of each project in the stack
              output "pipelines" that has none (or whose trigger points at
              another build pipeline), and put its webhook secret into the
              project's Vault secret. The secret is never printed; the trigger
              URL and the name of the Vault secret are, for the GitHub webhook.
  delete-all  Before destroy: delete every trigger of the DevOps project.

Reads the main stack outputs (KEY=VALUE lines, as `stack.sh main outputs`
prints them) from stdin. A trigger is found by its name, afp-<project>; what
it filters is fixed here, not in the settings.

Environment:
  AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
  OCI_CLI_PROFILE, OCI_CLI_AUTH, ...  Passed through to the OCI CLI.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Which pushes start a build: tags v* (ADR 015).
HEAD_REF = "refs/tags/v*"
EVENTS = ["PUSH"]


class TriggerError(Exception):
    pass


def trigger_name(project: str) -> str:
    return f"afp-{project}"


def parse_outputs(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key] = value
    return result


def desired_projects(tfvars: dict[str, Any]) -> set[str]:
    """Projects that get a pipeline: those with a repository."""
    return {p["name"] for p in tfvars.get("projects") or [] if p.get("repository")}


def actions(build_pipeline_id: str) -> list[dict[str, Any]]:
    return [{
        "type": "TRIGGER_BUILD_PIPELINE",
        "buildPipelineId": build_pipeline_id,
        "filter": {"triggerSource": "GITHUB", "events": EVENTS, "include": {"headRef": HEAD_REF}},
    }]


class Oci:
    """Thin wrapper over the OCI CLI; every call returns parsed JSON or None."""

    def __init__(self, region: str) -> None:
        self.region = region

    def run(self, *args: str) -> Any:
        proc = subprocess.run(["oci", "--region", self.region, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            # The CLI's error text never holds a secret: secrets only come
            # back in the output of a successful create.
            raise TriggerError(f"oci {args[0]} {args[1]} {args[2]} failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def list_triggers(self, project_id: str) -> dict[str, str]:
        """Active triggers of the DevOps project: name => OCID."""
        data = self.run("devops", "trigger", "list", "--project-id", project_id, "--lifecycle-state", "ACTIVE", "--all")
        items = (data or {}).get("data", {}).get("items", [])
        return {item["display-name"]: item["id"] for item in items}

    def trigger_pipeline(self, trigger_id: str) -> str | None:
        data = self.run("devops", "trigger", "get", "--trigger-id", trigger_id)
        acts = (data or {}).get("data", {}).get("actions") or []
        return acts[0].get("build-pipeline-id") if acts else None

    def delete_trigger(self, trigger_id: str) -> None:
        self.run("devops", "trigger", "delete", "--trigger-id", trigger_id, "--force", "--wait-for-state", "SUCCEEDED")

    def create_trigger(self, project_id: str, connection_id: str, name: str, build_pipeline_id: str) -> tuple[str, str, str]:
        """Create a GitHub trigger; return (OCID, URL, webhook secret).

        Without --wait-for-state: with it, the CLI prints the work request
        instead of the response, and the secret is lost."""
        data = self.run(
            "devops", "trigger", "create-github-trigger",
            "--project-id", project_id, "--connection-id", connection_id, "--display-name", name,
            "--description", "AlwaysFreePlatform: made by make apply (scripts/triggers.py)",
            "--actions", json.dumps(actions(build_pipeline_id)),
        )
        d = (data or {}).get("data", {})
        if not d.get("id") or not d.get("secret") or not d.get("trigger-url"):
            raise TriggerError(f"create-github-trigger for {name} returned no id, URL or secret")
        return d["id"], d["trigger-url"], d["secret"]

    def put_secret(self, secret_id: str, value: str) -> None:
        """New version of a Vault secret. The value goes through a private
        file, not the command line, so that other processes cannot see it."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"secretId": secret_id, "secretContentContent": base64.b64encode(value.encode()).decode()}, f)
            self.run("vault", "secret", "update-base64", "--from-json", f"file://{path}", "--force")


def prune(oci: Oci, outputs: dict[str, str], tfvars: dict[str, Any]) -> None:
    project_id = outputs.get("devops_project_id")
    if not project_id:
        return  # no DevOps project yet
    keep = {trigger_name(p) for p in desired_projects(tfvars)}
    for name, trigger_id in sorted(oci.list_triggers(project_id).items()):
        if name not in keep:
            print(f"Deleting trigger {name} (its project has no repository any more) ...")
            oci.delete_trigger(trigger_id)


def create(oci: Oci, outputs: dict[str, str]) -> None:
    project_id = outputs.get("devops_project_id")
    connection_id = outputs.get("devops_connection_id")
    if not project_id or not connection_id:
        raise TriggerError("stack outputs devops_project_id / devops_connection_id are missing")
    pipelines: dict[str, dict[str, str]] = json.loads(outputs.get("pipelines") or "{}")
    existing = oci.list_triggers(project_id)
    for project, p in sorted(pipelines.items()):
        name = trigger_name(project)
        if name in existing:
            if oci.trigger_pipeline(existing[name]) == p["build_pipeline_id"]:
                continue
            print(f"Trigger {name} points at another build pipeline; recreating it ...")
            oci.delete_trigger(existing[name])
        print(f"Creating trigger {name} ...")
        trigger_id, url, secret = oci.create_trigger(project_id, connection_id, name, p["build_pipeline_id"])
        try:
            oci.put_secret(p["webhook_secret_id"], secret)
        except TriggerError:
            # A trigger whose secret nobody knows is useless; the next apply
            # creates it again.
            oci.delete_trigger(trigger_id)
            raise
        print(
            f"Created trigger {name}. Register a webhook in the GitHub repository of {project}:\n"
            f"  Payload URL: {url}\n"
            f"  Secret:      Vault secret {p['webhook_secret_name']} (Versions > View Secret Contents > Copy secret)\n"
            "  Content type: application/json; events: Just the push event."
        )


def delete_all(oci: Oci, outputs: dict[str, str]) -> None:
    project_id = outputs.get("devops_project_id")
    if not project_id:
        print("No DevOps project in the stack's outputs; no triggers to delete.")
        return
    for name, trigger_id in sorted(oci.list_triggers(project_id).items()):
        print(f"Deleting trigger {name} ...")
        oci.delete_trigger(trigger_id)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("prune", "create", "delete-all"):
        print(__doc__, file=sys.stderr)
        return 2
    config_dir = os.environ.get("AFP_CONFIG_DIR")
    if not config_dir:
        print("triggers.py: AFP_CONFIG_DIR is not set", file=sys.stderr)
        return 1
    with open(Path(config_dir) / "terraform.tfvars.json", encoding="utf-8") as f:
        tfvars = json.load(f)
    oci = Oci(tfvars["region"])
    outputs = parse_outputs(sys.stdin.read())
    try:
        if argv[0] == "prune":
            prune(oci, outputs, tfvars)
        elif argv[0] == "create":
            create(oci, outputs)
        else:
            delete_all(oci, outputs)
    except TriggerError as e:
        print(f"triggers.py: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
