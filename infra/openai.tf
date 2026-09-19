# Azure OpenAI account plus its three model deployments.
resource "azurerm_cognitive_account" "openai" {
  name                = "arxivisual-openai"
  resource_group_name = azurerm_resource_group.main.name
  location            = "eastus2"
  kind                = "OpenAI"
  sku_name            = "S0"

  custom_subdomain_name         = "arxivisual-openai"
  public_network_access_enabled = true
}

# Main narration/scene-generation model.
resource "azurerm_cognitive_deployment" "gpt_5_mini" {
  name                 = "gpt-5-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-5-mini"
    version = "2025-08-07"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 250
  }

  rai_policy_name        = "Microsoft.DefaultV2"
  version_upgrade_option = "OnceNewDefaultVersionAvailable"
}

# Voiceover text-to-speech model.
resource "azurerm_cognitive_deployment" "gpt_4o_mini_tts" {
  name                 = "gpt-4o-mini-tts"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini-tts"
    version = "2025-12-15"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 50
  }

  rai_policy_name        = "Microsoft.DefaultV2"
  version_upgrade_option = "OnceNewDefaultVersionAvailable"
}

# Idle standby deployment: no app references it. VISUAL_QA_MODEL and
# VISUAL_QA_REPAIR_MODEL are both gpt-5-mini (container_apps.tf). GlobalStandard
# is pay-per-token, so it costs nothing while unused; it only holds quota.
resource "azurerm_cognitive_deployment" "gpt_5_6_sol" {
  name                 = "gpt-5.6-sol"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-5.6-sol"
    version = "2026-07-09"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 250
  }

  rai_policy_name        = "Microsoft.DefaultV2"
  version_upgrade_option = "OnceNewDefaultVersionAvailable"
}
