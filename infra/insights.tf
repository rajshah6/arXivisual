# Application Insights for the backend (arxivisual-api + arxivisual-worker).
# Workspace-based: telemetry lands in the Log Analytics workspace the Container
# Apps environment already ships console logs to, so one workspace holds (and
# bills for) both. The connection string is wired into the two apps as the
# "appinsights-connection-string" secret in container_apps.tf — straight from
# this resource, never through a variable. Retention is the resource default.
#
# The backend enables the Azure Monitor OpenTelemetry distro only when
# APPLICATIONINSIGHTS_CONNECTION_STRING is present (backend/telemetry.py);
# OTEL_TRACES_SAMPLER=microsoft.fixed_percentage + OTEL_TRACES_SAMPLER_ARG=0.2
# keep 20% of request traces (without the sampler name the distro reads the
# argument as 0.2 traces/second). Langfuse runs on its own tracer provider and
# is untouched by that sampling.
resource "azurerm_application_insights" "main" {
  name                = "arxivisual-insights"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"

  # Cost fuse: request traces are sampled at 20% and app logs are not exported
  # (OTEL_LOGS_EXPORTER=none on the apps — Container Apps already ships stdout
  # to the same workspace), so 1 GB/day is far above normal and only bites if
  # something starts flooding telemetry.
  daily_data_cap_in_gb = 1
}
