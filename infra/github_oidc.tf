# GitHub Actions deploys via OIDC federation - no client secret exists.
resource "azuread_application" "github_deploy" {
  display_name = "arxivisual-github-deploy"
}

resource "azuread_service_principal" "github_deploy" {
  client_id = azuread_application.github_deploy.client_id
}

# Trust tokens issued by GitHub Actions for pushes to rajshah6/arXivisual main.
resource "azuread_application_federated_identity_credential" "github_main" {
  application_id = azuread_application.github_deploy.id
  display_name   = "github-arxivisual-main"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:rajshah6/arXivisual:ref:refs/heads/main"
}

# The deploy principal can manage everything inside the resource group.
resource "azurerm_role_assignment" "github_deploy_contributor" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github_deploy.object_id
}
