# Stack "stack-afp-base": what cannot be destroyed and recreated repeatedly.
# A deleted vault stays PENDING_DELETION inside its compartment, and a
# recreated DNS zone may get other name servers, which are written outside OCI
# (the NS records of the parent zone). Everything else is in terraform/main.

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
