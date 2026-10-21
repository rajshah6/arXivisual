# arXivisual Infrastructure (Terraform)

Terraform codification of the **live, production** arXivisual Azure
infrastructure. The original estate was created by hand (az CLI / portal /
GitHub Actions) and adopted into Terraform via `import` blocks on 2026-08-26;
new resources (e.g. the frontend in `frontend.tf`) are created by Terraform
directly. Infra changes go through `plan`/`apply` here, not ad-hoc `az`.

> **WARNING: `terraform apply` touches production.** The Container Apps serve
> arxivisual.org right now. Always run `terraform plan` first, read every diff,
> and only apply when the plan contains nothing beyond the change you intended
> (the estate is fully adopted; a clean plan is "No changes", and unexpected
> diffs are drift from ad-hoc `az` commands — see "Drift" below).

## What this manages

| File | Resources |
|---|---|
| `main.tf` | Resource group `arxivisual-rg` (eastus2) |
| `registry.tf` | ACR `ca82c08e2eadacr` (Basic, admin enabled) + AcrPull role for the API app's system identity |
| `openai.tf` | Azure OpenAI account `arxivisual-openai` + deployments `gpt-5-mini` (2025-08-07, GlobalStandard 250; generation, visual QA and repair; retires 2027-02-09), `gpt-4o-mini-tts` (2025-12-15, GlobalStandard 50), `gpt-6-luna` (2026-09-22, GlobalStandard 250, `NoAutoUpgrade`; gpt-5-mini's successor at ~1/4 of its output price, not referenced by any app until the worker is switched after an eval smoke test; **retires 2028-03-11**, migrate around 2028-01). `gpt-5.6-sol` was removed on 2026-10-08 (unused since 2026-09-07, 10x gpt-5-mini's output price) |
| `database.tf` | Postgres flexible server `arxivisual-db` (**westus3**, B1ms, PG16, 32GB, custom maintenance window Sunday 21:00 UTC); databases `arxiviz`, `temporal`, `temporal_visibility`; `azure.extensions=BTREE_GIN`; allow-Azure-services firewall rule |
| `container_apps.tf` | Log Analytics workspace, managed environment `arxivisual-api-env`, and the three backend apps: `arxivisual-api` (external HTTP :8000, 2 vCPU / 4 Gi, 1–2 replicas), `arxivisual-temporal` (internal HTTP/2 → :7233, 0.5 vCPU / 1 Gi, down from 1.0 / 2 Gi in the 2026-10 cost review; exactly 1 replica, see "Temporal server pin"), `arxivisual-worker` (no ingress, 2 vCPU / 4 Gi, 1–3 replicas on a KEDA Postgres rule; keep it at min 1: at min 0 every running replica bills at the active rate, so scale-to-zero would add ~CA$22/mo, a replay estimate with a range of CA$10–41, 2026-10-08) |
| `insights.tf` | Application Insights `arxivisual-insights` (workspace-based, on the Log Analytics workspace above, type `web`, default retention, 1 GB/day cap). Its connection string is injected into `arxivisual-api` and `arxivisual-worker` as the `appinsights-connection-string` secret → `APPLICATIONINSIGHTS_CONNECTION_STRING`, with `OTEL_TRACES_SAMPLER=microsoft.fixed_percentage` + `OTEL_TRACES_SAMPLER_ARG=0.2` (20% of traces) and `OTEL_SERVICE_NAME` (the cloud role name: `arxivisual-api` / `arxivisual-worker`). Output `application_insights_app_id` |
| `alerts.tf` | Action group `arxivisual-alerts` (email to `contact_email`), metric alerts on `arxivisual-db` and the three backend apps, three 15-minute log alerts on the workspace. See "Alerts" |
| `frontend.tf` | The Next.js frontend `arxivisual-web` (external HTTP :3000, 0.25 vCPU / 0.5 Gi, 0–3 replicas until `web_custom_domains_enabled` is set at the DNS cut-over, then 1–3, `/healthz` probes), its user-assigned identity + AcrPull role, and the `arxivisual.org` / `www.arxivisual.org` custom domains with managed certificates |
| `budgets.tf` | Subscription budget `arxivisual-monthly` (CA$575 = the monthly pace at which the Azure credit lasts to 2028-07-29, recompute quarterly; forecast-100% / actual-100% / actual-150% alerts; counts cost before credits and only emails, plus an actual-`hard_stop_threshold_percent` notification that calls the hard stop once `hard_stop_enabled` is set), cost anomaly alert `arxivisual-cost-anomaly` (daily, free, ~2-day lag; detection only runs once the subscription is onboarded by opening a Cost Analysis smart view on it, so do that once after the first apply and check the rule under Cost alerts > Alert rules; **expires a year after each apply that writes it**, renew by bumping the date in its `message`), and billing-account budget `MonthlyReset` ($5) via **azapi** (azurerm has no billing-account budget resource); notifications go to `contact_email` |
| `hardstop.tf` | **Off until `hard_stop_enabled = true`.** Automation account `arxivisual-automation` (Basic, system identity), custom role `arxivisual-hard-stop` on the RG (read + stop on Container Apps, no `listSecrets`), runtime environment `arxivisual-ps76` (PowerShell 7.6, Az 15.1.0), runbook `arxivisual-hard-stop` (`runbooks/hard-stop.ps1`), its webhook, and action group `arxivisual-hard-stop` that the budget's hard-stop notification calls to **stop the four Container Apps**. See "Hard stop" |
| `github_oidc.tf` | Entra app `arxivisual-github-deploy`, its service principal, the GitHub OIDC federated credential (`repo:rajshah6/arXivisual:ref:refs/heads/main`), and its Contributor role on the RG |
| `state.tf` | The `arxivisualtfstate` storage account + `tfstate` container (the backend manages state *in* it and Terraform also *manages* it), with blob versioning and 14-day soft delete. See "State protection" |

