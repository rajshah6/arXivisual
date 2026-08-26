output "api_fqdn" {
  description = "Public FQDN of the arxivisual-api container app."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "temporal_internal_fqdn" {
  description = "Internal FQDN of the Temporal server (reachable only inside the environment)."
  value       = azurerm_container_app.temporal.ingress[0].fqdn
}

output "container_app_environment_default_domain" {
  description = "Default domain of the Container Apps environment."
  value       = azurerm_container_app_environment.main.default_domain
}

output "acr_login_server" {
  description = "Login server for the container registry."
  value       = azurerm_container_registry.main.login_server
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint URL."
  value       = azurerm_cognitive_account.openai.endpoint
}

output "postgres_fqdn" {
  description = "FQDN of the Postgres flexible server."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "github_deploy_client_id" {
  description = "Client ID GitHub Actions uses for OIDC login (AZURE_CLIENT_ID repo secret)."
  value       = azuread_application.github_deploy.client_id
}
