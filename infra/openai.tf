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

# Main narration/scene-generation model (plus visual QA and repair). Retires
# 2027-02-09 (az cognitiveservices account list-models: deprecation.inference),
# so all traffic has to move to gpt-6-luna below before then; it stays deployed
# as the rollback target until the cut-over has settled.
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

# Successor to gpt-5-mini. NOT referenced by any app yet: a follow-up one-line
# PR points the worker's AZURE_OPENAI_DEPLOYMENT at it after an eval smoke test
# (evals.yml `deployment` input), with gpt-5-mini kept for rollback.
# Why: Azure Retail Prices API (eastus2, Global Standard, per 1M tokens) lists
# it at US$0.10 input / $0.50 output (cached input $0.01, cache write $0.125;
# long-context requests $0.20 / $0.75) vs gpt-5-mini's $0.25 / $2.00, checked
# 2026-10-08. Output is ~88% of the gpt-5-mini bill (Sep 2026), so at the
# Sep 16-Oct 7 token volume this saves ~CA$430/mo if luna emits 1.2x
# gpt-5-mini's output tokens (CA$320-490 across 0.75x-2x; breakeven at 4.3x).
# There is no quality data on this pipeline yet.
# Verified 2026-10-08: version 2026-09-22 is GenerallyAvailable and the default
# (list-models); GlobalStandard quota in eastus2 is 0 of 10,000 (K TPM) used
# (az cognitiveservices usage list), so 250 fits.
# NoAutoUpgrade pins this version and its price; nothing moves under us. The
# flip side: the version RETIRES 2028-03-11 (list-models deprecation.inference),
# before the credits end on 2028-07-29, and a NoAutoUpgrade deployment stops
# serving on that date instead of moving on. Migrate around 2028-01 (Service
# Health gives >= 60 days' notice).
resource "azurerm_cognitive_deployment" "gpt_6_luna" {
  name                 = "gpt-6-luna"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-6-luna"
    version = "2026-09-22"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 250
  }

  rai_policy_name        = "Microsoft.DefaultV2"
  version_upgrade_option = "NoAutoUpgrade"
}

# gpt-5.6-sol (2026-07-09) was removed here on 2026-10-08: zero requests since
# 2026-09-07 20:00Z (AzureOpenAIRequests), and 10x gpt-5-mini's output price
# (US$20 vs $2 per 1M, Retail Prices API; CA$195.70 in its last week of use,
# Sep 1-7). Pay-per-token meant it cost nothing idle, but an unused expensive
# deployment invites a stale env var or a leaked key to spend on it. Old
# branches that still set VISUAL_QA_MODEL to it would recreate it on apply;
# don't apply from them.