Not managed here: Cloudflare R2 (object storage), Cloudflare Turnstile, Langfuse, PostHog (only its project token is passed through, see Secrets), and DNS (Porkbun — the records `frontend.tf` needs are listed in [docs/DEPLOY.md](../docs/DEPLOY.md)).

## Bootstrap history

The state storage account `arxivisualtfstate` and its `tfstate` container were
created manually with the az CLI before the first `terraform init`
(chicken-and-egg: the backend must exist before Terraform can run). They are
also imported and managed by `state.tf`, so drift on them is visible like
everything else.

## Backend / auth

State lives in `azurerm` backend
`arxivisual-rg/arxivisualtfstate/tfstate/arxivisual.tfstate`.

`use_azuread_auth = true` was attempted and **fails** with
`AuthorizationPermissionMismatch`: the signed-in identity is subscription
Owner, which has no blob *data-plane* role. The backend therefore uses its
default flow - it lists the storage account keys via ARM (allowed for Owner)
and authenticates to blob storage with the shared key. To move to AAD auth
later:

```sh
az role assignment create \
  --assignee <your-object-id> \
  --role "Storage Blob Data Contributor" \
  --scope "$(az storage account show -n arxivisualtfstate -g arxivisual-rg --query id -o tsv)"
# then add `use_azuread_auth = true` back to the backend block in versions.tf
```

Provider auth is Azure CLI (`az login`) for azurerm, azuread, and azapi.

## Usage

```sh
cd infra
terraform init                       # backend + providers
terraform validate
terraform plan                       # review! expect only the change you intended
terraform apply                      # ONLY after the plan is fully understood
```

Use the pinned Terraform version from `.terraform.lock.hcl`'s era (built and
verified with Terraform 1.15.x, azurerm 4.81, azuread 3.9, azapi 2.12). Commit
`.terraform.lock.hcl`; never commit `.terraform/`, state files, or
`terraform.tfvars`.

### Applying

**Apply only from an up-to-date `main`**, and rebase any other branch before
planning from it. A branch cut before a resource was added or removed still
declares the old set: on 2026-10-08 every open branch still had `gpt-5.6-sol`
and no `gpt-6-luna`, so applying from one would destroy `gpt-6-luna` and undo
the Temporal, web and budget changes made with it.

**Know which apps a plan rolls.** Any change under a container app's
`template` (env, cpu/memory, scale) starts a new revision, and none of them
rolls for free:

