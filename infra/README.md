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
| `openai.tf` | Azure OpenAI account `arxivisual-openai` + deployments `gpt-5-mini` (2025-08-07, GlobalStandard 250; generation, visual QA and repair), `gpt-4o-mini-tts` (2025-12-15, GlobalStandard 50), `gpt-5.6-sol` (2026-07-09, GlobalStandard 250; idle standby, nothing references it) |
| `database.tf` | Postgres flexible server `arxivisual-db` (**westus3**, B1ms, PG16, 32GB, custom maintenance window Sunday 21:00 UTC); databases `arxiviz`, `temporal`, `temporal_visibility`; `azure.extensions=BTREE_GIN`; allow-Azure-services firewall rule |
| `container_apps.tf` | Log Analytics workspace, managed environment `arxivisual-api-env`, and the three backend apps: `arxivisual-api` (external HTTP :8000), `arxivisual-temporal` (internal HTTP/2 → :7233, see "Temporal server pin"), `arxivisual-worker` (no ingress) |
| `insights.tf` | Application Insights `arxivisual-insights` (workspace-based, on the Log Analytics workspace above, type `web`, default retention, 1 GB/day cap). Its connection string is injected into `arxivisual-api` and `arxivisual-worker` as the `appinsights-connection-string` secret → `APPLICATIONINSIGHTS_CONNECTION_STRING`, with `OTEL_TRACES_SAMPLER=microsoft.fixed_percentage` + `OTEL_TRACES_SAMPLER_ARG=0.2` (20% of traces) and `OTEL_SERVICE_NAME` (the cloud role name: `arxivisual-api` / `arxivisual-worker`). Output `application_insights_app_id` |
| `alerts.tf` | Action group `arxivisual-alerts` (email to `contact_email`), metric alerts on `arxivisual-db` and the three backend apps, three 15-minute log alerts on the workspace. See "Alerts" |
| `frontend.tf` | The Next.js frontend `arxivisual-web` (external HTTP :3000, 0.25 vCPU / 0.5 Gi, 1–3 replicas, `/healthz` probes), its user-assigned identity + AcrPull role, and the `arxivisual.org` / `www.arxivisual.org` custom domains with managed certificates |
| `budgets.tf` | Subscription budget `arxivisual-monthly` ($300, 50%/90%/forecast-100% alerts) and billing-account budget `MonthlyReset` ($5) via **azapi** (azurerm has no billing-account budget resource); notifications go to `contact_email` |
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
