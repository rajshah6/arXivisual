# Log Analytics workspace backing the Container Apps environment (auto-named
# by the portal when the environment was created).
resource "azurerm_log_analytics_workspace" "main" {
  name                = "workspace-arxivisualrg2OvU"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# Container Apps managed environment (workload-profiles mode, Consumption
# profile only).
resource "azurerm_container_app_environment" "main" {
  name                = "arxivisual-api-env"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

locals {
  app_image = "ca82c08e2eadacr.azurecr.io/arxivisual-api:gh-d19c154f03c9b9d59a15510d932d9955d60da5ae"
}

# ---------------------------------------------------------------------------
# arxivisual-api: external FastAPI service on port 8000.
# Pulls its image with a system-assigned identity (AcrPull, see registry.tf).
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "api" {
  # The deploy workflow (gh-<sha> tags) owns the image; Terraform owns
  # everything else. Without this, every CD deploy would appear as drift.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  name                         = "arxivisual-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  registry {
    server   = "ca82c08e2eadacr.azurecr.io"
    identity = "system" # lowercase to match what the ACA API stores; "System" causes a perpetual cosmetic diff
  }

  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "s3-access-key"
    value = var.s3_access_key
  }
  secret {
    name  = "s3-secret-key"
    value = var.s3_secret_key
  }
  secret {
    name  = "azure-openai-api-key"
    value = var.azure_openai_api_key
  }
  secret {
    name  = "langfuse-public-key"
    value = var.langfuse_public_key
  }
  secret {
    name  = "langfuse-secret-key"
    value = var.langfuse_secret_key
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "arxivisual-api"
      image  = local.app_image
      cpu    = 2.0
      memory = "4Gi"

      env {
        name  = "LLM_PROVIDER"
        value = "azure"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = "https://arxivisual-openai.openai.azure.com"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = "gpt-5-mini"
      }
      env {
        name  = "STORAGE_MODE"
        value = "r2"
      }
      env {
        name  = "S3_ENDPOINT"
        value = "https://0c4b2250cd401bcd63be9985bae2710a.r2.cloudflarestorage.com"
      }
      env {
        name  = "S3_BUCKET"
        value = "arxivisual"
      }
      env {
        name        = "S3_ACCESS_KEY"
        secret_name = "s3-access-key"
      }
      env {
        name        = "S3_SECRET_KEY"
        secret_name = "s3-secret-key"
      }
      env {
        name  = "S3_PUBLIC_URL"
        value = "https://pub-c68fa9a916b34af1bcbdb557f12d9287.r2.dev"
      }
      env {
        name  = "ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "RENDER_MODE"
        value = "local"
      }
      env {
        name  = "AZURE_OPENAI_REASONING_EFFORT"
        value = "medium"
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "LANGFUSE_PUBLIC_KEY"
        secret_name = "langfuse-public-key"
      }
      env {
        name        = "LANGFUSE_SECRET_KEY"
        secret_name = "langfuse-secret-key"
      }
      env {
        name  = "LANGFUSE_HOST"
        value = "https://us.cloud.langfuse.com"
      }
      env {
        name  = "LANGFUSE_TRACING_ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "ENABLE_VISUAL_QA"
        value = "1"
      }
      env {
        name  = "VISUAL_QA_MODEL"
        value = "gpt-5.6-sol"
      }

      env {
        name  = "USE_TEMPORAL"
        value = "1"
      }

      env {
        name  = "TEMPORAL_ADDRESS"
        value = "arxivisual-temporal.internal.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io:443"
      }

      env {
        name  = "TEMPORAL_TLS"
        value = "1"
      }
    }
  }
}

# ---------------------------------------------------------------------------
# arxivisual-temporal: Temporal server (auto-setup image) on internal TCP 7233.
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "temporal" {
  name                         = "arxivisual-temporal"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  ingress {
    external_enabled = false
    target_port      = 7233
    # gRPC over ACA's standard http2 ingress (envoy terminates TLS on :443 and
    # forwards h2c) — raw TCP ingress proved unroutable on this environment.
    transport        = "http2"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  secret {
    name  = "pg-pwd"
    value = var.postgres_admin_password
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "arxivisual-temporal"
      image  = "temporalio/auto-setup:1.23.1.1"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "DB"
        value = "postgres12"
      }
      env {
        name  = "DB_PORT"
        value = "5432"
      }
      env {
        name  = "POSTGRES_USER"
        value = "rabidcheese9"
      }
      env {
        name        = "POSTGRES_PWD"
        secret_name = "pg-pwd"
      }
      env {
        name  = "POSTGRES_SEEDS"
        value = "arxivisual-db.postgres.database.azure.com"
      }
      env {
        name  = "DBNAME"
        value = "temporal"
      }
      env {
        name  = "VISIBILITY_DBNAME"
        value = "temporal_visibility"
      }
      env {
        name  = "POSTGRES_TLS_ENABLED"
        value = "true"
      }
      env {
        name  = "POSTGRES_TLS_DISABLE_HOST_VERIFICATION"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "info"
      }
      env {
        name  = "SQL_TLS_ENABLED"
        value = "true"
      }
      env {
        name  = "SQL_TLS"
        value = "true"
      }
      env {
        name  = "SQL_TLS_DISABLE_HOST_VERIFICATION"
        value = "true"
      }
      env {
        name  = "SQL_MAX_CONNS"
        value = "2"
      }
      env {
        name  = "SQL_MAX_IDLE_CONNS"
        value = "1"
      }
      env {
        name  = "NUM_HISTORY_SHARDS"
        value = "1"
      }

      env {
        name  = "BIND_ON_IP"
        value = "0.0.0.0"
      }

      env {
        name  = "TEMPORAL_BROADCAST_ADDRESS"
        value = "127.0.0.1"
      }

      # The live probes only set port/interval/failure-threshold (+ initial
      # delay on startup); timeout and success threshold are set explicitly to
      # the Kubernetes/ACA platform defaults so the first apply materializes
      # the values the platform already uses implicitly.
      startup_probe {
        transport               = "TCP"
        port                    = 7233
        initial_delay           = 10
        interval_seconds        = 10
        failure_count_threshold = 30
        timeout                 = 1
      }

      readiness_probe {
        transport               = "TCP"
        port                    = 7233
        interval_seconds        = 10
        failure_count_threshold = 3
        success_count_threshold = 1
        timeout                 = 1
      }
    }
  }
}

