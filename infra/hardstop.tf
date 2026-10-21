# Hard stop: the only thing in this directory that STOPS spend instead of
# mailing about it.
#
# Why: the MCA billing profile's spending limit is Off (status LimitRemoved
# since 2026-07-29) and a card is on file, so when the US$10K startup credit
# runs out (~mid 2027 at the Oct 2026 burn, a year before its 2028-07-29
# expiry) the card simply starts paying ~CA$1,300/month, and a runaway
# (leaked key, a bot past the admission caps) during the credit period just
# burns credit faster. Every budget notification is email-only; the spending
# limit is a portal-only switch Ajith has to flip. Audit 2026-10-21, findings
# spending-limit-off-card-live and no-automated-stop-mechanism.
#
# What: the Learn-documented chain (cost-management-budget-scenario):
#
#   budget notification (Actual > hard_stop_threshold_percent, budgets.tf)
#     -> action group arxivisual-hard-stop (automation_runbook_receiver)
#       -> webhook on runbook arxivisual-hard-stop (runbooks/hard-stop.ps1)
#         -> POST .../containerApps/<app>/stop on worker, api, web, temporal
#
# A stopped app has no replicas and no scale rule can wake it, so Container
# Apps compute ends at once and Foundry Models spend ends because nothing
# calls the model. Postgres, ACR, R2, the app definitions and their revisions
# survive; recovery is `az containerapp start` x4 (README "Hard stop").
#
# Cost: ~CA$0. The Automation account is free; Basic-SKU job minutes are
# billed at US$0.002/min after 500 free minutes per subscription per month
# (Learn: automation overview, "Pricing"), and one stop run is 2-5 minutes.
# Action-group runbook receivers and budget notifications are free.
#
# Limits, so nobody trusts this further than it goes:
#   - Budgets evaluate once a day on cost data that lands 8-24 h late, so the
#     stop arrives 1-2 days after the threshold is crossed. At today's burn
#     that is ~CA$90 of overshoot; a 10x runaway can add ~CA$900.
#   - Each threshold fires ONCE per budget period. Starting the apps again in
#     the same month runs unguarded until the next month.
#   - Budget cost is pre-credit, so the stop protects the credit period and
#     the card period alike (and fires on paper cost even while credits pay).
#   - The stop kills in-flight papers; `arxivisual-worker` has no graceful
#     shutdown (README "Applying").
#   - The webhook URL is a bearer secret held in Terraform state, and the
#     webhook expires on `expiry_time` (renew by replacing it: the attribute
#     is ForceNew).
#
# Gated behind var.hard_stop_enabled (default false): merging this changes
# nothing; the plan with it on is 7 adds plus one in-place budget change.
# Microsoft.Automation is NOT registered on the subscription (2026-10-21) and
# versions.tf never registers providers, so before the first apply with it on:
#   az provider register -n Microsoft.Automation
# After that apply, start the runbook from the portal with DryRun = true once
# (README "Hard stop") so the identity, the role and the API are proven
# before a budget ever calls it.

locals {
  hard_stop = var.hard_stop_enabled ? 1 : 0
}

# Basic is the SKU with the 500 free job minutes; the identity is what the
# runbook authenticates as (Connect-AzAccount -Identity), so no credential is
# stored anywhere.
resource "azurerm_automation_account" "hard_stop" {
  count = local.hard_stop

  name                = "arxivisual-automation"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "Basic"

  identity {
    type = "SystemAssigned"
  }
}

# A custom role with the two operations the runbook performs (GET the app,
# POST its stop action) and nothing else. The built-in "Container Apps
# Contributor" (358470bc-b998-42bd-ab17-a7e34c199c0f) read as least privilege
# but its Microsoft.App/containerApps/*/action wildcard matches
# listSecrets/action, which returns every api and worker secret
# (DATABASE_URL, the OpenAI key, R2, Langfuse) in plain text; Learn's
# container-apps/manage-secrets page names that role for exactly this and
# says to write a custom role without the wildcard (review 2026-10-21).
# start/action is left out on purpose: recovery is a human running
# `az containerapp start` (README "Hard stop"), and the identity that can
# stop the estate need not be able to undo it. Custom role names are unique
# per directory, hence the project prefix. Writing a role definition needs
# Microsoft.Authorization/roleDefinitions/write, which the subscription Owner
# who runs terraform here has (README "Backend / auth").
resource "azurerm_role_definition" "hard_stop" {
  count = local.hard_stop

  name        = "arxivisual-hard-stop"
  scope       = azurerm_resource_group.main.id
  description = "Read the arxivisual Container Apps and POST their stop action; nothing else (infra/hardstop.tf)."

  permissions {
    actions = [
      "Microsoft.App/containerApps/read",
      "Microsoft.App/containerApps/stop/action",
    ]
  }

  assignable_scopes = [azurerm_resource_group.main.id]
}

# Resource-group scope is enough for the runbook's Set-AzContext to find the
# subscription: the GitHub deploy principal holds only an RG-scoped
# Contributor (github_oidc.tf) and `az login` + `az containerapp update` work
# from deploy-backend.yml.
resource "azurerm_role_assignment" "hard_stop" {
  count = local.hard_stop

  scope              = azurerm_resource_group.main.id
  role_definition_id = azurerm_role_definition.hard_stop[0].role_definition_resource_id
  principal_id       = azurerm_automation_account.hard_stop[0].identity[0].principal_id
  # A managed identity is a service principal; saying so skips the AAD lookup
  # that races the brand-new identity's replication (same as frontend.tf).
  principal_type = "ServicePrincipal"
}

