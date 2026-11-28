"""Tests for the systemd timers of afp (afp.timers)."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

from afp_world import ROOT

from afp import cli, timers
from afp.log import Log


class Systemctl:
    """Records the commands; every one succeeds."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")


def ctx(tmp_path: Path, runner: Systemctl) -> cli.Context:
    log = Log(tmp_path / "log" / "test.log", echo=io.StringIO())
    return cli.Context(paths=cli.Paths(code=ROOT), log=log, runner=runner, oci=None)  # type: ignore[arg-type]


def test_units(tmp_path: Path) -> None:
    timers.install(ctx(tmp_path, Systemctl()), unit_dir=tmp_path)
    service = (tmp_path / "afp-backup.service").read_text()
    assert "Type=oneshot\n" in service
    assert "ExecStart=/opt/afp/current/bin/afp backup\n" in service  # every project: no argument
    timer = (tmp_path / "afp-backup.timer").read_text()
    assert "OnCalendar=Sun *-*-* 18:00:00 UTC\n" in timer
    assert "Persistent=true\n" in timer
    assert "[Install]\nWantedBy=timers.target\n" in timer
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == [
        "afp-backup.service", "afp-backup.timer", "afp-check-db.service", "afp-check-db.timer",
        "afp-check-disk.service", "afp-check-disk.timer",
    ]
    assert (tmp_path / "afp-backup.timer").stat().st_mode & 0o777 == 0o644


def test_the_checks_run_every_hour(tmp_path: Path) -> None:
    timers.install(ctx(tmp_path, Systemctl()), unit_dir=tmp_path)
    for check in ("check-db", "check-disk"):
        assert f"ExecStart=/opt/afp/current/bin/afp {check}\n" in (tmp_path / f"afp-{check}.service").read_text()
        timer = (tmp_path / f"afp-{check}.timer").read_text()
        assert "OnCalendar=hourly\n" in timer
        assert "Persistent=false\n" in timer  # a missed hour is not made up
        assert "[Install]\nWantedBy=timers.target\n" in timer


def test_the_service_is_the_bootstraps_afp() -> None:
    bootstrap = (ROOT / "terraform/modules/compute/afp-bootstrap.sh").read_text()
    assert 'AFP_DIR="/opt/afp"' in bootstrap and '"$AFP_DIR/current/bin/afp" install' in bootstrap
    assert timers.AFP == "/opt/afp/current/bin/afp"


def test_idempotent(tmp_path: Path) -> None:
    runner = Systemctl()
    assert timers.install(ctx(tmp_path, runner), unit_dir=tmp_path) is True
    assert runner.calls == [["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", "afp-backup.timer", "afp-check-db.timer", "afp-check-disk.timer"]]
    runner.calls.clear()
    assert timers.install(ctx(tmp_path, runner), unit_dir=tmp_path) is False
    assert runner.calls == [["systemctl", "enable", "--now", "afp-backup.timer", "afp-check-db.timer", "afp-check-disk.timer"]]  # no daemon-reload


def test_a_changed_unit_is_rewritten_and_reloaded(tmp_path: Path) -> None:
    runner = Systemctl()
    timers.install(ctx(tmp_path, runner), unit_dir=tmp_path)
    (tmp_path / "afp-backup.service").write_text("old\n")
    runner.calls.clear()
    assert timers.install(ctx(tmp_path, runner), unit_dir=tmp_path) is True
    assert (tmp_path / "afp-backup.service").read_text() == timers.UNITS["afp-backup.service"]
    assert ["systemctl", "daemon-reload"] in runner.calls
