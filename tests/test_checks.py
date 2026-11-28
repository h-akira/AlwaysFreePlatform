"""Tests for the hourly checks afp check-db and afp check-disk (afp.checks),
on the fake VM of tests/afp_world.py."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from afp_world import ADMIN_PASSWORD, LOGS, REGION, World, make_ctx

from afp import checks, cli
from afp.errors import AfpError

NO_ARGS = argparse.Namespace()


def sent(world: World) -> list[tuple[str, str, float, dict[str, str]]]:
    return [(m["namespace"], m["name"], d["value"], m["dimensions"]) for m in world.metrics for d in m["datapoints"]]


def test_check_db_sends_1_when_the_db_answers(tmp_path: Path) -> None:
    world = World()
    summary = cli.cmd_check_db(make_ctx(tmp_path, world), NO_ARGS)
    assert summary == "the DB answered; sent check_db_ok = 1"
    assert sent(world) == [("afp", "check_db_ok", 1, {"command": "check-db"})]
    run = next(c for c in world.calls if c["args"][:2] == ["docker", "run"])
    assert run["stdin"] == "SELECT 1;\n"
    assert run["args"][run["args"].index("-h") + 1] == "10.0.1.10"
    assert run["env"] == {"MYSQL_PWD": ADMIN_PASSWORD}  # never in the arguments
    assert ADMIN_PASSWORD not in " ".join(run["args"])


def test_check_db_sends_0_and_fails_when_the_db_does_not_answer(tmp_path: Path) -> None:
    world = World()
    world.db_down = True
    with pytest.raises(AfpError, match=r"^the DB did not answer: .*Can't connect.*; sent check_db_ok = 0$"):
        cli.cmd_check_db(make_ctx(tmp_path, world), NO_ARGS)
    assert sent(world) == [("afp", "check_db_ok", 0, {"command": "check-db"})]


def test_check_db_fails_when_the_metric_cannot_be_sent(tmp_path: Path) -> None:
    world = World()
    world.metric_fails = True
    with pytest.raises(AfpError, match=r"^cannot send the metric afp/check_db_ok = 1: "):
        cli.cmd_check_db(make_ctx(tmp_path, world), NO_ARGS)


def test_check_db_takes_no_lock(tmp_path: Path) -> None:
    # A deploy holds the lock for minutes; the check must not wait for it.
    world = World()
    ctx = make_ctx(tmp_path, world)
    cli.cmd_check_db(ctx, NO_ARGS)
    assert not (ctx.paths.run_dir / "lock").exists()


def test_disk_used_percent_counts_like_df(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # total 100, used 45, free (for non-root) 45: 10 kept for root
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda path: checks.shutil._ntuple_diskusage(100, 45, 45))
    assert checks.disk_used_percent(tmp_path) == 50.0


def test_check_disk_sends_the_percent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda path: checks.shutil._ntuple_diskusage(300, 100, 200))
    world = World()
    summary = checks.check_disk(make_ctx(tmp_path, world), cli.load_config(make_ctx(tmp_path, world)), tmp_path)
    assert summary == f"{tmp_path} is 33.3% used; sent disk_used_percent = 33.3"
    assert sent(world) == [("afp", "disk_used_percent", 33.3, {"command": "check-disk"})]


def test_check_disk_looks_at_the_boot_volume() -> None:
    assert checks.DISK_PATH == Path("/")


def test_a_check_that_goes_well_keeps_no_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    world = World()
    monkeypatch.setattr(cli, "metadata_region", lambda: REGION)
    paths = make_ctx(tmp_path, world).paths
    monkeypatch.setattr(cli, "Runner", lambda log: world)
    assert cli.main(["check-db"], paths=paths) == 0
    out = capsys.readouterr().out
    assert out.endswith("log: not kept (the run went well)\n")
    assert world.in_bucket(LOGS) == []
    assert [p.name for p in paths.log_dir.iterdir()] == ["test.log"]  # only make_ctx's own


def test_a_check_that_fails_uploads_its_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    world = World()
    world.db_down = True
    monkeypatch.setattr(cli, "metadata_region", lambda: REGION)
    paths = make_ctx(tmp_path, world).paths
    monkeypatch.setattr(cli, "Runner", lambda log: world)
    assert cli.main(["check-db"], paths=paths) == 1
    assert "afp check-db: FAILED: the DB did not answer" in capsys.readouterr().out
    [name] = world.in_bucket(LOGS)
    assert name.endswith("-check-db.log")