# ---------------------------------------------------------------------------
# arxivisual-worker: Temporal worker, no ingress. Pulls the image with the
# registry admin credential (stored as a container app secret).
# ---------------------------------------------------------------------------
resource "azurerm_container_app" "worker" {
  # The deploy workflow (gh-<sha> tags) owns the image; Terraform owns
  # everything else. Without this, every CD deploy would appear as drift.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  name                         = "arxivisual-worker"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  max_inactive_revisions       = 100

  registry {
    server               = "ca82c08e2eadacr.azurecr.io"
    username             = "ca82c08e2eadacr"
    password_secret_name = "ca82c08e2eadacrazurecrio-ca82c08e2eadacr"
  }

  secret {
    name  = "azure-openai-api-key"
    value = var.azure_openai_api_key
  }
  secret {
    name  = "s3-access-key"
    value = var.s3_access_key
  }
  secret {
    name  = "s3-secret-key"
    value = var.s3_secret_key
  }
  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "langfuse-public-key"
    value = var.langfuse_public_key
  }
  secret {
    name  = "langfuse-secret-key"
    value = var.langfuse_secret_key
  }
  secret {
    name  = "ca82c08e2eadacrazurecrio-ca82c08e2eadacr"
    value = var.acr_admin_password
  }
  secret {
    # libpq-style URI for the KEDA postgresql scaler (asyncpg's ssl= param is
    # not understood by libpq; sslmode= is).
    name  = "keda-pg-conn"
    value = "postgresql://rabidcheese9:${urlencode(var.postgres_admin_password)}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/arxiviz?sslmode=require"
  }

  template {
    # KEDA autoscaling off durable queue depth: papers queue on Temporal, and
    # the count of active jobs in OUR domain table is the truthful backlog
    # signal. One extra replica per ~2 active jobs, capped at 3 (each replica
    # is 2 vCPU; the render concurrency cap applies per replica).
    min_replicas = 1
    max_replicas = 3

    custom_scale_rule {
      name             = "active-jobs"
      custom_rule_type = "postgresql"
      metadata = {
        query                      = "SELECT COUNT(*) FROM processing_jobs WHERE status IN ('queued','processing')"
        targetQueryValue           = "2"
        activationTargetQueryValue = "0"
      }
      authentication {
        secret_name       = "keda-pg-conn"
        trigger_parameter = "connection"
      }
    }

    container {
      name    = "arxivisual-worker"
      image   = local.app_image
      command = ["python", "/app/temporal_app/worker.py"]
      cpu     = 2.0
      memory  = "4Gi"

      env {
        name  = "LLM_PROVIDER"
        value = "azure"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = "https://arxivisual-openai.openai.azure.com"
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = "gpt-5-mini"
      }
      env {
        name  = "STORAGE_MODE"
        value = "r2"
      }
      env {
        name  = "S3_ENDPOINT"
        value = "https://0c4b2250cd401bcd63be9985bae2710a.r2.cloudflarestorage.com"
      }
      env {
        name  = "S3_BUCKET"
        value = "arxivisual"
      }
      env {
        name  = "S3_PUBLIC_URL"
        value = "https://pub-c68fa9a916b34af1bcbdb557f12d9287.r2.dev"
      }
      env {
        name  = "ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "RENDER_MODE"
        value = "local"
      }
      env {
        name  = "AZURE_OPENAI_REASONING_EFFORT"
        value = "medium"
      }
      env {
        name  = "LANGFUSE_HOST"
        value = "https://us.cloud.langfuse.com"
      }
      env {
        name  = "LANGFUSE_TRACING_ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "ENABLE_VISUAL_QA"
        value = "1"
      }
      env {
        name  = "VISUAL_QA_MODEL"
        value = "gpt-5.6-sol"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "S3_ACCESS_KEY"
        secret_name = "s3-access-key"
      }
      env {
        name        = "S3_SECRET_KEY"
        secret_name = "s3-secret-key"
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "LANGFUSE_PUBLIC_KEY"
        secret_name = "langfuse-public-key"
      }
      env {
        name        = "LANGFUSE_SECRET_KEY"
        secret_name = "langfuse-secret-key"
      }
      env {
        name  = "TEMPORAL_ADDRESS"
        value = "arxivisual-temporal.internal.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io:443"
      }

      env {
        name  = "TEMPORAL_TLS"
        value = "1"
      }
      env {
        name  = "RENDER_CONCURRENCY"
        value = "3"
      }
    }
  }
}
