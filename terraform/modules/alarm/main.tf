# The alarms of the platform. All mail topic-afp-devops.
#
# - alarm-afp-backup: the weekly backup. afp backup of every project sends the
#   custom metric afp/backup_ok (1: every dump made, 0: not; afp/project.py). A
#   backup that does not run at all sends nothing and is not noticed here.
# - alarm-afp-nlb-unhealthy: users cannot reach the apps (the VM or Caddy is
#   down): the NLB's own TCP health checks of ports 80 and 443.
# - alarm-afp-check-db: the DB does not answer (afp check-db, every hour).
# - alarm-afp-vm-memory: the VM is short of memory (Oracle Cloud Agent).
# - alarm-afp-vm-disk: the VM's disk is nearly full (afp check-disk, every hour).
#
# The hourly metrics are read over [1h], as long as they are posted apart: a
# 0 (or a full disk) keeps the alarm firing until the next hour's data point
# is fine. An hourly check that stops running sends nothing and is not
# noticed here; a VM that is down is noticed by alarm-afp-nlb-unhealthy.

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

variable "nlb_id" {
  description = "OCID of the NLB (nlb-afp-main) whose health checks are watched"
  type        = string
}

variable "instance_id" {
  description = "OCID of the VM whose memory is watched"
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

resource "oci_monitoring_alarm" "nlb_unhealthy" {
  compartment_id        = var.compartment_id
  metric_compartment_id = var.compartment_id
  display_name          = "alarm-afp-nlb-unhealthy"
  is_enabled            = true
  namespace             = "oci_nlb"
  query                 = "UnhealthyBackendsPerNlb[1m]{resourceId = \"${var.nlb_id}\"}.max() > 0"
  pending_duration      = "PT5M"
  severity              = "CRITICAL"
  destinations          = [var.topic_id]
  body                  = <<-EOT
    Users cannot reach the apps: for 5 minutes the NLB's health check of port
    80 or 443 on the VM has failed. The VM is down, or Caddy is not running.
    Check: the VM in the console; make ssh CMD='sudo docker ps' (is afp-caddy up?).
    To start Caddy and the projects again: make platform.
  EOT
}

resource "oci_monitoring_alarm" "check_db" {
  compartment_id        = var.compartment_id
  metric_compartment_id = var.compartment_id
  display_name          = "alarm-afp-check-db"
  is_enabled            = true
  namespace             = "afp"
  query                 = "check_db_ok[1h].min() < 1"
  severity              = "CRITICAL"
  destinations          = [var.topic_id]
  body                  = <<-EOT
    The DB did not answer SELECT 1 from the VM (afp check-db, every hour;
    check_db_ok = 0). Every project shares it.
    Why: the log of that run in bucket ${var.logs_bucket_name},
    <time>-check-db.log, and the DB system (mysql-afp-main) in the console.
    The alarm stays firing until a later hourly check is fine.
  EOT
}

resource "oci_monitoring_alarm" "vm_memory" {
  compartment_id        = var.compartment_id
  metric_compartment_id = var.compartment_id
  display_name          = "alarm-afp-vm-memory"
  is_enabled            = true
  namespace             = "oci_computeagent"
  query                 = "MemoryUtilization[5m]{resourceId = \"${var.instance_id}\"}.mean() > 90"
  pending_duration      = "PT5M"
  severity              = "WARNING"
  destinations          = [var.topic_id]
  body                  = <<-EOT
    The VM has used more than 90% of its memory for a while. Every project
    runs on it; one more may not fit, and a container may be killed.
    Which: make ssh CMD='sudo docker stats --no-stream'.
  EOT
}

resource "oci_monitoring_alarm" "vm_disk" {
  compartment_id        = var.compartment_id
  metric_compartment_id = var.compartment_id
  display_name          = "alarm-afp-vm-disk"
  is_enabled            = true
  namespace             = "afp"
  query                 = "disk_used_percent[1h].max() > 90"
  severity              = "WARNING"
  destinations          = [var.topic_id]
  body                  = <<-EOT
    The VM's disk is more than 90% full (afp check-disk, every hour). When it
    is full, deploys and the apps' writes fail.
    What: make ssh CMD='sudo docker system df' (images, containers, build cache).
  EOT
}

output "alarm_id" {
  value = oci_monitoring_alarm.backup.id
}