- `arxivisual-worker` drains on SIGTERM (`temporal_app/worker.py`, up to
  9 min inside a 600 s `termination_grace_period_seconds`) once the image
  that carries that change is live; before it, a roll killed in-flight
  activities. Even with the drain, a render longer than the grace period is
  lost and re-dispatched after its 2-minute heartbeat timeout, and a repair
  is simply lost (`_NO_RETRY` in `backend/temporal_app/workflows.py`).
- `arxivisual-api` drops any paper running on the in-process fallback
  (`backend/api/routes.py`, "does not survive restarts").
- `arxivisual-temporal` sends papers submitted during its handover to that
  fallback.

So never roll Temporal in the same apply as the api or worker, and apply only
when no paper is in flight, ideally in the 22:00-23:00 UTC window (quiet, not
empty: on 2026-10-08 there were calls at 22:09Z). The jobs table and Temporal
are reachable only from inside Azure, so "no queued or processing job, no
running workflow" is checked from outside with all three of these, over the
last 15 minutes:

1. No `AzureOpenAIRequests` on any deployment (generation, the judges and
   TTS all call it).
2. `arxivisual-worker` CPU at idle: `UsageNanoCores` maximum under ~10,000,000
   (10 millicores). An idle replica sits near 0.3 millicores and a Manim
   render uses hundreds, so this catches a long render between TTS calls,
   which check 1 alone misses.
3. No paper with `"status": "processing"` in `GET /api/papers`. This alone is
   not enough: a brand-new paper has no row until ingest finishes, and a
   re-run of a ready paper still lists as `ready`.

```sh
az monitor metrics list --metric AzureOpenAIRequests --interval 5m --aggregation Total -o table \
  --resource "$(az cognitiveservices account show -n arxivisual-openai -g arxivisual-rg --query id -o tsv)"
az monitor metrics list --metric UsageNanoCores --interval 5m --aggregation Maximum -o table \
  --resource "$(az containerapp show -n arxivisual-worker -g arxivisual-rg --query id -o tsv)"
curl -s https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io/api/papers \
  | jq '[.papers[] | select(.status == "processing")] | length'
```

When one plan rolls Temporal together with the api or worker (the first apply
of the 2026-10 cost changes did, if `OTEL_SERVICE_NAME` had not been applied
before it), split it: `terraform apply -target=azurerm_container_app.api
-target=azurerm_container_app.worker` first, then a normal plan and apply for
the rest once the check above is quiet again.

## Secrets

No secret value exists anywhere in this directory. Every secret-bearing
attribute reads a `sensitive = true` variable (see `variables.tf`):

`postgres_admin_password`, `database_url`, `azure_openai_api_key`,
`s3_access_key`, `s3_secret_key`, `langfuse_public_key`,
`langfuse_secret_key`, `acr_admin_password`, `turnstile_secret_key` (Cloudflare
Turnstile secret) and `ip_hash_secret` (the HMAC key behind the IP fingerprints
in admission logs).

The last two are **required, and the plan fails without them** (validation
blocks in `variables.tf`). Their secret/env blocks in `container_apps.tf` are
dynamic on non-empty (the Container Apps API rejects empty secrets), so an
apply from a machine that simply lacked the two `TF_VAR_*`s would otherwise
have *removed* them from the live API without a word — and the backend **skips
Turnstile verification when the secret is unset** (proof-of-humanity off) and
falls back to a public default key for the IP fingerprints. If you ever mean
to turn Turnstile off, delete the validation in the same change so it is a
reviewed decision.

`posthog_api_key` stays optional (empty = no `POSTHOG_API_KEY` /
`POSTHOG_HOST` env on either app, and the backend emits no product events),
with `posthog_host` (default US cloud) beside it. It is set in production, so
leaving it empty still plans the removal of both env vars — read the plan.

`database_url` must use asyncpg's `?ssl=require`. libpq's `?sslmode=require`
crashes the API and worker at startup (only the worker's KEDA scaler secret,
built in `container_apps.tf`, uses `sslmode`).

The Application Insights connection string is **not** a variable: it is read
off `azurerm_application_insights.main` and written to the API and worker apps
as the `appinsights-connection-string` secret. That wiring (the component, the
secret, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `OTEL_TRACES_SAMPLER`,
`OTEL_TRACES_SAMPLER_ARG`, `OTEL_LOGS_EXPORTER`) and the PostHog env were
applied on 2026-09-10; nothing from `insights.tf` is pending. New env vars are
always appended as the **last** `env` block of their container (after the
dynamic `POSTHOG_*` blocks): the provider diffs `env` by position, so an
insert in the middle shows every later block as changed. Leave the connection
string out of any `az containerapp update` — the next apply would re-submit it
anyway.

