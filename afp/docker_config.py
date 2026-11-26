"""Docker's daemon.json: the json-file log driver, rotated, with each line
labelled by its compose project and service (read by the VM's logging agent).

Docker reads daemon.json only when it starts, and the log options apply only
to containers created after that. Restarting Docker is left to the caller.
"""

from __future__ import annotations

import json
from pathlib import Path

from afp.caddy import write_if_changed

DAEMON_JSON = Path("/etc/docker/daemon.json")

DAEMON_CONFIG = {
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3",
        "labels": "com.docker.compose.project,com.docker.compose.service",
    },
}


def render() -> str:
    return json.dumps(DAEMON_CONFIG, indent=2) + "\n"


def write_daemon_json(path: Path) -> bool:
    """Write daemon.json if it differs; tell whether it changed."""
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    return write_if_changed(path, render())
