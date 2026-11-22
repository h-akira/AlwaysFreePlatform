variable "compartment_id" {
  type = string
}

variable "vault_id" {
  type = string
}

variable "key_id" {
  type = string
}

# var.projects of the main stack; pipeline is true when it has a repository.
variable "projects" {
  type = list(object({
    name     = string
    pipeline = bool
    secrets = list(object({
      name = string
      how  = string
    }))
  }))
}

# A deleted secret stays PENDING_DELETION in the vault, which outlives this
# stack. A suffix per stack lifetime keeps recreated names from colliding.
resource "random_id" "suffix" {
  byte_length = 4
}

# The DB system needs the password at creation, so Terraform generates it.
# It ends up in the Resource Manager state either way.
resource "random_password" "db_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  # HeatWave requires a symbol. The provider's default symbols all count as
  # one for OCI; "~" alone does not (ADR 030).
  min_special = 1
}

resource "oci_vault_secret" "db_admin_password" {
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-db-admin-password-${random_id.suffix.hex}"
  description    = "Administrator password of the MySQL HeatWave DB system"

  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.db_admin.result)
  }
}

# GitHub token that OCI DevOps reads the project repositories with; one for
# the platform. Like the manual secrets: the administrator puts the token in as
# a new secret version, which Terraform leaves alone.
resource "oci_vault_secret" "github_token" {
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-github-token-${random_id.suffix.hex}"
  description    = "GitHub token for OCI DevOps (set the value by hand)"

  secret_content {
    content_type = "BASE64"
    content      = base64encode("CHANGE_ME")
  }

  lifecycle {
    ignore_changes = [secret_content]
  }
}

locals {
  projects = { for p in var.projects : p.name => p }
  # "<project>/<NAME>" => {project, name}
  generated = merge([for p in var.projects : {
    for s in p.secrets : "${p.name}/${s.name}" => { project = p.name, name = s.name } if s.how == "generate"
  }]...)
  manual = merge([for p in var.projects : {
    for s in p.secrets : "${p.name}/${s.name}" => { project = p.name, name = s.name } if s.how == "manual"
  }]...)
  pipelines = { for p in var.projects : p.name => p if p.pipeline }
}

# Same rules as the administrator's password (ADR 030).
resource "random_password" "project_db" {
  for_each    = local.projects
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
}

resource "random_password" "generated" {
  for_each    = local.generated
  length      = 32
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
}

# One suffix per secret, so that a project (or a manual secret) removed and
# added again does not collide with its own name that is still pending deletion.
resource "random_id" "project" {
  for_each    = local.projects
  byte_length = 4
}

resource "random_id" "manual" {
  for_each    = local.manual
  byte_length = 4
}

# One JSON secret per project: AFP_DB_PASSWORD and the generated secrets.
resource "oci_vault_secret" "project" {
  for_each       = local.projects
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-${each.key}-${random_id.project[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.key}: DB password and generated secrets"

  secret_content {
    content_type = "BASE64"
    content = base64encode(jsonencode(merge(
      { AFP_DB_PASSWORD = random_password.project_db[each.key].result },
      { for k, v in local.generated : v.name => random_password.generated[k].result if v.project == each.key },
    )))
  }
}

# Manual secrets start with a placeholder; the project puts the real value in
# as a new secret version, which Terraform leaves alone.
resource "oci_vault_secret" "manual" {
  for_each       = local.manual
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-${each.value.project}-${each.value.name}-${random_id.manual[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.value.project}: ${each.value.name} (set the value by hand)"

  secret_content {
    content_type = "BASE64"
    content      = base64encode("CHANGE_ME")
  }

  lifecycle {
    ignore_changes = [secret_content]
  }
}

resource "random_id" "webhook" {
  for_each    = local.pipelines
  byte_length = 4
}

# Webhook secret of the project's GitHub trigger. The API returns it only when
# the trigger is created; scripts/triggers.py then puts it in as a new secret
# version, which Terraform leaves alone. The administrator copies it from here
# into the GitHub webhook.
resource "oci_vault_secret" "webhook" {
  for_each       = local.pipelines
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "afp-${each.key}-webhook-${random_id.webhook[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.key}: webhook secret of its GitHub trigger (set by make apply)"

  secret_content {
    content_type = "BASE64"
    content      = base64encode("CHANGE_ME")
  }

  lifecycle {
    ignore_changes = [secret_content]
  }
}

output "webhook_secrets" {
  value = { for name, _ in local.pipelines : name => {
    id   = oci_vault_secret.webhook[name].id
    name = oci_vault_secret.webhook[name].secret_name
  } }
}

# Per project: the JSON secret and the manual secrets by name.
output "project_secrets" {
  value = { for name, p in local.projects : name => {
    secret_id         = oci_vault_secret.project[name].id
    manual_secret_ids = { for k, v in local.manual : v.name => oci_vault_secret.manual[k].id if v.project == name }
  } }
}

output "db_admin_password" {
  value     = random_password.db_admin.result
  sensitive = true
}

output "db_admin_secret_id" {
  value = oci_vault_secret.db_admin_password.id
}

output "github_token_secret_id" {
  value = oci_vault_secret.github_token.id
}