The only long-standing part of this directory that has never been applied is
phase 2 of the frontend: the `arxivisual.org` / `www` custom domains, gated by
`web_custom_domains_enabled` (see "Frontend bootstrap").

`web_image_tag` (default `latest`) names the `arxivisual-web` image the
frontend app is created or replaced with. Every deploy-frontend run tags its
build `gh-<sha>` and `latest`, so the default always exists once the first
build has run (`gh workflow run deploy-frontend.yml -f roll=false` on `main`);
after creation Terraform ignores the image. Never prune the `latest` tag.

Supply them either as environment variables:

```sh
export TF_VAR_postgres_admin_password='...'
export TF_VAR_database_url='...'
# ... etc
```

or in an untracked `terraform.tfvars` copied from
`terraform.tfvars.example` (git-ignored - **never commit it**).

For `plan` the actual values don't matter (Terraform can't diff them against
Azure anyway); for the first `apply` they MUST be the real live values,
because that apply re-submits every container app secret and the Postgres
admin password. In particular `postgres_admin_password` must be the *current*
DB password or the first apply will change it out from under the running apps.

## Import-block lifecycle

The original estate was adopted with one `import` block per resource
(`imports.tf`); that first apply has happened and the file was deleted. New
resources (e.g. `frontend.tf`) are created by Terraform directly.

## Frontend bootstrap (two applies)

`frontend.tf` is created in two steps because Terraform cannot see Porkbun.
Step 1 has been applied (`arxivisual-web` is live on its
`azurecontainerapps.io` FQDN) and is kept here for a rebuild; step 2, the
custom domains, is still pending and DNS still points at Vercel:

1. Build the image on `main` (`gh workflow run deploy-frontend.yml -f roll=false`),
   then `terraform apply` with the default `web_image_tag = "latest"` (or a
   `gh-<sha>`) and the default `web_custom_domains_enabled = false`. Expect:
   `+ azurerm_user_assigned_identity.web`, `+ azurerm_role_assignment.web_acr_pull`,
   `+ time_sleep.web_acr_pull` (90 s RBAC propagation wait), `+ azurerm_container_app.web`, and
   two new env vars on `arxivisual-api` (`CORS_EXTRA_ORIGINS`,
   `TURNSTILE_ALLOWED_HOSTNAMES`). Anything else in the plan is drift from
   `az containerapp update --set-env-vars` runs on the API app — read it
   before applying. If the app create fails with an ACR `UNAUTHORIZED` image
   pull, RBAC had not propagated yet: wait a few minutes and re-run apply.
2. Create the four records from `terraform output web_dns_records`, wait for
   them to resolve, apply with `web_custom_domains_enabled = true`. Expect:
   `+ azurerm_container_app_custom_domain.web["apex"|"www"]`,
   `+ azurerm_container_app_environment_managed_certificate.web[...]`,
   `+ azapi_update_resource.web_domain_binding[0]`. The certificate step waits
   for issuance (minutes; 30-minute timeout).

The cut-over order, DNS rules and verification live in
[docs/DEPLOY.md](../docs/DEPLOY.md).

## Drift and the (historical) first-apply diffs

The estate was adopted on 2026-08-26 (`26 imported, 0 added, 4 changed, 0
destroyed`; the post-apply plan was "No changes"). The pre-apply adoption plan
that used to be checked in as `PLAN_SNAPSHOT.txt` was deleted in Sept 2026: it
described a state that no longer exists and read like a current expectation
(it is in git history if you need it). Since the adoption Terraform owns
everything here, so the expected plan is "No changes" plus whatever you are
deliberately changing — last confirmed against production on 2026-09-18.

Known sources of drift: env vars set on the API app with `az containerapp
update --set-env-vars` (admission-control caps, secrets) that were never
mirrored into `container_apps.tf`. A plan will offer to revert them to the
Terraform values — reconcile the `.tf` file first, then apply. The same
benign diffs the first apply showed can reappear after manual edits: secret
blocks re-submitted (the API never returns secret values), probe timeouts and
`success_count_threshold` defaults made explicit, and `administrator_password`
on `arxivisual-db` (ARM never returns it; supply the *current* password or the
apply changes it out from under the running apps).

