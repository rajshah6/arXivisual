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

output "web_fqdn" {
  description = "Default public FQDN of the arxivisual-web (frontend) container app."
  value       = azurerm_container_app.web.ingress[0].fqdn
}

output "web_identity_principal_id" {
  description = "Principal id of the frontend app's user-assigned identity (holds AcrPull)."
  value       = azurerm_user_assigned_identity.web.principal_id
}

output "custom_domain_verification_id" {
  description = "Value of the asuid TXT records Porkbun needs for custom domains on this environment."
  value       = azurerm_container_app_environment.main.custom_domain_verification_id
}

output "environment_static_ip" {
  description = "Static inbound IP of the environment — the apex A record for arxivisual.org points here."
  value       = azurerm_container_app_environment.main.static_ip_address
}

output "application_insights_app_id" {
  description = "App ID of the arxivisual-insights Application Insights component (non-sensitive; the connection string stays inside the container app secrets)."
  value       = azurerm_application_insights.main.app_id
}
