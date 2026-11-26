# The projects' container logs, sent to OCI Logging by the VM's agent
# (Oracle Cloud Agent's Custom Logs Monitoring plugin). Every project goes to
# one log; each line carries the compose project and service as labels
# (written into Docker's daemon.json by afp install).

variable "compartment_id" {
  type = string
}

# The VMs' dynamic group: its instances run this agent configuration.
variable "dynamic_group_id" {
  type = string
}

resource "oci_logging_log_group" "apps" {
  compartment_id = var.compartment_id
  display_name   = "loggroup-afp-apps"
  description    = "Container logs of the AlwaysFreePlatform projects"
}

resource "oci_logging_log" "apps" {
  log_group_id       = oci_logging_log_group.apps.id
  display_name       = "log-afp-apps"
  log_type           = "CUSTOM"
  is_enabled         = true
  retention_duration = 30 # days
}

resource "oci_logging_unified_agent_configuration" "apps" {
  compartment_id = var.compartment_id
  display_name   = "agentconfig-afp-apps"
  description    = "Send the Docker json-file logs of the AlwaysFreePlatform VMs to log-afp-apps"
  is_enabled     = true

  service_configuration {
    configuration_type = "LOGGING"

    sources {
      name        = "docker"
      source_type = "LOG_TAIL"
      paths       = ["/var/lib/docker/containers/*/*-json.log"]

      # Each line is {"log": ..., "stream": ..., "attrs": {...}, "time": ...}.
      # The time of the event is when the agent reads it: Docker writes
      # "time" in RFC 3339 with a varying number of fraction digits, which
      # one fixed time_format does not always match.
      parser {
        parser_type = "JSON"
      }
    }

    destination {
      log_object_id = oci_logging_log.apps.id
    }
  }

  group_association {
    group_list = [var.dynamic_group_id]
  }
}

output "log_group_id" {
  value = oci_logging_log_group.apps.id
}

output "log_id" {
  value = oci_logging_log.apps.id
}

output "agent_configuration_id" {
  value = oci_logging_unified_agent_configuration.apps.id
}
