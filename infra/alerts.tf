# Alerting. Before this file nothing here notified anyone: a Postgres restart
# (2026-09-14 07:34Z: API 5xx plus 46 minutes of Temporal errors), a steady
# trickle of silent Temporal fallbacks and 208 probe failures all went
# unnoticed. Deliberately small and cheap:
#
#   - one action group that emails var.contact_email;
#   - metric alerts on the Postgres server and the three backend Container
#     Apps (billed per monitored time series, cents per month each);
#   - three log alerts on the existing Log Analytics workspace, evaluated every
#     15 minutes (the cheapest useful frequency, ~0.50 USD/month per rule).
#
# No availability web tests (they are billed per test): outside-in uptime
# probing is a scheduled GitHub Actions workflow instead.
#
# Metric names and namespaces were checked against the live metric definitions
# (az monitor metrics list-definitions) and the Azure Monitor supported-metrics
# reference; the three KQL queries were run against the workspace. Thresholds
# are variables (variables.tf, "Alerting") whose defaults come from the 14 days
# of data before 2026-09-18.

resource "azurerm_monitor_action_group" "main" {
  name                = "arxivisual-alerts"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "arxivisual" # 12 characters max

  email_receiver {
    name                    = "owner"
    email_address           = var.contact_email
    use_common_alert_schema = true
  }
}

# ---------------------------------------------------------------------------
# Postgres flexible server (namespace Microsoft.DBforPostgreSQL/flexibleServers).
# ---------------------------------------------------------------------------

# 32 GB with auto-grow off (database.tf); a full disk flips the server to
# read-only. ~14% used in Sept 2026, so this is a slow-moving early warning.
resource "azurerm_monitor_metric_alert" "postgres_storage" {
  name                = "arxivisual-db-storage"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "arxivisual-db storage use is above ${var.alert_postgres_storage_percent}% (32 GB, auto-grow off). A full disk makes the server read-only: free space or raise storage_mb in infra/database.tf."
  severity            = 2
  frequency           = "PT15M"
  window_size         = "PT1H"

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.alert_postgres_storage_percent
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
}

# is_db_alive is 1 (up) or 0 (down), sampled every 10 s; Microsoft's guidance
# is to aggregate it with MAX per minute, so this fires once the server has
# reported down for a whole minute.
#
# Known gap: a quick restart does not report 0, it reports NOTHING. The
# 2026-09-14 restart is a one-minute hole in this metric (07:35Z, sample count
# 0) and a static metric alert does not evaluate missing data, so this rule
# catches a server that stays down, not a blip. Blips are caught downstream by
# the api-5xx and temporal-fallback log alerts below (both would have fired on
# 09-14). The proper signal is a Resource Health activity-log alert, which
# needs the Microsoft.ResourceHealth provider registered on the subscription
# first (it is not, and versions.tf never registers providers).
resource "azurerm_monitor_metric_alert" "postgres_down" {
  name                = "arxivisual-db-down"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "arxivisual-db reported itself down (is_db_alive = 0) for a full minute. The API, the worker and Temporal all depend on it."
  severity            = 0
  frequency           = "PT1M"
  window_size         = "PT1M"

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "is_db_alive"
    aggregation      = "Maximum"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
}

# ---------------------------------------------------------------------------
# Backend Container Apps (namespace Microsoft.App/containerApps). The frontend
# is left out on purpose: it is not serving arxivisual.org yet.
# ---------------------------------------------------------------------------

locals {
  alert_container_apps = {
    api      = azurerm_container_app.api
    temporal = azurerm_container_app.temporal
    worker   = azurerm_container_app.worker
  }
}

# All three run min_replicas = 1, so an average below 1 over five minutes means
# the app had no running replica for part of the window. Only ACTIVE revisions
# emit Replicas (deactivated ones emit nothing), so a revision roll does not
# drag the average down: no 5-minute bin dipped below 1 across eight API
# revision rolls and a week of worker deploys in Sept 2026.
resource "azurerm_monitor_metric_alert" "app_no_replicas" {
  for_each = local.alert_container_apps

  name                = "${each.value.name}-no-replicas"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [each.value.id]
  description         = "${each.value.name} averaged fewer than 1 running replica over 5 minutes (min_replicas is 1). Check the revision's provisioning state and system logs."
  severity            = 1
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
}

