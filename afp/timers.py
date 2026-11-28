"""The systemd timers that run afp on the VM by themselves.

- afp-backup.timer: afp backup for every project, Sunday 18:00 UTC (Monday
  3:00 in Japan). Persistent: a run missed while the VM was off is made when
  it is back.
- afp-check-db.timer: afp check-db, every hour.
- afp-check-disk.timer: afp check-disk, every hour.

Each run sends a metric that an alarm watches (terraform/modules/alarm).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from afp.caddy import write_if_changed

if TYPE_CHECKING:
    from afp.cli import Context

UNIT_DIR = Path("/etc/systemd/system")
# Where afp-bootstrap puts the platform code (terraform/modules/compute/afp-bootstrap.sh).
AFP = "/opt/afp/current/bin/afp"


def _service(description: str, command: str) -> str:
    return f"""\
[Unit]
Description={description}
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart={AFP} {command}
"""


def _timer(description: str, calendar: str, persistent: bool) -> str:
    return f"""\
[Unit]
Description={description}

[Timer]
OnCalendar={calendar}
Persistent={"true" if persistent else "false"}

[Install]
WantedBy=timers.target
"""


UNITS = {
    "afp-backup.service": _service("Dump every project's DB to the dumps bucket (afp backup)", "backup"),
    "afp-backup.timer": _timer("Weekly afp backup", "Sun *-*-* 18:00:00 UTC", persistent=True),
    "afp-check-db.service": _service("Check that the DB answers (afp check-db)", "check-db"),
    "afp-check-db.timer": _timer("Hourly afp check-db", "hourly", persistent=False),
    "afp-check-disk.service": _service("Send how full the VM's disk is (afp check-disk)", "check-disk"),
    "afp-check-disk.timer": _timer("Hourly afp check-disk", "hourly", persistent=False),
}
TIMERS = [name for name in UNITS if name.endswith(".timer")]


def install(ctx: Context, unit_dir: Path = UNIT_DIR) -> bool:
    """Put the units, reload systemd if they changed, enable and start the
    timers. Idempotent; True when a unit changed."""
    changed = False
    for name, content in UNITS.items():
        changed = write_if_changed(unit_dir / name, content) or changed
    if changed:
        ctx.runner.run(["systemctl", "daemon-reload"])
    ctx.runner.run(["systemctl", "enable", "--now", *TIMERS])
    return changed
