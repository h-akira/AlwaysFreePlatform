"""Docker's daemon.json written by afp: rotated json-file logs with the compose
labels, written only when it differs. Only afp writes it."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afp import docker_config  # noqa: E402

BOOTSTRAP = (ROOT / "terraform" / "modules" / "compute" / "afp-bootstrap.sh").read_text()
LABELS = "com.docker.compose.project,com.docker.compose.service"


def test_it_is_rotated_json_file_logs_with_the_compose_labels() -> None:
    written = json.loads(docker_config.render())
    assert written == {
        "log-driver": "json-file",
        "log-opts": {"max-size": "10m", "max-file": "3", "labels": LABELS},
    }


def test_the_bootstrap_does_not_write_it() -> None:
    # Two writers made Docker restart twice on every boot.
    assert "put_file /etc/docker/daemon.json" not in BOOTSTRAP
    assert "restart docker" not in BOOTSTRAP


def test_it_writes_only_when_it_differs(tmp_path: Path) -> None:
    path = tmp_path / "etc" / "docker" / "daemon.json"
    assert docker_config.write_daemon_json(path) is True
    assert json.loads(path.read_text()) == docker_config.DAEMON_CONFIG
    assert path.stat().st_mode & 0o777 == 0o644
    mtime = path.stat().st_mtime_ns
    assert docker_config.write_daemon_json(path) is False
    assert path.stat().st_mtime_ns == mtime


def test_it_replaces_an_older_file(tmp_path: Path) -> None:
    # The VMs started before this change have the bootstrap's file without labels.
    path = tmp_path / "daemon.json"
    path.write_text(json.dumps({"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}))
    assert docker_config.write_daemon_json(path) is True
    assert json.loads(path.read_text())["log-opts"]["labels"] == LABELS
    assert docker_config.write_daemon_json(path) is False
