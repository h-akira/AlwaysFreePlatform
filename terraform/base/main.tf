# Stack "stack-afp-base": what cannot be destroyed and recreated repeatedly.
# A deleted vault stays PENDING_DELETION inside its compartment, and a
# recreated DNS zone may get other name servers, which are written outside OCI
# (the NS records of the parent zone). The budget of the compartment is kept
# here too, so that it watches the spend while the main stack is recreated.
# Everything else is in terraform/main.

module "iam" {
  source       = "../modules/iam"
  tenancy_ocid = var.tenancy_ocid
}

module "vault" {
  source         = "../modules/vault"
  compartment_id = module.iam.compartment_id
}

module "dns" {
  source         = "../modules/dns"
  compartment_id = module.iam.compartment_id
  zone           = var.dns_zone
}

# Only when budget_amount is set.
module "budget" {
  source         = "../modules/budget"
  count          = var.budget_amount == null ? 0 : 1
  tenancy_ocid   = var.tenancy_ocid
  compartment_id = module.iam.compartment_id
  amount         = var.budget_amount
  email          = var.notification_email
}
