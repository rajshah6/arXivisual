terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }

  # State storage was bootstrapped manually (see state.tf, which also codifies it).
  #
  # NOTE on auth: `use_azuread_auth = true` was attempted first but fails with
  # AuthorizationPermissionMismatch because the signed-in user is subscription
  # Owner without a blob DATA-plane role (Storage Blob Data Contributor). The
  # backend therefore uses its default behavior: it looks up the storage
  # account access key via ARM (the Owner role can list keys) and talks to the
  # blob endpoint with the shared key. To switch to AAD auth later, grant
  # yourself "Storage Blob Data Contributor" on arxivisualtfstate and add
  # `use_azuread_auth = true` back.
  backend "azurerm" {
    resource_group_name  = "arxivisual-rg"
    storage_account_name = "arxivisualtfstate"
    container_name       = "tfstate"
    key                  = "arxivisual.tfstate"
  }
}

provider "azurerm" {
  features {}

  subscription_id = var.subscription_id

  # All resource providers were registered when the infra was created by hand;
  # never attempt registration from Terraform.
  resource_provider_registrations = "none"
}

provider "azuread" {}

provider "azapi" {
  subscription_id = var.subscription_id
}
