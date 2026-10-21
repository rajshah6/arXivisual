<#
.SYNOPSIS
    arXivisual cost hard stop: stops the four Container Apps.

.DESCRIPTION
    Published into the arxivisual-automation account by infra/hardstop.tf and
    started by the arxivisual-hard-stop action group when the Actual
    hard-stop notification on the arxivisual-monthly budget fires
    (infra/budgets.tf). It POSTs the documented `stop` action
    (microsoft.app/containerapps/stop/action) on each app. A stopped app has
    no replicas and no scale rule can wake it, so Container Apps compute ends
    at once and Foundry Models spend ends because nothing calls the model.
    Postgres, ACR, R2 and the app definitions are untouched.

    Not `minReplicas/maxReplicas = 0`: the Container Apps scale limits allow
    0 for the minimum but 1 for the maximum (Learn: scale-app, "Scale
    definition"), and with min 0 / max 1 the api would wake on the next HTTP
    request and the worker on the next queued job.

    Recovery is manual and is NOT a terraform apply (the provider does not
    model the running state, so a plan reads "No changes" after a stop):
        az containerapp start -g arxivisual-rg -n <app>   (x4)
    See infra/README.md, "Hard stop".

    Start it by hand from the portal with DryRun = true to prove the
    identity, the role assignment and the API version without stopping
    anything: it prints each app's runningStatus and exits.

.PARAMETER WebhookData
    Filled in by Azure Automation when the action group calls the webhook
    (the budget payload, schemaId "AIP Budget Notification"). Only logged.

.PARAMETER DryRun
    Read and report, never stop. Defaults to false; the webhook passes no
    parameters, so a budget trigger always stops.
#>
param(
    [Parameter(Mandatory = $false)]
    [object] $WebhookData,

    [Parameter(Mandatory = $false)]
    [bool] $DryRun = $false
)

$ErrorActionPreference = 'Stop'

$SubscriptionId = '4301c7fd-ffa2-4ad1-bca9-a15ef2d2bd59'
$ResourceGroup  = 'arxivisual-rg'
# A GA version that lists the stop action (az provider show -n Microsoft.App,
# 2026-10-21) and the one frontend.tf already uses through azapi.
$ApiVersion     = '2025-07-01'
# Spenders first: the worker makes the LLM and TTS calls, the api admits the
# papers that cause them. web and temporal are small but still bill.
$Apps = @('arxivisual-worker', 'arxivisual-api', 'arxivisual-web', 'arxivisual-temporal')

if ($null -ne $WebhookData) {
    Write-Output "Triggered by webhook '$($WebhookData.WebhookName)'. Payload: $($WebhookData.RequestBody)"
} else {
    Write-Output "Started manually (DryRun = $DryRun)."
}

# The sandbox inherits no context; authenticate as the Automation account's
# system-assigned identity (Learn: enable-managed-identity-for-automation).
Disable-AzContextAutosave -Scope Process | Out-Null
$context = (Connect-AzAccount -Identity).context
Set-AzContext -SubscriptionId $SubscriptionId -DefaultProfile $context | Out-Null

function Get-AppPath([string] $App, [string] $Suffix) {
    $base = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.App/containerApps/$App"
    return "${base}${Suffix}?api-version=${ApiVersion}"
}

function Get-AppRunningStatus([string] $App) {
    $response = Invoke-AzRestMethod -Method GET -Path (Get-AppPath $App '')
    if ($response.StatusCode -ne 200) {
        throw "GET ${App} returned HTTP $($response.StatusCode): $($response.Content)"
    }
    return ($response.Content | ConvertFrom-Json).properties.runningStatus
}

$failed = @()
$stopping = @()

foreach ($app in $Apps) {
    try {
        $status = Get-AppRunningStatus $app
        Write-Output "${app}: runningStatus=${status}"
        if ($status -eq 'Stopped') {
            Write-Output "${app}: already stopped, nothing to do."
            continue
        }
        if ($DryRun) {
            Write-Output "${app}: DryRun, would POST .../stop"
            continue
        }
        $response = Invoke-AzRestMethod -Method POST -Path (Get-AppPath $app '/stop')
        if ($response.StatusCode -notin @(200, 202)) {
            throw "POST ${app}/stop returned HTTP $($response.StatusCode): $($response.Content)"
        }
        Write-Output "${app}: stop accepted (HTTP $($response.StatusCode))."
        $stopping += $app
    } catch {
        Write-Warning "${app}: $($_.Exception.Message)"
        $failed += $app
    }
}

# The stop is a long-running operation; give it a few minutes and report what
# the apps say, so the job log (and its Failed/Completed state) is the truth.
if ($stopping.Count -gt 0) {
    $deadline = (Get-Date).AddMinutes(4)
    $pending = @($stopping)
    # A plain loop, not Where-Object: anything written inside a filter block
    # counts as its output, and a non-empty output is "true".
    while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 20
        $stillPending = @()
        foreach ($app in $pending) {
            try {
                $status = Get-AppRunningStatus $app
                Write-Output "${app}: runningStatus=${status}"
                if ($status -ne 'Stopped') { $stillPending += $app }
            } catch {
                Write-Warning "${app}: $($_.Exception.Message)"
                $stillPending += $app
            }
        }
        $pending = $stillPending
    }
    foreach ($app in $pending) { $failed += "${app} (not Stopped after 4 min)" }
}

if ($failed.Count -gt 0) {
    throw "Hard stop incomplete: $($failed -join ', '). Check the apps in the portal and stop them by hand (az containerapp stop)."
}

if ($DryRun) {
    Write-Output 'DryRun complete: identity, role and API all work.'
} else {
    Write-Output 'Hard stop complete: all four Container Apps are Stopped. Recovery: infra/README.md, "Hard stop".'
}
