# The alarm on the weekly backup: afp backup of every project sends the custom
# metric afp/backup_ok (1: every dump made, 0: not; afp/project.py). A backup
# that does not run at all sends nothing and is not noticed here.

variable "compartment_id" {
  description = "Compartment of the alarm and of the metric (afp.json's compartment_id)"
  type        = string
}

variable "topic_id" {
  description = "Notification topic the alarm mails to (topic-afp-devops)"
  type        = string
}

variable "logs_bucket_name" {
  description = "Bucket of the afp run logs, named in the mail"
  type        = string
}

resource "oci_monitoring_alarm" "backup" {
  compartment_id        = var.compartment_id
  metric_compartment_id = var.compartment_id
  display_name          = "alarm-afp-backup"
  is_enabled            = true
  namespace             = "afp"
  query                 = "backup_ok[1m].min() < 1"
  severity              = "ERROR"
  destinations          = [var.topic_id]
  body                  = <<-EOT
    The weekly DB backup (afp backup, Sunday 18:00 UTC) failed: the dump of at
    least one project, or the whole run, did not succeed (backup_ok = 0).
    Which project and why: the log of that run in bucket ${var.logs_bucket_name},
    <time>-backup.log. The dumps that were made are in the dumps bucket.
    To retry: make backup (or make backup PROJECT=<name>).
  EOT
}

output "alarm_id" {
  value = oci_monitoring_alarm.backup.id
}
