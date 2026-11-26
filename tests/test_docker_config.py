"""Docker's daemon.json written by afp: the bootstrap's log settings plus the
compose labels, written only when it differs."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afp import docker_config  # noqa: E402

BOOTSTRAP = (ROOT / "terraform" / "modules" / "compute" / "afp-bootstrap.sh").read_text()
LABELS = "com.docker.compose.project,com.docker.compose.service"


def _bootstrap_daemon_json() -> dict:
    [body] = re.findall(r"put_file /etc/docker/daemon\.json 0644 <<'EOF'\n(.*?)\nEOF\n", BOOTSTRAP, re.S)
    return json.loads(body)


def test_it_is_the_bootstrap_settings_plus_the_compose_labels() -> None:
    written = json.loads(docker_config.render())
    expected = _bootstrap_daemon_json()
    expected["log-opts"]["labels"] = LABELS
    assert written == expected
    assert written["log-driver"] == "json-file"
    assert written["log-opts"] == {"max-size": "10m", "max-file": "3", "labels": LABELS}


def test_it_writes_only_when_it_differs(tmp_path: Path) -> None:
    path = tmp_path / "etc" / "docker" / "daemon.json"
    assert docker_config.write_daemon_json(path) is True
    assert json.loads(path.read_text()) == docker_config.DAEMON_CONFIG
    assert path.stat().st_mode & 0o777 == 0o644
    mtime = path.stat().st_mtime_ns
    assert docker_config.write_daemon_json(path) is False
    assert path.stat().st_mtime_ns == mtime


def test_it_replaces_what_the_bootstrap_wrote(tmp_path: Path) -> None:
    path = tmp_path / "daemon.json"
    path.write_text(json.dumps(_bootstrap_daemon_json()))
    assert docker_config.write_daemon_json(path) is True
    assert json.loads(path.read_text())["log-opts"]["labels"] == LABELS
    assert docker_config.write_daemon_json(path) is False
