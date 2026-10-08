# Postgres flexible server. NOTE: deliberately in westus3 (B1ms capacity was
# unavailable in eastus2 at creation time) while the rest of the stack is in
# eastus2.
resource "azurerm_postgresql_flexible_server" "main" {
  name                = "arxivisual-db"
  resource_group_name = azurerm_resource_group.main.name
  location            = "westus3"

  version                       = "16"
  administrator_login           = "rabidcheese9"
  administrator_password        = var.postgres_admin_password
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  storage_tier                  = "P4"
  auto_grow_enabled             = false
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  zone                          = "3"
  public_network_access_enabled = true

  authentication {
    active_directory_auth_enabled = false
    password_auth_enabled         = true
  }

  # Custom maintenance window: Sunday 21:00-22:00 UTC, inside the quietest
  # stretch of the day (19:00-24:00 UTC). The default system-managed window
  # falls between 23:00 and 07:00 server-region time (06:00-14:00 UTC for
  # westus3), which is how a maintenance restart on 2026-09-14 07:34Z landed on
  # live traffic: API 5xx and 46 minutes of Temporal errors. day_of_week 0 is
  # Sunday and times are UTC. Azure applies a changed window from the NEXT
  # maintenance cycle on, and custom-window servers are patched at least 7 days
  # after system-managed ones in the region.
  maintenance_window {
    day_of_week  = 0
    start_hour   = 21
    start_minute = 0
  }
}

# Application database.
resource "azurerm_postgresql_flexible_server_database" "arxiviz" {
  name      = "arxiviz"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Temporal persistence store.
resource "azurerm_postgresql_flexible_server_database" "temporal" {
  name      = "temporal"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Temporal visibility store.
resource "azurerm_postgresql_flexible_server_database" "temporal_visibility" {
  name      = "temporal_visibility"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# btree_gin is required by Temporal's advanced visibility schema.
resource "azurerm_postgresql_flexible_server_configuration" "azure_extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "BTREE_GIN"
}

# Connection headroom: API pool (≤15) + Temporal server (≤16 with capped
# pools) + worker activities + KEDA scaler probes exceeded the B1ms default
# of 50 during revision transitions (observed: "remaining connection slots
# are reserved" crash-loops). Static parameter — a server restart is required
# for it to take effect; do it deliberately (Temporal makes in-flight jobs
# safe across the restart).
resource "azurerm_postgresql_flexible_server_configuration" "max_connections" {
  name      = "max_connections"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "100"
}

# 0.0.0.0-0.0.0.0 is Azure's "allow Azure services" sentinel rule; Container
# Apps reach the DB through it.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAllAzureServicesAndResourcesWithinAzureIps_2026-8-19_12-29-0"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
