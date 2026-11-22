# OCI DevOps: what the platform shares (project, GitHub connection, logs,
# notifications, the VM as a deployment target, permissions) and, for each
# project with a repository, a build pipeline and a deployment pipeline.
#
# The GitHub triggers are not made here: the API returns a trigger's webhook
# secret only in the response to its creation, and the provider drops it.
# scripts/triggers.py creates and deletes them during make apply / destroy.

variable "tenancy_ocid" {
  type = string
}

variable "compartment_id" {
  type = string
}

# Name of the compartment, as written in policy statements.
variable "compartment_name" {
  type = string
}

variable "bucket_name" {
  type = string
}

# Vault secret holding the GitHub token (the administrator sets its value).
variable "github_token_secret_id" {
  type = string
}

variable "notification_email" {
  type = string
}

variable "vm_instance_id" {
  type = string
}

# Projects with a repository: [{name, repository}].
variable "projects" {
  type = list(object({
    name       = string
    repository = string
  }))
}

locals {
  c        = var.compartment_name
  projects = { for p in var.projects : p.name => p }
}

resource "oci_ons_notification_topic" "devops" {
  compartment_id = var.compartment_id
  name           = "afp-devops"
  description    = "AlwaysFreePlatform: build and deployment notifications"
}

# The address has to confirm the subscription from the mail OCI sends.
resource "oci_ons_subscription" "email" {
  compartment_id = var.compartment_id
  topic_id       = oci_ons_notification_topic.devops.id
  protocol       = "EMAIL"
  endpoint       = var.notification_email
}

resource "oci_devops_project" "afp" {
  compartment_id = var.compartment_id
  name           = "afp"
  description    = "AlwaysFreePlatform"

  notification_config {
    topic_id = oci_ons_notification_topic.devops.id
  }
}

# Build and deployment logs; without them a run shows no output.
resource "oci_logging_log_group" "devops" {
  compartment_id = var.compartment_id
  display_name   = "afp-devops"
}

resource "oci_logging_log" "devops" {
  display_name       = "afp-devops"
  log_group_id       = oci_logging_log_group.devops.id
  log_type           = "SERVICE"
  is_enabled         = true
  retention_duration = 30

  configuration {
    compartment_id = var.compartment_id
    source {
      category    = "all"
      resource    = oci_devops_project.afp.id
      service     = "devops"
      source_type = "OCISERVICE"
    }
  }
}

resource "oci_devops_connection" "github" {
  project_id      = oci_devops_project.afp.id
  connection_type = "GITHUB_ACCESS_TOKEN"
  access_token    = var.github_token_secret_id
  display_name    = "github"
  description     = "GitHub, with the platform's token (ADR 023)"
}

# The platform's VM; recreating the VM updates the environment.
resource "oci_devops_deploy_environment" "vm" {
  project_id              = oci_devops_project.afp.id
  deploy_environment_type = "COMPUTE_INSTANCE_GROUP"
  display_name            = "vm-main"

  compute_instance_group_selectors {
    items {
      selector_type        = "INSTANCE_IDS"
      compute_instance_ids = [var.vm_instance_id]
    }
  }
}

# DevOps resources (build and deployment pipelines, the connection) act
# through resource principals; every one in the compartment is a member.
resource "oci_identity_dynamic_group" "devops" {
  compartment_id = var.tenancy_ocid
  name           = "afp-devops"
  description    = "AlwaysFreePlatform DevOps resources"
  matching_rule  = "ALL {resource.compartment.id = '${var.compartment_id}'}"
}

resource "oci_identity_policy" "devops" {
  compartment_id = var.compartment_id
  name           = "afp-devops"
  description    = "What the AlwaysFreePlatform DevOps resources may do"
  statements = [
    # The connection and the build read the GitHub token, and no other secret.
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to read secret-family in compartment ${local.c} where target.secret.id = '${var.github_token_secret_id}'",
    # Build: push images (creating repositories), read afp.json and
    # platform.json, put the release bundle, start the deployment, notify.
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to manage repos in compartment ${local.c}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to read buckets in compartment ${local.c} where target.bucket.name = '${var.bucket_name}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to manage objects in compartment ${local.c} where target.bucket.name = '${var.bucket_name}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to manage devops-family in compartment ${local.c}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to use ons-topics in compartment ${local.c}",
    # Deployment to the instance group: run commands on the VM.
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to read all-artifacts in compartment ${local.c}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to read instance-family in compartment ${local.c}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops.name} to use instance-agent-command-family in compartment ${local.c}",
  ]
}

# ---- per project ----

resource "oci_devops_deploy_pipeline" "project" {
  for_each     = local.projects
  project_id   = oci_devops_project.afp.id
  display_name = "afp-${each.key}-deploy"
  description  = "Run afp deploy for ${each.key} on the VM, with the tag as AFP_TAG"

  deploy_pipeline_parameters {
    items {
      name        = "AFP_TAG"
      description = "Version to deploy (the git tag); set by the build"
    }
  }
}

