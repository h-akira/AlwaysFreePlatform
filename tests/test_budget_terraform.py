"""Static checks of terraform/modules/budget: when budget_amount is set, the
base stack watches the monthly spend of the platform's compartment and mails
notification_email when the actual spend reaches the budget."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET_TF = (ROOT / "terraform" / "modules" / "budget" / "main.tf").read_text()
BASE_MAIN_TF = (ROOT / "terraform" / "base" / "main.tf").read_text()
BASE_VARIABLES_TF = (ROOT / "terraform" / "base" / "variables.tf").read_text()
MAIN_MAIN_TF = (ROOT / "terraform" / "main" / "main.tf").read_text()
STACK_SH = (ROOT / "scripts" / "stack.sh").read_text()


def _block(text: str, header: str) -> str:
    """The block that starts with header, up to its closing brace at column 0."""
    start = text.index(header)
    end = text.index("\n}\n", start)
    return text[start:end]


def test_the_base_stack_makes_the_budget_only_when_the_amount_is_set() -> None:
    module = _block(BASE_MAIN_TF, 'module "budget"')
    assert 'source         = "../modules/budget"' in module
    assert "count          = var.budget_amount == null ? 0 : 1" in module
    assert "amount         = var.budget_amount" in module
    # Nothing else of the module is created outside that count.
    assert BASE_MAIN_TF.count("modules/budget") == 1
    assert "budget" not in MAIN_MAIN_TF


def test_the_amount_is_optional_and_a_whole_number() -> None:
    variable = _block(BASE_VARIABLES_TF, 'variable "budget_amount"')
    assert "type        = number" in variable
    assert "default     = null" in variable
    assert "var.budget_amount == null ? true :" in variable
    assert "floor(var.budget_amount) == var.budget_amount" in variable
    assert "var.budget_amount >= 1" in variable


def test_the_budget_is_in_the_root_and_targets_the_platform_compartment() -> None:
    module = _block(BASE_MAIN_TF, 'module "budget"')
    assert "tenancy_ocid   = var.tenancy_ocid" in module
    assert "compartment_id = module.iam.compartment_id" in module
    budget = _block(BUDGET_TF, 'resource "oci_budget_budget" "afp"')
    # Every budget is created in the root compartment, whatever it targets.
    assert "compartment_id = var.tenancy_ocid" in budget
    assert 'display_name   = "budget-afp-main"' in budget
    assert "amount         = var.amount" in budget
    assert 'reset_period   = "MONTHLY"' in budget
    assert 'target_type    = "COMPARTMENT"' in budget
    assert "targets        = [var.compartment_id]" in budget
    # target_compartment_id is deprecated in favour of targets.
    assert "target_compartment_id" not in BUDGET_TF


def test_one_alert_rule_mails_notification_email_at_the_whole_actual_budget() -> None:
    assert re.findall(r'resource "oci_budget_alert_rule" "(\w+)"', BUDGET_TF) == ["actual"]
    rule = _block(BUDGET_TF, 'resource "oci_budget_alert_rule" "actual"')
    assert "budget_id      = oci_budget_budget.afp.id" in rule
    assert 'display_name   = "alertrule-afp-main"' in rule
    assert 'type           = "ACTUAL"' in rule
    assert 'threshold_type = "PERCENTAGE"' in rule
    assert re.search(r"threshold      = 100\b", rule)
    assert "recipients     = var.email" in rule
    module = _block(BASE_MAIN_TF, 'module "budget"')
    assert "email          = var.notification_email" in module


def test_the_base_stack_gets_the_email_and_maybe_the_amount() -> None:
    assert 'variable "notification_email"' in BASE_VARIABLES_TF
    keys = re.search(r'^\s*VARIABLE_KEYS="(tenancy_ocid[^"]*)"', STACK_SH, re.M)
    assert keys is not None
    assert keys.group(1).split(",") == ["tenancy_ocid", "region", "dns_zone", "notification_email", "budget_amount?"]