Anything on a plan beyond this list (or beyond an intentional change) should
be treated as a red flag - stop and investigate before applying.

## Alerts

`alerts.tf` is the only alerting there is (before it, a Postgres restart, a
steady trickle of silent Temporal fallbacks and 208 probe failures all went
unnoticed). Everything mails `contact_email` through the `arxivisual-alerts`
action group; thresholds are variables with defaults taken from the 14 days of
data before 2026-09-18.

| Rule | Signal | Fires when |
|---|---|---|
| `arxivisual-db-storage` | metric `storage_percent` | hourly average > `alert_postgres_storage_percent` (80). 32 GB, auto-grow off; a full disk makes the server read-only |
| `arxivisual-db-down` | metric `is_db_alive` | the server reported itself down for a full minute |
| `<app>-no-replicas` ×3 | metric `Replicas` | 5-minute average < 1 on `arxivisual-api` / `-temporal` / `-worker` (all run `min_replicas = 1`) |
| `<app>-restarts` ×3 | metric `RestartCount` | more than `alert_restart_count` (3) container restarts in 15 minutes, i.e. a crash loop |
| `arxivisual-temporal-fallback` | log, `ContainerAppConsoleLogs_CL` | more than `alert_temporal_fallback_count` (0) "Temporal unavailable" lines in 15 min: the API ran a paper on the legacy in-process path |
| `arxivisual-api-5xx` | log, `AppRequests` | estimated 5xx responses in 15 min > `alert_api_5xx_count` (5). `sum(ItemCount)` undoes the 20% trace sampling, so the value moves in steps of 5; the normal rate is zero |
| `arxivisual-worker-errors` | log, `ContainerAppConsoleLogs_CL` | more than `alert_worker_error_count` (30) `Traceback` / `Pipeline failed` lines from the worker in 15 min. Tracebacks are routine there (p50 4, p99 20, max 24 per window), so this only trips on something systemic |

Cost: log alerts are billed by evaluation frequency (15 minutes is ~0.50
USD/month per rule, so ~1.50); metric alerts per monitored time series (eight
here, cents each). There are deliberately no Application Insights availability
web tests (billed per test): outside-in uptime probing is a scheduled GitHub
Actions workflow.

Known gaps, so nobody trusts these further than they go:

- **A quick Postgres restart does not trip `arxivisual-db-down`.** During the
  2026-09-14 07:34Z restart `is_db_alive` did not report 0, it reported
  nothing for a minute, and a static metric alert does not evaluate missing
  data. That incident would have been caught by `arxivisual-api-5xx` and
  `arxivisual-temporal-fallback` instead. The proper signal is a Resource
  Health activity-log alert (free), but `Microsoft.ResourceHealth` is not
  registered on the subscription and `versions.tf` never registers providers:
  `az provider register -n Microsoft.ResourceHealth`, then add an
  `azurerm_monitor_activity_log_alert` on the server.
- `Replicas` is only emitted by active revisions. If an app with no replica
  reports *nothing* rather than 0, `<app>-no-replicas` stays silent; the
  restart and log alerts are the backstop.
- "Pipeline failed" is currently only the job's error text in Postgres; the
  worker does not log it, so today `arxivisual-worker-errors` is driven by
  `Traceback` alone.
- Log alerts need the data to arrive: Container Apps console logs usually land
  within a few minutes, and Azure retries a late evaluation, but these are
  15-minute signals, not pages.
- Expected noise: the monthly Postgres maintenance restart (Sunday 21:00 UTC
  window, `database.tf`) will usually trip `arxivisual-api-5xx` and/or
  `arxivisual-temporal-fallback` once. That is the alerts working.

The first apply makes Azure mail the receiver a "you have been added to an
action group" notice; if it does not arrive, check spam before trusting any of
the above.

## Hard stop