# afp deploy builds the images on the VM from the source that the build put
# into the bucket (ADR 026), so the step allows for a build.
# The tag reaches a shell on the VM. The build checks its form before
# exporting it (scripts/devops-build.sh) and afp checks it again; the quotes
# keep anything else from being parsed by the shell.
resource "oci_devops_deploy_artifact" "spec" {
  for_each                   = local.projects
  project_id                 = oci_devops_project.afp.id
  display_name               = "afp-${each.key}-deployment-spec"
  deploy_artifact_type       = "DEPLOYMENT_SPEC"
  argument_substitution_mode = "SUBSTITUTE_PLACEHOLDERS"

  deploy_artifact_source {
    deploy_artifact_source_type = "INLINE"
    base64encoded_content       = <<-EOT
      version: 1.0
      component: deployment
      steps:
        - stepType: Command
          name: afp deploy
          timeoutInSeconds: 1800
          command: sudo -n /opt/afp/current/bin/afp deploy ${each.key} '$${AFP_TAG}'
    EOT
  }
}

# afp deploy rolls back by itself; DevOps only reports the result.
resource "oci_devops_deploy_stage" "project" {
  for_each                                     = local.projects
  deploy_pipeline_id                           = oci_devops_deploy_pipeline.project[each.key].id
  deploy_stage_type                            = "COMPUTE_INSTANCE_GROUP_ROLLING_DEPLOYMENT"
  display_name                                 = "afp-deploy"
  compute_instance_group_deploy_environment_id = oci_devops_deploy_environment.vm.id
  deployment_spec_deploy_artifact_id           = oci_devops_deploy_artifact.spec[each.key].id

  deploy_stage_predecessor_collection {
    items {
      id = oci_devops_deploy_pipeline.project[each.key].id
    }
  }

  # One VM, so one batch; the delay between batches (1 to 3599 s) never applies.
  rollout_policy {
    policy_type = "COMPUTE_INSTANCE_GROUP_LINEAR_ROLLOUT_POLICY_BY_COUNT"
    batch_count = 1
  }

  rollback_policy {
    policy_type = "NO_STAGE_ROLLBACK_POLICY"
  }
}

resource "oci_devops_build_pipeline" "project" {
  for_each     = local.projects
  project_id   = oci_devops_project.afp.id
  display_name = "afp-${each.key}-build"
  description  = "Build ${each.key} from ${each.value.repository}"

  build_pipeline_parameters {
    items {
      name          = "AFP_PROJECT"
      default_value = each.key
      description   = "Project name on the platform"
    }
    items {
      name          = "AFP_BUCKET"
      default_value = var.bucket_name
      description   = "Bucket holding afp.json, platform.json and the release bundles"
    }
  }
}

# Runs the project's build_spec.yaml (from the template in examples/hello). The
# runner is x86_64 and cannot emulate arm64, so it only puts the tag's source
# and compose.afp.yaml into the bucket; the VM builds (ADR 026).
resource "oci_devops_build_pipeline_stage" "build" {
  for_each                  = local.projects
  build_pipeline_id         = oci_devops_build_pipeline.project[each.key].id
  build_pipeline_stage_type = "BUILD"
  display_name              = "build"
  # An update sends the description; DevOps rejects an empty one.
  description          = "Release the tag on the head of release for the VM to build"
  image                = "OL8_X86_64_STANDARD_10"
  build_spec_file      = "build_spec.yaml"
  primary_build_source = "project"

  stage_execution_timeout_in_seconds = 1800

  build_pipeline_stage_predecessor_collection {
    items {
      id = oci_devops_build_pipeline.project[each.key].id
    }
  }

  build_runner_shape_config {
    build_runner_type = "DEFAULT"
  }

  build_source_collection {
    items {
      name            = "project"
      connection_type = "GITHUB"
      connection_id   = oci_devops_connection.github.id
      repository_url  = each.value.repository
      # The trigger builds the pushed branch; a run started by hand builds
      # this one. Both are release (ADR 029).
      branch = "release"
    }
  }
}

resource "oci_devops_build_pipeline_stage" "deploy" {
  for_each                       = local.projects
  build_pipeline_id              = oci_devops_build_pipeline.project[each.key].id
  build_pipeline_stage_type      = "TRIGGER_DEPLOYMENT_PIPELINE"
  display_name                   = "deploy"
  deploy_pipeline_id             = oci_devops_deploy_pipeline.project[each.key].id
  is_pass_all_parameters_enabled = true

  build_pipeline_stage_predecessor_collection {
    items {
      id = oci_devops_build_pipeline_stage.build[each.key].id
    }
  }
}

output "project_id" {
  value = oci_devops_project.afp.id
}

output "connection_id" {
  value = oci_devops_connection.github.id
}

output "build_pipeline_ids" {
  value = { for name, _ in local.projects : name => oci_devops_build_pipeline.project[name].id }
}
