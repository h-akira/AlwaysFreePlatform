"""The weekly backup: a systemd timer that runs afp backup for every project.

Sunday 18:00 UTC (Monday 3:00 in Japan). Persistent: a run missed while the
VM was off is made when it is back. The result goes to the metric that the
alarm watches (afp backup).
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
TIMER = "afp-backup.timer"

UNITS = {
    "afp-backup.service": f"""\
[Unit]
Description=Dump every project's DB to the dumps bucket (afp backup)
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart={AFP} backup
""",
    TIMER: """\
[Unit]
Description=Weekly afp backup

[Timer]
OnCalendar=Sun *-*-* 18:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
""",
}


def install(ctx: Context, unit_dir: Path = UNIT_DIR) -> bool:
    """Put the units, reload systemd if they changed, enable and start the
    timer. Idempotent; True when a unit changed."""
    changed = False
    for name, content in UNITS.items():
        changed = write_if_changed(unit_dir / name, content) or changed
    if changed:
        ctx.runner.run(["systemctl", "daemon-reload"])
    ctx.runner.run(["systemctl", "enable", "--now", TIMER])
    return changed
