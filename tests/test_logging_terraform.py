"""Static checks of terraform/modules/logging: one log for every project,
kept 30 days, fed by the agent from Docker's json-file logs."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGGING_TF = (ROOT / "terraform" / "modules" / "logging" / "main.tf").read_text()


def _block(text: str, header: str) -> str:
    """The block that starts with header, up to its closing brace at column 0."""
    start = text.index(header)
    end = text.index("\n}\n", start)
    return text[start:end]


def test_one_custom_log_kept_30_days_in_its_group() -> None:
    group = _block(LOGGING_TF, 'resource "oci_logging_log_group" "apps"')
    assert 'display_name   = "loggroup-afp-apps"' in group
    assert "compartment_id = var.compartment_id" in group
    log = _block(LOGGING_TF, 'resource "oci_logging_log" "apps"')
    assert 'display_name       = "log-afp-apps"' in log
    assert "log_group_id       = oci_logging_log_group.apps.id" in log
    assert 'log_type           = "CUSTOM"' in log
    assert re.search(r"retention_duration = 30\b", log)


def test_the_agent_tails_the_docker_logs_as_json_into_the_log() -> None:
    agent = _block(LOGGING_TF, 'resource "oci_logging_unified_agent_configuration" "apps"')
    assert 'display_name   = "agentconfig-afp-apps"' in agent
    assert "is_enabled     = true" in agent
    assert 'configuration_type = "LOGGING"' in agent
    assert 'source_type = "LOG_TAIL"' in agent
    assert 'paths       = ["/var/lib/docker/containers/*/*-json.log"]' in agent
    assert 'parser_type = "JSON"' in agent
    assert "log_object_id = oci_logging_log.apps.id" in agent


def test_the_agent_runs_on_the_vms_dynamic_group() -> None:
    agent = _block(LOGGING_TF, 'resource "oci_logging_unified_agent_configuration" "apps"')
    assert "group_list = [var.dynamic_group_id]" in agent
    assert 'variable "dynamic_group_id"' in LOGGING_TF


def test_the_ids_are_outputs() -> None:
    for name, value in [("log_group_id", "oci_logging_log_group.apps.id"), ("log_id", "oci_logging_log.apps.id")]:
        assert f"value = {value}" in _block(LOGGING_TF, f'output "{name}"')
