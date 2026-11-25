# One VCN with a subnet per role (ADR 040):
#   public   the network load balancer only (the way in from the internet)
#   vm       the VM, private; out through the NAT and service gateways
#   db       the DB system, private
#   bastion  the Bastion's private endpoint, private; may reach only the VM's
#            ssh port and the DB's MySQL port

variable "compartment_id" {
  type = string
}

variable "vcn_cidr" {
  type = string
}

variable "public_subnet_cidr" {
  type = string
}

variable "vm_subnet_cidr" {
  type = string
}

variable "db_subnet_cidr" {
  type = string
}

variable "bastion_subnet_cidr" {
  type = string
}

variable "home_cidrs" {
  type = list(string)
}

variable "https_public" {
  type = bool
}

locals {
  https_sources = var.https_public ? ["0.0.0.0/0"] : var.home_cidrs
}

resource "oci_core_vcn" "afp" {
  compartment_id = var.compartment_id
  display_name   = "vcn-afp-main"
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "afp"
}

# --- gateways and routes ---

resource "oci_core_internet_gateway" "afp" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "igw-afp-main"
}

resource "oci_core_nat_gateway" "afp" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "nat-afp-main"
}

data "oci_core_services" "all" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_service_gateway" "afp" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "sgw-afp-main"

  services {
    service_id = data.oci_core_services.all.services[0].id
  }
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "rt-afp-public"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.afp.id
  }
}

resource "oci_core_route_table" "vm" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "rt-afp-vm"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_nat_gateway.afp.id
  }

  route_rules {
    destination       = data.oci_core_services.all.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.afp.id
  }
}

# --- public subnet: the network load balancer ---

# Port 80 is always open (HTTP-01 challenges and redirects); 443 is open to
# everyone or only to home_cidrs. The load balancer keeps the client's address,
# so this is the only place where clients are filtered.
resource "oci_core_security_list" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "seclist-afp-public"

  ingress_security_rules {
    protocol = "6" # TCP
    source   = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
  }

  dynamic "ingress_security_rules" {
    for_each = local.https_sources
    content {
      protocol = "6" # TCP
      source   = ingress_security_rules.value
      tcp_options {
        min = 443
        max = 443
      }
    }
  }

  # Path MTU discovery.
  ingress_security_rules {
    protocol = "1" # ICMP
    source   = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }

  dynamic "egress_security_rules" {
    for_each = [80, 443]
    content {
      protocol    = "6" # TCP
      destination = var.vm_subnet_cidr
      tcp_options {
        min = egress_security_rules.value
        max = egress_security_rules.value
      }
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = var.compartment_id
  vcn_id            = oci_core_vcn.afp.id
  display_name      = "subnet-afp-public"
  cidr_block        = var.public_subnet_cidr
  dns_label         = "public"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
}

# --- VM subnet ---

# 80 and 443 come through the load balancer with the clients' own addresses,
# so they are allowed from anywhere; the VM has no public IP, so nothing else
# reaches them. ssh only from the Bastion subnet.
resource "oci_core_security_list" "vm" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "seclist-afp-vm"

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  dynamic "ingress_security_rules" {
    for_each = [80, 443]
    content {
      protocol = "6" # TCP
      source   = "0.0.0.0/0"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  ingress_security_rules {
    protocol = "6" # TCP
    source   = var.bastion_subnet_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  # Path MTU discovery.
  ingress_security_rules {
    protocol = "1" # ICMP
    source   = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "vm" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.afp.id
  display_name               = "subnet-afp-vm"
  cidr_block                 = var.vm_subnet_cidr
  dns_label                  = "vm"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.vm.id
  security_list_ids          = [oci_core_security_list.vm.id]
}

# --- DB subnet ---

# MySQL from the VM and from the Bastion's endpoint.
resource "oci_core_security_list" "db" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "seclist-afp-db"

  dynamic "ingress_security_rules" {
    for_each = [var.vm_subnet_cidr, var.bastion_subnet_cidr]
    content {
      protocol = "6" # TCP
      source   = ingress_security_rules.value
      tcp_options {
        min = 3306
        max = 3306
      }
    }
  }
}

resource "oci_core_subnet" "db" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.afp.id
  display_name               = "subnet-afp-db"
  cidr_block                 = var.db_subnet_cidr
  dns_label                  = "db"
  prohibit_public_ip_on_vnic = true
  security_list_ids          = [oci_core_security_list.db.id]
}

# --- Bastion subnet ---

# The Bastion's endpoint is bound by this list (references/oci-bastion.md §3),
# so it needs the egress rules to the VM's ssh port and the DB's MySQL port.
resource "oci_core_security_list" "bastion" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.afp.id
  display_name   = "seclist-afp-bastion"

  egress_security_rules {
    protocol    = "6" # TCP
    destination = var.vm_subnet_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  egress_security_rules {
    protocol    = "6" # TCP
    destination = var.db_subnet_cidr
    tcp_options {
      min = 3306
      max = 3306
    }
  }
}

resource "oci_core_subnet" "bastion" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.afp.id
  display_name               = "subnet-afp-bastion"
  cidr_block                 = var.bastion_subnet_cidr
  dns_label                  = "bastion"
  prohibit_public_ip_on_vnic = true
  security_list_ids          = [oci_core_security_list.bastion.id]
}

resource "oci_bastion_bastion" "afp" {
  compartment_id               = var.compartment_id
  name                         = "bastionafpmain" # only letters and digits are allowed
  bastion_type                 = "STANDARD"
  target_subnet_id             = oci_core_subnet.bastion.id
  client_cidr_block_allow_list = var.home_cidrs
  max_session_ttl_in_seconds   = 10800
}

output "public_subnet_id" {
  value = oci_core_subnet.public.id
}

output "vm_subnet_id" {
  value = oci_core_subnet.vm.id
}

output "db_subnet_id" {
  value = oci_core_subnet.db.id
}

output "bastion_id" {
  value = oci_bastion_bastion.afp.id
}
