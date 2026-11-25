# Read by scripts/ (e.g. db-tunnel.sh) from the stack's state.

output "compartment_id" {
  value = local.compartment_id
}

output "bastion_id" {
  value = module.network.bastion_id
}

output "db_ip" {
  value = module.database.ip_address
}

output "db_port" {
  value = module.database.port
}

output "db_admin_username" {
  value = var.db_admin_username
}

output "db_admin_secret_id" {
  value = module.secrets.db_admin_secret_id
}

output "vault_id" {
  value = data.oci_kms_vaults.afp.vaults[0].id
}

output "key_id" {
  value = data.oci_kms_keys.afp.keys[0].id
}

output "bucket" {
  value = module.storage.bucket_name
}

output "namespace" {
  value = data.oci_objectstorage_namespace.this.namespace
}

output "vm_id" {
  value = module.vm.instance_id
}

output "vm_private_ip" {
  value = module.vm.private_ip
}

output "public_ip" {
  value = module.nlb.public_ip
}

output "vm_arch" {
  value = module.vm.arch
}

output "devops_project_id" {
  value = module.devops.project_id
}

output "devops_connection_id" {
  value = module.devops.connection_id
}

# Read by scripts/triggers.py: {project: {build_pipeline_id}} for the projects
# with a repository. It also makes their webhook secrets (ADR 039).
output "pipelines" {
  value = { for name, id in module.devops.build_pipeline_ids : name => { build_pipeline_id = id } }

  precondition {
    condition     = var.github_token_secret_id != null || alltrue([for p in var.projects : p.repository == null])
    error_message = "Projects with a repository need github_token_secret_id: make the token's Vault secret by hand and write its OCID there."
  }
}

output "domains" {
  value = local.domains
}
