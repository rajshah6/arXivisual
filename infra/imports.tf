# ---------------------------------------------------------------------------
# Import blocks binding every existing Azure resource to its Terraform
# resource. These are consumed on the FIRST `terraform apply`; after the state
# contains the resources, this whole file can be deleted.
# ---------------------------------------------------------------------------

locals {
  sub = "/subscriptions/${var.subscription_id}"
  rg  = "/subscriptions/${var.subscription_id}/resourceGroups/arxivisual-rg"
}

import {
  to = azurerm_resource_group.main
  id = local.rg
}

# --- Registry ---------------------------------------------------------------

import {
  to = azurerm_container_registry.main
  id = "${local.rg}/providers/Microsoft.ContainerRegistry/registries/ca82c08e2eadacr"
}

import {
  to = azurerm_role_assignment.api_acr_pull
  id = "${local.rg}/providers/Microsoft.ContainerRegistry/registries/ca82c08e2eadacr/providers/Microsoft.Authorization/roleAssignments/b2a1a0f9-7530-4cca-a26d-1a05184135a4"
}

# --- Azure OpenAI -----------------------------------------------------------

import {
  to = azurerm_cognitive_account.openai
  id = "${local.rg}/providers/Microsoft.CognitiveServices/accounts/arxivisual-openai"
}

import {
  to = azurerm_cognitive_deployment.gpt_5_mini
  id = "${local.rg}/providers/Microsoft.CognitiveServices/accounts/arxivisual-openai/deployments/gpt-5-mini"
}

import {
  to = azurerm_cognitive_deployment.gpt_4o_mini_tts
  id = "${local.rg}/providers/Microsoft.CognitiveServices/accounts/arxivisual-openai/deployments/gpt-4o-mini-tts"
}

import {
  to = azurerm_cognitive_deployment.gpt_5_6_sol
  id = "${local.rg}/providers/Microsoft.CognitiveServices/accounts/arxivisual-openai/deployments/gpt-5.6-sol"
}

# --- Database ---------------------------------------------------------------

import {
  to = azurerm_postgresql_flexible_server.main
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db"
}

import {
  to = azurerm_postgresql_flexible_server_database.arxiviz
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db/databases/arxiviz"
}

import {
  to = azurerm_postgresql_flexible_server_database.temporal
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db/databases/temporal"
}

import {
  to = azurerm_postgresql_flexible_server_database.temporal_visibility
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db/databases/temporal_visibility"
}

import {
  to = azurerm_postgresql_flexible_server_configuration.azure_extensions
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db/configurations/azure.extensions"
}

import {
  to = azurerm_postgresql_flexible_server_firewall_rule.allow_azure_services
  id = "${local.rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/arxivisual-db/firewallRules/AllowAllAzureServicesAndResourcesWithinAzureIps_2026-8-19_12-29-0"
}

# --- Container Apps ---------------------------------------------------------

import {
  to = azurerm_log_analytics_workspace.main
  id = "${local.rg}/providers/Microsoft.OperationalInsights/workspaces/workspace-arxivisualrg2OvU"
}

import {
  to = azurerm_container_app_environment.main
  id = "${local.rg}/providers/Microsoft.App/managedEnvironments/arxivisual-api-env"
}

import {
  to = azurerm_container_app.api
  id = "${local.rg}/providers/Microsoft.App/containerApps/arxivisual-api"
}

import {
  to = azurerm_container_app.temporal
  id = "${local.rg}/providers/Microsoft.App/containerApps/arxivisual-temporal"
}

import {
  to = azurerm_container_app.worker
  id = "${local.rg}/providers/Microsoft.App/containerApps/arxivisual-worker"
}

# --- Budgets ----------------------------------------------------------------

import {
  to = azurerm_consumption_budget_subscription.monthly
  id = "${local.sub}/providers/Microsoft.Consumption/budgets/arxivisual-monthly"
}

import {
  to = azapi_resource.billing_monthly_reset_budget
  id = "/providers/Microsoft.Billing/billingAccounts/3f54dc1c-3b08-5841-bb04-33a83cf4e3a7:9dc3de7a-80d3-4d17-baf3-665da89267cd_2019-05-31/providers/Microsoft.CostManagement/budgets/MonthlyReset"
}

# --- GitHub OIDC ------------------------------------------------------------

import {
  to = azuread_application.github_deploy
  id = "/applications/133ab678-24c6-4f28-b383-53661fe8d6ff"
}

import {
  to = azuread_service_principal.github_deploy
  id = "/servicePrincipals/37b5aaca-7ddc-414b-a359-4880264f7433"
}

import {
  to = azuread_application_federated_identity_credential.github_main
  id = "133ab678-24c6-4f28-b383-53661fe8d6ff/federatedIdentityCredential/3934171f-dd96-416c-a4d5-4af4e94fc8e4"
}

import {
  to = azurerm_role_assignment.github_deploy_contributor
  id = "${local.rg}/providers/Microsoft.Authorization/roleAssignments/4cb5ec3f-2646-477c-81ea-6fbff0909aed"
}

# --- Terraform state storage ------------------------------------------------

import {
  to = azurerm_storage_account.tfstate
  id = "${local.rg}/providers/Microsoft.Storage/storageAccounts/arxivisualtfstate"
}

import {
  to = azurerm_storage_container.tfstate
  id = "${local.rg}/providers/Microsoft.Storage/storageAccounts/arxivisualtfstate/blobServices/default/containers/tfstate"
}
