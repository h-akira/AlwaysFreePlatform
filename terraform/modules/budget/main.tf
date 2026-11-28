variable "tenancy_ocid" {
  description = "Tenancy root, where every budget is created whatever it targets"
  type        = string
}

variable "compartment_id" {
  description = "Compartment whose spend the budget tracks (compartment-afp-main)"
  type        = string
}

variable "amount" {
  description = "Monthly budget, a whole number in the currency of the tenancy"
  type        = number
}

variable "email" {
  description = "Address the alert rule mails"
  type        = string
}

# The spend of the platform's compartment (and its children) per month. Kept by the base stack with the compartment, so that it goes on
# watching while the main stack is destroyed and recreated.
resource "oci_budget_budget" "afp" {
  compartment_id = var.tenancy_ocid
  display_name   = "budget-afp-main"
  description    = "AlwaysFreePlatform"
  amount         = var.amount
  reset_period   = "MONTHLY"
  target_type    = "COMPARTMENT"
  targets        = [var.compartment_id]
}

# Mails when the actual spend of the month reaches the whole budget.
resource "oci_budget_alert_rule" "actual" {
  budget_id      = oci_budget_budget.afp.id
  display_name   = "alertrule-afp-main"
  type           = "ACTUAL"
  threshold_type = "PERCENTAGE"
  threshold      = 100
  recipients     = var.email
  message        = "The spend of compartment-afp-main this month has reached its budget (budget-afp-main). Look at Cost Analysis in the OCI Console."
}
