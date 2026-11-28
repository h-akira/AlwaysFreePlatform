"""Static checks of terraform/modules/alarm: the platform's alarms watch the
metrics that afp and OCI send, and all mail topic-afp-devops."""

import re
from pathlib import Path

from afp import checks

ROOT = Path(__file__).resolve().parent.parent
ALARM_TF = (ROOT / "terraform" / "modules" / "alarm" / "main.tf").read_text()
COMPUTE_TF = (ROOT / "terraform" / "modules" / "compute" / "main.tf").read_text()
MAIN_TF = (ROOT / "terraform" / "main" / "main.tf").read_text()


def _block(text: str, header: str) -> str:
    start = text.index(header)
    end = text.index("\n}\n", start)
    return text[start:end]


def _alarm(name: str) -> str:
    return _block(ALARM_TF, f'resource "oci_monitoring_alarm" "{name}"')


def test_every_alarm_mails_the_devops_topic() -> None:
    names = re.findall(r'resource "oci_monitoring_alarm" "(\w+)"', ALARM_TF)
    assert names == ["backup", "nlb_unhealthy", "check_db", "vm_memory", "vm_disk"]
    for name in names:
        alarm = _alarm(name)
        assert "destinations          = [var.topic_id]" in alarm
        assert "is_enabled            = true" in alarm
        assert "metric_compartment_id = var.compartment_id" in alarm


def test_the_nlb_alarm_watches_its_health_checks_for_5_minutes() -> None:
    alarm = _alarm("nlb_unhealthy")
    assert 'display_name          = "alarm-afp-nlb-unhealthy"' in alarm
    assert 'namespace             = "oci_nlb"' in alarm
    assert 'query                 = "UnhealthyBackendsPerNlb[1m]{resourceId = \\"${var.nlb_id}\\"}.max() > 0"' in alarm
    assert 'pending_duration      = "PT5M"' in alarm


def test_the_metrics_of_afp_are_read_over_an_hour() -> None:
    # A [1m] window would see an hourly or weekly data point for one minute only.
    assert 'query                 = "backup_ok[1h].min() < 1"' in _alarm("backup")
    db = _alarm("check_db")
    assert 'display_name          = "alarm-afp-check-db"' in db
    assert f'query                 = "{checks.CHECK_DB_METRIC}[1h].min() < 1"' in db
    assert f'namespace             = "{checks.NAMESPACE}"' in db
    disk = _alarm("vm_disk")
    assert 'display_name          = "alarm-afp-vm-disk"' in disk
    assert f'query                 = "{checks.DISK_METRIC}[1h].max() > 90"' in disk
    assert f'namespace             = "{checks.NAMESPACE}"' in disk


def test_the_memory_alarm_watches_the_vm() -> None:
    alarm = _alarm("vm_memory")
    assert 'display_name          = "alarm-afp-vm-memory"' in alarm
    assert 'namespace             = "oci_computeagent"' in alarm
    assert 'query                 = "MemoryUtilization[5m]{resourceId = \\"${var.instance_id}\\"}.mean() > 90"' in alarm
    assert 'pending_duration      = "PT5M"' in alarm


def test_the_vm_runs_the_monitoring_plugin() -> None:
    assert 'name          = "Compute Instance Monitoring"\n      desired_state = "ENABLED"' in COMPUTE_TF


def test_the_main_stack_passes_the_nlb_and_the_vm() -> None:
    alarm = _block(MAIN_TF, 'module "alarm"')
    assert "nlb_id           = module.nlb.nlb_id" in alarm
    assert "instance_id      = module.vm.instance_id" in alarm
