"""The hourly checks of the platform: afp check-db and afp check-disk.

Each sends one data point of a custom metric that an alarm watches
(terraform/modules/alarm). They take no lock: they only read, and they must
not wait for a deploy.
"""

from __future__ import annotations

import shutil
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from afp import db
from afp.config import Config
from afp.errors import AfpError

if TYPE_CHECKING:
    from afp.cli import Context

NAMESPACE = "afp"
CHECK_DB_METRIC = "check_db_ok"
DISK_METRIC = "disk_used_percent"
# The boot volume: Docker's images, containers and logs, and afp's files.
DISK_PATH = Path("/")


def post(ctx: Context, cfg: Config, name: str, value: float, command: str) -> None:
    if not cfg.compartment_id:
        raise AfpError("afp.json has no compartment_id; run make apply")
    try:
        ctx.need_oci().post_metric(cfg.compartment_id, NAMESPACE, name, value, {"command": command})
    except Exception as e:
        raise AfpError(f"cannot send the metric {NAMESPACE}/{name} = {value}: {e}") from e
    ctx.log.info(f"sent the metric {NAMESPACE}/{name} = {value}")


def check_db(ctx: Context, cfg: Config) -> str:
    """Ask the DB SELECT 1 as the admin user; send check_db_ok (1: it answered,
    0: it did not, or its admin password could not be read)."""
    try:
        password = ctx.need_oci().secret(cfg.db.admin_secret_id)
        db.run_sql(ctx.runner, db.mysql_image(ctx.paths.code), cfg.db, password, "SELECT 1;\n")
    except Exception as e:  # the metric is sent all the same
        ctx.log.detail(traceback.format_exc())
        post(ctx, cfg, CHECK_DB_METRIC, 0, "check-db")
        raise AfpError(f"the DB did not answer: {e}; sent {CHECK_DB_METRIC} = 0") from e
    post(ctx, cfg, CHECK_DB_METRIC, 1, "check-db")
    return f"the DB answered; sent {CHECK_DB_METRIC} = 1"


def disk_used_percent(path: Path = DISK_PATH) -> float:
    """Used space in percent, as df counts it: the space kept for root counts
    as neither used nor free."""
    usage = shutil.disk_usage(path)
    return round(100 * usage.used / (usage.used + usage.free), 1)


def check_disk(ctx: Context, cfg: Config, path: Path = DISK_PATH) -> str:
    """Send how full the VM's disk is (disk_used_percent)."""
    value = disk_used_percent(path)
    post(ctx, cfg, DISK_METRIC, value, "check-disk")
    return f"{path} is {value}% used; sent {DISK_METRIC} = {value}"
