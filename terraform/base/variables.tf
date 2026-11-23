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
