# Container registry that holds the arxivisual-api image (built/pushed by the
# GitHub Actions deploy workflow). Admin user is enabled because the worker app
# pulls with admin credentials; the API app pulls with its system identity.
resource "azurerm_container_registry" "main" {
  name                = "ca82c08e2eadacr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

# The API container app pulls images using its system-assigned identity.
resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.api.identity[0].principal_id
}
