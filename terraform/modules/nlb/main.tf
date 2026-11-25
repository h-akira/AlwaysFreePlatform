# The way in from the internet: a public network load balancer (layer 4) that
# passes TCP 80 and 443 through to the VM, where Caddy terminates TLS and gets
# the certificates (ADR 040). The client's address is kept (is_preserve_source).
# Its public IP is not reserved: it lives as long as the load balancer, and the
# DNS records follow it.

variable "compartment_id" {
  type = string
}

# The VM's name in the project list ("main").
variable "name" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "instance_id" {
  type = string
}

# Each resource waits for the previous one, so that the load balancer gets one
# change at a time. Whether parallel changes are refused is not documented;
# the chain only costs a little time.
resource "oci_network_load_balancer_network_load_balancer" "nlb" {
  compartment_id = var.compartment_id
  display_name   = "nlb-afp-${var.name}"
  subnet_id      = var.subnet_id
  is_private     = false
}

resource "oci_network_load_balancer_backend_set" "http" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  name                     = "backendset-afp-${var.name}-http"
  policy                   = "FIVE_TUPLE"
  is_preserve_source       = true

  health_checker {
    protocol = "TCP"
    port     = 80
  }
}

resource "oci_network_load_balancer_backend_set" "https" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  name                     = "backendset-afp-${var.name}-https"
  policy                   = "FIVE_TUPLE"
  is_preserve_source       = true

  health_checker {
    protocol = "TCP"
    port     = 443
  }

  depends_on = [oci_network_load_balancer_backend_set.http]
}

resource "oci_network_load_balancer_backend" "http" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  backend_set_name         = oci_network_load_balancer_backend_set.http.name
  target_id                = var.instance_id
  port                     = 80

  depends_on = [oci_network_load_balancer_backend_set.https]
}

resource "oci_network_load_balancer_backend" "https" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  backend_set_name         = oci_network_load_balancer_backend_set.https.name
  target_id                = var.instance_id
  port                     = 443

  depends_on = [oci_network_load_balancer_backend.http]
}

resource "oci_network_load_balancer_listener" "http" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  name                     = "listener-afp-${var.name}-http"
  default_backend_set_name = oci_network_load_balancer_backend_set.http.name
  protocol                 = "TCP"
  port                     = 80

  depends_on = [oci_network_load_balancer_backend.https]
}

resource "oci_network_load_balancer_listener" "https" {
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.nlb.id
  name                     = "listener-afp-${var.name}-https"
  default_backend_set_name = oci_network_load_balancer_backend_set.https.name
  protocol                 = "TCP"
  port                     = 443

  depends_on = [oci_network_load_balancer_listener.http]
}

output "public_ip" {
  value = one([for ip in oci_network_load_balancer_network_load_balancer.nlb.ip_addresses : ip.ip_address if ip.is_public])
}
