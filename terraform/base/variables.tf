variable "tenancy_ocid" {
  description = "OCID of the tenancy."
  type        = string
}

variable "region" {
  description = "Region to create resources in. Must be the home region (Always Free)."
  type        = string
}

variable "dns_zone" {
  description = "Public DNS zone of the platform, e.g. afp.example.com. Each project is served at <name>.<dns_zone>. After the first apply, delegate the zone from its parent with NS records for the name servers in the output dns_nameservers."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.dns_zone))
    error_message = "dns_zone must be a lower-case domain name such as afp.example.com."
  }
}

variable "notification_email" {
  description = "Email address that receives the budget alert (the same value as in the main stack)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be an email address."
  }
}

variable "budget_amount" {
  description = "Monthly budget of the platform's compartment (compartment-afp-main and its children), a whole number in the currency of the tenancy. When set, the base stack creates the budget budget-afp-main and an alert rule that mails notification_email when the actual spend of the month reaches the amount. Null (unset): no budget."
  type        = number
  default     = null

  validation {
    condition     = var.budget_amount == null ? true : (var.budget_amount >= 1 && var.budget_amount <= 999999999999 && floor(var.budget_amount) == var.budget_amount)
    error_message = "budget_amount must be a whole number from 1 to 999999999999."
  }
}
