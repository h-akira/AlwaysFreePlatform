# The main stack looks these up by name; the outputs are for checking, except
# dns_nameservers, which the parent zone delegates to (NS records).

output "compartment_id" {
  value = module.iam.compartment_id
}

output "vault_id" {
  value = module.vault.vault_id
}

output "key_id" {
  value = module.vault.key_id
}

output "dns_nameservers" {
  value = module.dns.nameservers
}