Nothing else here stops spend. The billing profile's spending limit is Off
(`LimitRemoved` since 2026-07-29) with a card on file, every budget
notification is email-only, and the US$10K startup credit runs out around
mid-2027 at the Oct 2026 burn, a year before its 2028-07-29 expiry; after
that the card pays ~CA$1,300/month with no ceiling, and a runaway during the
credit period just burns credit faster (audit 2026-10-21). `hardstop.tf` is
the Learn-documented answer (cost-management-budget-scenario): the
`arxivisual-monthly` budget gets one more **Actual** notification at
`hard_stop_threshold_percent` (default 300% = CA$1,725) whose contact group is
the action group `arxivisual-hard-stop`, whose only receiver is a webhook on
the Automation runbook `arxivisual-hard-stop`, which POSTs the Container Apps
`stop` action on `arxivisual-worker`, `-api`, `-web` and `-temporal`. A
stopped app has no replicas and no scale rule can wake it, so Container Apps
compute ends at once and Foundry Models spend ends because nothing calls the
model. Postgres, ACR, R2, the app definitions and their revisions survive.

Why `stop` and not replicas: the Container Apps scale limits allow a minimum
of 0 but a **maximum of 1**, and at min 0 / max 1 the api wakes on the next
HTTP request and the worker on the next queued job.

**Cost: ~CA$0.** The Automation account is free; Basic-SKU job minutes bill at
US$0.002/min after 500 free minutes per subscription per month, and one run is
2-5 minutes. Action-group runbook receivers and budget notifications are free.

**What the runbook's identity can do:** read the Container Apps and POST
their `stop` action, through the custom role `arxivisual-hard-stop`, and
nothing else. The built-in `Container Apps Contributor` was not used because
its `containerApps/*/action` wildcard includes `listSecrets`, which returns
the apps' secrets in plain text. It cannot `start` anything either: recovery
is a human (below).

### Threshold

300% of CA$575 = CA$1,725 per month of **actual, pre-credit** cost. The
Oct 14-19 2026 burn of CA$1,287/mo is 224%, so a normal month never trips it
(200% would have: that is why the default is not 200), while a 2x runaway
crosses it by ~day 21 and a 10x one by ~day 5. Cost Management evaluates once
a day on data that lands 8-24 h late, so the stop arrives 1-2 days after the
line is crossed: ~CA$90 of overshoot at today's burn, ~CA$900 for a 10x
runaway. Lower `hard_stop_threshold_percent` toward 200 once the cost cuts
land and the new burn is measured; the budget's 100%/150% mails stay as the
early warning.

### Turning it on (Ajith)

1. `az provider register -n Microsoft.Automation` and wait for
   `az provider show -n Microsoft.Automation --query registrationState` to
   say `Registered`. The provider is not registered on this subscription
   (2026-10-21) and `versions.tf` never registers providers, so the apply
   fails without this.