# The runtime the job executes in. PowerShell 7.2, the newest version the
# classic runbook API offers (runbook_type "PowerShell72"), was retired by
# Automation on 2026-09-30: no security updates, no support, and the
# retirement policy lets the platform cap retired runtimes at one instance
# (Learn whats-new July 2026, automation-runtime-retirement-policy). 7.4
# leaves PowerShell support on 2026-11-10. 7.6 is the current LTS (to
# 2028-11-14), GA in every public region since July 2026, and reachable only
# through a Runtime Environment (Learn automation-runbook-types, 7.6 tab).
# Az 15.1.0 is the version Learn lists as its default package and has the
# cmdlets the script uses (Connect-AzAccount, Set-AzContext,
# Invoke-AzRestMethod). It is pinned here because the provider reads the
# package map back and would otherwise plan to remove it, and removing a
# package is ForceNew (azurerm 4.81
# automation_runtime_environment_resource.go). The name carries the version
# because runtime_version is ForceNew: the next bump is a new environment
# and an in-place runbook update; the script itself does not change.
resource "azurerm_automation_runtime_environment" "hard_stop" {
  count = local.hard_stop

  name                  = "arxivisual-ps76"
  location              = azurerm_resource_group.main.location
  automation_account_id = azurerm_automation_account.hard_stop[0].id
  description           = "PowerShell 7.6 with Az for the arxivisual-hard-stop runbook (infra/hardstop.tf)."

  runtime_language = "PowerShell"
  runtime_version  = "7.6"

  runtime_default_packages = {
    az = "15.1.0"
  }
}

# Inline content is pushed to the draft and PUBLISHED by the provider on
# every change (azurerm 4.81 automation_runbook_resource.go), so editing the
# .ps1 and applying is the whole release process. runbook_type is the plain
# "PowerShell": that is the type that accepts a runtime_environment_name
# (provider docs), and the version comes from the environment above. The
# script carries the subscription id and resource group as literals on
# purpose: templatefile() would need every PowerShell `${...}` in it escaped,
# after which it could no longer be read or run as-is. The two values are
# pinned in variables.tf (subscription_id) and main.tf
# (azurerm_resource_group.main) and have not changed since the project began.
resource "azurerm_automation_runbook" "hard_stop" {
  count = local.hard_stop

  name                     = "arxivisual-hard-stop"
  location                 = azurerm_resource_group.main.location
  resource_group_name      = azurerm_resource_group.main.name
  automation_account_name  = azurerm_automation_account.hard_stop[0].name
  runbook_type             = "PowerShell"
  runtime_environment_name = azurerm_automation_runtime_environment.hard_stop[0].name
  log_verbose              = false
  log_progress             = false
  description              = "Stops arxivisual-worker, -api, -web and -temporal when the arxivisual-monthly budget's hard-stop threshold is crossed. Recovery: az containerapp start x4 (infra/README.md, Hard stop). Start with DryRun=true to test."
  content                  = file("${path.module}/runbooks/hard-stop.ps1")
}

# The URL is generated once, never readable again from Azure, and lives in
# state (sensitive). expiry_time is ForceNew: changing it mints a new URL and
# updates the action group below in the same apply. Set well past the budget
# end date (2028-07-31) so renewing the budget does not also mean replacing
# this; the API allows up to 10 years from creation.
resource "azurerm_automation_webhook" "hard_stop" {
  count = local.hard_stop

  name                    = "arxivisual-hard-stop-budget"
  resource_group_name     = azurerm_resource_group.main.name
  automation_account_name = azurerm_automation_account.hard_stop[0].name
  runbook_name            = azurerm_automation_runbook.hard_stop[0].name
  expiry_time             = "2035-12-31T00:00:00Z"
  enabled                 = true
}

# Its own action group, so nothing but the budget's hard-stop notification can
# ever reach the runbook (the arxivisual-alerts group in alerts.tf is wired to
# every monitoring rule and stays email-only). The mail here is in addition
# to the budget's own: it says "the HARD STOP fired", not "a threshold was
# crossed". The common alert schema is left off on the runbook receiver so
# the job log shows the budget's own payload; on a PowerShell 7 runbook that
# arrives as a string rather than the documented WebhookData object (Learn
# automation-webhooks), and the script logs it as delivered.
resource "azurerm_monitor_action_group" "hard_stop" {
  count = local.hard_stop

  name                = "arxivisual-hard-stop"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "arxivstop" # 12 characters max

  email_receiver {
    name                    = "owner"
    email_address           = var.contact_email
    use_common_alert_schema = true
  }

  automation_runbook_receiver {
    name                    = "stop-container-apps"
    automation_account_id   = azurerm_automation_account.hard_stop[0].id
    runbook_name            = azurerm_automation_runbook.hard_stop[0].name
    webhook_resource_id     = azurerm_automation_webhook.hard_stop[0].id
    service_uri             = azurerm_automation_webhook.hard_stop[0].uri
    is_global_runbook       = false
    use_common_alert_schema = false
  }
}