# RestartCount is sparse: one sample per container restart, per replica, and
# nothing otherwise (the worker logged four isolated restarts, value 1 each, in
# the two weeks before this was written). Total over 15 minutes crosses the
# default of 3 only in a crash loop, whether the platform reports each restart
# as 1 or as the replica's running total (the docs say the latter).
resource "azurerm_monitor_metric_alert" "app_restarts" {
  for_each = local.alert_container_apps

  name                = "${each.value.name}-restarts"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [each.value.id]
  description         = "${each.value.name} containers restarted more than ${var.alert_restart_count} times in 15 minutes (crash loop). Check the console logs of the newest revision."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = var.alert_restart_count
  }

  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
}

# ---------------------------------------------------------------------------
# Log alerts on the Log Analytics workspace (Container Apps console logs and
# the workspace-based Application Insights tables live in the same one).
# Stateful (auto-mitigation): one mail when a rule fires, one when it clears,
# not one per evaluation. Queries are single-line strings on purpose: a heredoc
# adds a trailing newline the API may not echo back.
# ---------------------------------------------------------------------------

locals {
  # api/routes.py logs this when starting the Temporal workflow fails and the
  # request falls back (fail-open) to the legacy in-process pipeline.
  alert_query_temporal_fallback = "ContainerAppConsoleLogs_CL | where Log_s has 'Temporal unavailable'"

  # Only the API records server spans, so no role filter (the role was still
  # "unknown_service" when this was written). ResultCode is a string.
  alert_query_api_5xx = "AppRequests | where toint(ResultCode) >= 500"

  alert_query_worker_errors = "ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'arxivisual-worker' | where Log_s has 'Traceback' or Log_s has 'Pipeline failed'"
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "temporal_fallback" {
  name                = "arxivisual-temporal-fallback"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_log_analytics_workspace.main.location
  scopes              = [azurerm_log_analytics_workspace.main.id]
  description         = "The API logged 'Temporal unavailable' and ran a paper on the legacy in-process pipeline (no durability, no checkpointing, no repair pass). Check arxivisual-temporal and its Postgres connection."
  severity            = 2

  evaluation_frequency    = "PT15M"
  window_duration         = "PT15M"
  auto_mitigation_enabled = true

  criteria {
    query                   = local.alert_query_temporal_fallback
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = var.alert_temporal_fallback_count

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.main.id]
  }
}

# Request traces are sampled at 20% (OTEL_TRACES_SAMPLER_ARG on the apps), so
# rows undercount by 5x; summing ItemCount (5 per sampled row) estimates the
# real number and stays right if the sampling rate changes.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "api_5xx" {
  name                = "arxivisual-api-5xx"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_log_analytics_workspace.main.location
  scopes              = [azurerm_log_analytics_workspace.main.id]
  description         = "arxivisual-api answered more than ${var.alert_api_5xx_count} requests (estimated) with a 5xx in 15 minutes (Application Insights AppRequests, sampling-corrected). The normal rate is zero."
  severity            = 1

  evaluation_frequency    = "PT15M"
  window_duration         = "PT15M"
  auto_mitigation_enabled = true

  criteria {
    query                   = local.alert_query_api_5xx
    time_aggregation_method = "Total"
    metric_measure_column   = "ItemCount"
    operator                = "GreaterThan"
    threshold               = var.alert_api_5xx_count

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.main.id]
  }
}

# "Pipeline failed" is today only the job's error text in Postgres; the worker
# does not log it. The term is matched anyway so a future log line lights this
# rule up without touching Terraform.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "worker_errors" {
  name                = "arxivisual-worker-errors"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_log_analytics_workspace.main.location
  scopes              = [azurerm_log_analytics_workspace.main.id]
  description         = "arxivisual-worker logged more than ${var.alert_worker_error_count} 'Traceback' / 'Pipeline failed' lines in 15 minutes. A few tracebacks are routine (failed renders of generated code); this many means something systemic."
  severity            = 2

  evaluation_frequency    = "PT15M"
  window_duration         = "PT15M"
  auto_mitigation_enabled = true

  criteria {
    query                   = local.alert_query_worker_errors
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = var.alert_worker_error_count

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.main.id]
  }
}
