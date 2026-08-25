# Resource group holding everything (the Postgres server lives in westus3 but
# still belongs to this eastus2 resource group).
resource "azurerm_resource_group" "main" {
  name     = "arxivisual-rg"
  location = "eastus2"
}
