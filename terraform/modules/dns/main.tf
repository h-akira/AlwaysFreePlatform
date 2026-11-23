variable "compartment_id" {
  type = string
}

variable "zone" {
  type = string
}

# Kept by the base stack: the parent zone delegates to its name servers by NS
# records outside OCI, which would have to be changed if the zone were recreated.
resource "oci_dns_zone" "afp" {
  compartment_id = var.compartment_id
  name           = var.zone
  zone_type      = "PRIMARY"
  scope          = "GLOBAL"
}

output "nameservers" {
  value = [for ns in oci_dns_zone.afp.nameservers : ns.hostname]
}