2. Set `hard_stop_enabled = true` (tfvars or `-var`) and plan. The hard stop
   itself is seven adds and one in-place change:
   `+ azurerm_automation_account.hard_stop[0]`,
   `+ azurerm_role_definition.hard_stop[0]`,
   `+ azurerm_role_assignment.hard_stop[0]`,
   `+ azurerm_automation_runtime_environment.hard_stop[0]`,
   `+ azurerm_automation_runbook.hard_stop[0]`,
   `+ azurerm_automation_webhook.hard_stop[0]`,
   `+ azurerm_monitor_action_group.hard_stop[0]` and
   `~ azurerm_consumption_budget_subscription.monthly` (one notification
   added). None of these touches a Container App. **The same plan also
   carries whatever `main` has pending**, and until the 2026-10 cost-cut
   apply has landed that is four `~ azurerm_container_app.<app> will be
   updated in-place` lines, among them the worker's `AZURE_OPENAI_DEPLOYMENT`
   flip to `gpt-6-luna` and the api's 0.5 CPU / 1Gi. A plain `apply` from
   that plan would roll the worker onto luna before `model_smoke` has passed
   on it (the audit's apply sequence requires 5/5 first). So either arm the
   hard stop after that sequence is done, when a plan from `main` shows
   nothing but the lines above, or apply just the hard stop:

   ```sh
   terraform apply -var=hard_stop_enabled=true \
     -target=azurerm_automation_account.hard_stop \
     -target=azurerm_role_definition.hard_stop \
     -target=azurerm_role_assignment.hard_stop \
     -target=azurerm_automation_runtime_environment.hard_stop \
     -target=azurerm_automation_runbook.hard_stop \
     -target=azurerm_automation_webhook.hard_stop \
     -target=azurerm_monitor_action_group.hard_stop \
     -target=azurerm_consumption_budget_subscription.monthly
   ```

   Read the targeted plan before answering `yes`: it must list the eight
   resources above and no `azurerm_container_app`. (The budget target also
   applies that resource's other pending edits, the 575 amount and the
   50%/90% removals from #98; they roll nothing.) If the role assignment
   fails with `RoleDefinitionDoesNotExist`, the new custom role had not
   replicated yet: run the same apply again.
3. Prove it without stopping anything: portal > Automation Accounts >
   `arxivisual-automation` > Runbooks > `arxivisual-hard-stop` > **Start**,
   set `DryRun` = `true`, and read the job output: one
   `runningStatus=Running` line per app and `DryRun complete`. A 403 means the
   role assignment has not propagated yet (minutes) or the account's
   identity is missing; a 4xx on the GET means the API version in
   `runbooks/hard-stop.ps1` needs bumping; a module error on
   `Connect-AzAccount` means the runtime environment's `az` package did not
   load (portal > Runtime Environments > `arxivisual-ps76` > Packages).
   Azure also mails the "you have been added to an action group" notice for
   `arxivisual-hard-stop`.
4. Optional full rehearsal in a quiet window (README "Applying"): start the
   runbook with `DryRun` = `false`, watch the four apps go `Stopped`, then run
   the recovery below. This is the only way to see the whole chain end to end
   short of a real budget trigger, and it costs a few minutes of downtime.

### When it fires

Three signals: the budget's own threshold mail, the action group's mail (the
subject names `arxivisual-hard-stop`), and a job under the Automation account
whose output lists each app's status. arxivisual.org stays up if it is still
on Vercel; otherwise `arxivisual-web` is stopped too and the site is down.
Every in-flight paper dies (`arxivisual-worker` has no graceful shutdown).

### Recovery

Manual, and **not** `terraform apply`: the azurerm provider does not model the
running state, so a plan reads "No changes" after a stop and an apply brings
nothing back. Find the cause first (Cost analysis, Langfuse, the api's
admission logs), fix it, then:

```sh
for app in arxivisual-temporal arxivisual-worker arxivisual-api arxivisual-web; do
  az containerapp start -g arxivisual-rg -n "$app"
done
```

Temporal first so the api and worker reconnect to it on boot. Each app resumes
its current revision with its previous scale settings; the `<app>-no-replicas`
alerts in `alerts.tf` clear once they are back. The threshold has fired for
this budget period, so the restarted estate runs **unguarded until the next
month**; the 150% mail and the anomaly alert are what is left.

### Known gaps

- 1-2 day lag between crossing the line and the stop (budget evaluation).
- Each threshold fires once per period; see "Recovery".
- The webhook URL is a bearer secret held in Terraform state, and `expiry_time`
  (2035-12-31) is `ForceNew`: changing it mints a new URL and rewrites the
  action group in the same apply.
- The budget itself ends 2028-07-31; extending it extends the hard stop.
- `runbooks/hard-stop.ps1` is authored without a local PowerShell to parse it;
  the DryRun in step 3 is its test. Azure publishes it on every apply that
  changes it (the provider pushes the draft and publishes).
- The runtime is PowerShell 7.6 (LTS to 2028-11-14) with Az 15.1.0 pinned in
  the runtime environment `arxivisual-ps76`. Automation retired 7.2 on
  2026-09-30 and 7.4 leaves PowerShell support on 2026-11-10, so when the
  next retirement notice comes the change is `runtime_version` and the `az`
  package version in `hardstop.tf` (a new environment, the runbook re-links
  to it in place, the script is untouched).
- On a PowerShell 7 runbook the webhook payload arrives as a string, not the
  documented `WebhookData` object; the script logs it as delivered, so the
  job output still shows what the budget sent.
- This bounds a runaway; it is not the spending limit. Turning the spending
  limit back on (portal, takes effect at the next billing period) is the
  separate, complementary decision in the audit.

## State protection

`arxivisual.tfstate` in the `arxivisualtfstate` account is the only copy of the
state. `state.tf` turns on **blob versioning** (every state write keeps the
previous version) and **14-day soft delete** for blobs and containers. To roll
back a bad state write: portal → storage account → `tfstate` container →
`arxivisual.tfstate` → *Versions* → make the wanted version the current one,
while no `terraform` process holds the state lease. A deleted blob or
container is restored with *Show deleted blobs/containers* → *Undelete*. Old
versions are small (one state file each) and are not pruned automatically.

## Temporal server pin

`arxivisual-temporal` runs `temporalio/auto-setup:1.23.1.1`. That image is
deprecated upstream (Temporal ships `temporalio/server` plus the admin-tools
image for schema work) and 1.23 is old, but this is a pin, not an oversight:

- Temporal supports upgrading **one minor version at a time** (1.23 → 1.24 →
  1.25 …), and each hop has a **schema step** for both the `temporal` and
  `temporal_visibility` databases (auto-setup runs the schema update on start;
  with the plain server image it is `temporal-sql-tool update-schema`). Never
  jump several minors in one change.
- There is one replica and one history shard, so every image change is a
  Temporal outage for as long as the new revision takes to start; the API
  fails open to the in-process pipeline meanwhile (and
  `arxivisual-temporal-fallback` will fire).
- Only upgrade inside a **drained window**: no `queued`/`processing` rows in
  `processing_jobs`, no running workflows, ideally with a fresh Postgres
  backup. Read the release notes of every minor on the path first.

## ACR housekeeping

`ca82c08e2eadacr` is a **Basic** registry: 10 GiB is *included*, it is not a
cap. Storage beyond it is billed per GiB per day, up to a 40 TiB limit, so the
registry never "fills up" — it just costs more. It stood at ~43 GB on
2026-09-18 (`az acr show-usage -n ca82c08e2eadacr -o table`), because every
deploy pushes a full image and nothing prunes. The untagged-manifest retention
policy is Premium-only, so pruning is manual.

Deleting is sharper than it looks:

- `az acr repository delete --image repo:tag` deletes the **manifest** and
  **every tag pointing at it**, not just that tag. In `arxivisual-web`,
  `latest` and the live `gh-<sha>` tag are the same manifest: deleting either
  deletes both, and Terraform creates/replaces the app from `latest`.
- `az acr repository untag --image repo:tag` removes only the tag and frees
  no space. Use it when a tag must go but its manifest must stay.
- Untagged (dangling) manifests can only be deleted by digest
  (`--image repo@sha256:…`); list them with
  `az acr manifest list-metadata --registry ca82c08e2eadacr --name <repo> --query "[?tags==null]"`.

Tags that must survive any prune — resolve them first, they change with every
deploy:

| Keep | Find it with |
|---|---|
| the live API image and the live worker image (both tags of `arxivisual-api`; they differ whenever the worker has not been rolled, since `deploy-backend.yml` only rolls the API) | `az containerapp show -n arxivisual-api -g arxivisual-rg --query "properties.template.containers[0].image" -o tsv` (same for `arxivisual-worker`) |
| the `local.app_image` tag in `container_apps.tf` (what a Terraform recreate of the api/worker boots) | `grep app_image infra/container_apps.tf` — bump it to the live API tag whenever you prune |
| one rollback tag per app: the image of the revision you would `az containerapp revision activate` | `az containerapp revision list -n <app> -g arxivisual-rg -o table` |
| `arxivisual-web:latest` and the live web `gh-<sha>` tag (one manifest) | `az containerapp show -n arxivisual-web …` as above |

Optional belt and braces: `az acr repository update -n ca82c08e2eadacr --image
arxivisual-api:<tag> --delete-enabled false --write-enabled true` makes a tag
undeletable until it is unlocked again (keep `--write-enabled true` on
`arxivisual-web:latest`, which every frontend deploy re-pushes).

## azapi usage

`MonthlyReset` is a Cost Management budget scoped to the *billing account*
(`Microsoft.Billing/billingAccounts/...`), a scope the azurerm provider cannot
express (`azurerm_consumption_budget_*` covers subscription / resource group /
management group only). It is modeled as
`azapi_resource` (`Microsoft.CostManagement/budgets@2023-11-01`) in
`budgets.tf`. Everything else is plain azurerm/azuread.
