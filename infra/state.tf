# The Terraform state store itself. It was bootstrapped manually (chicken-and-
# egg: the backend must exist before the first `terraform init`) and is now
# managed here as well.
resource "azurerm_storage_account" "tfstate" {
  name                = "arxivisualtfstate"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  network_rules {
    default_action = "Allow"
    bypass         = ["None"]
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}
