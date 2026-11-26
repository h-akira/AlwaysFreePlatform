"""Tests for afp backup: every project is tried, and the result of a backup of
every project goes to the metric afp/backup_ok (on the fake VM of tests/afp_world.py)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from afp_world import DUMPS, REGION, World, afp_json, make_ctx

from afp import cli
from afp.errors import AfpError

EVERY = argparse.Namespace(project=None)


def backup(world: World, tmp_path: Path, args: argparse.Namespace = EVERY) -> str:
    return cli.cmd_backup(make_ctx(tmp_path, world), args)


def metric_values(world: World) -> list[float]:
    return [d["value"] for m in world.metrics for d in m["datapoints"]]


def test_all_dumped_sends_1(tmp_path: Path) -> None:
    world = World()
    summary = backup(world, tmp_path)
    assert summary.startswith(f"dumped to {DUMPS}: hello/")
    assert metric_values(world) == [1]
    m = world.metrics[0]
    assert (m["namespace"], m["name"], m["compartmentId"]) == ("afp", "backup_ok", "ocid1.compartment.oc1..afp")
    assert m["dimensions"]  # the API needs at least one
    post = next(c["args"] for c in world.calls if "metric-data" in c["args"])
    assert post[:5] == ["oci", "--auth", "instance_principal", "--region", REGION]
    assert post[post.index("--endpoint") + 1] == f"https://telemetry-ingestion.{REGION}.oraclecloud.com"
    assert post[post.index("--batch-atomicity") + 1] == "ATOMIC"
    json.loads(post[post.index("--metric-data") + 1])


def test_a_failed_project_does_not_stop_the_others(tmp_path: Path) -> None:
    world = World()
    world.broken_dump.add("hello")
    ctx = make_ctx(tmp_path, world)
    with pytest.raises(AfpError, match=r"^dump failed: hello; dumped to bucket-afp-dumps: app-a/") as e:
        cli.cmd_backup(ctx, EVERY)
    assert "hello" not in str(e.value).split("dumped to")[1]
    assert [n.split("/")[0] for n in world.in_bucket(DUMPS)] == ["app-a"]
    assert metric_values(world) == [0]
    ctx.log.close()
    assert "error: dump of hello failed" in ctx.log.path.read_text()


def test_every_project_failing(tmp_path: Path) -> None:
    world = World()
    world.broken_dump |= {"hello", "app_a"}
    with pytest.raises(AfpError, match=r"^dump failed: hello, app-a; dumped to bucket-afp-dumps: none$"):
        backup(world, tmp_path)
    assert metric_values(world) == [0]


def test_one_project_sends_no_metric(tmp_path: Path) -> None:
    world = World()
    backup(world, tmp_path, argparse.Namespace(project="hello"))
    world.broken_dump.add("hello")
    with pytest.raises(AfpError, match="dump failed: hello"):
        backup(world, tmp_path, argparse.Namespace(project="hello"))
    assert world.metrics == []


def test_no_projects_sends_1(tmp_path: Path) -> None:
    world = World(afp_json(projects=[]))
    assert backup(world, tmp_path) == f"dumped to {DUMPS}: no projects"
    assert metric_values(world) == [1]


def test_a_metric_that_cannot_be_sent_fails_the_run(tmp_path: Path) -> None:
    world = World()
    world.metric_fails = True
    ctx = make_ctx(tmp_path, world)
    with pytest.raises(AfpError, match=r"^metric backup_ok not sent; dumped to bucket-afp-dumps: hello/"):
        cli.cmd_backup(ctx, EVERY)
    assert len(world.in_bucket(DUMPS)) == 2  # the dumps are made all the same
    ctx.log.close()
    assert "error: cannot send the metric afp/backup_ok = 1" in ctx.log.path.read_text()


def test_both_problems_are_reported(tmp_path: Path) -> None:
    world = World()
    world.broken_dump.add("app_a")
    world.metric_fails = True
    with pytest.raises(AfpError, match=r"^dump failed: app-a; metric backup_ok not sent; "):
        backup(world, tmp_path)


def test_no_compartment_in_afp_json(tmp_path: Path) -> None:
    data = afp_json()
    del data["compartment_id"]
    world = World(data)
    with pytest.raises(AfpError, match="metric backup_ok not sent"):
        backup(world, tmp_path)
    assert world.metrics == []


def test_a_lock_that_times_out_sends_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Busy:
        def __init__(self, *args: object) -> None:
            pass

        def __enter__(self) -> None:
            raise AfpError("another afp run holds the lock")

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(cli, "Lock", Busy)
    world = World()
    with pytest.raises(AfpError, match="holds the lock"):
        backup(world, tmp_path)
    assert metric_values(world) == [0]
    assert world.in_bucket(DUMPS) == []
