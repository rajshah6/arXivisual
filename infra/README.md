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
| `openai.tf` | Azure OpenAI account `arxivisual-openai` + deployments `gpt-5-mini` (2025-08-07, GlobalStandard 250), `gpt-4o-mini-tts` (2025-12-15, GlobalStandard 50), `gpt-5.6-sol` (2026-07-09, GlobalStandard 250) |
| `database.tf` | Postgres flexible server `arxivisual-db` (**westus3**, B1ms, PG16, 32GB); databases `arxiviz`, `temporal`, `temporal_visibility`; `azure.extensions=BTREE_GIN`; allow-Azure-services firewall rule |
| `container_apps.tf` | Log Analytics workspace, managed environment `arxivisual-api-env`, and the three backend apps: `arxivisual-api` (external HTTP :8000), `arxivisual-temporal` (internal TCP :7233), `arxivisual-worker` (no ingress) |
| `frontend.tf` | The Next.js frontend `arxivisual-web` (external HTTP :3000, 0.25 vCPU / 0.5 Gi, 1–3 replicas, `/healthz` probes), its user-assigned identity + AcrPull role, and the `arxivisual.org` / `www.arxivisual.org` custom domains with managed certificates |
| `budgets.tf` | Subscription budget `arxivisual-monthly` ($300, 50%/90%/forecast-100% alerts) and billing-account budget `MonthlyReset` ($5) via **azapi** (azurerm has no billing-account budget resource) |
| `github_oidc.tf` | Entra app `arxivisual-github-deploy`, its service principal, the GitHub OIDC federated credential (`repo:rajshah6/arXivisual:ref:refs/heads/main`), and its Contributor role on the RG |
| `state.tf` | The `arxivisualtfstate` storage account + `tfstate` container (the backend manages state *in* it and Terraform also *manages* it) |

Not managed here: Cloudflare R2 (object storage), Cloudflare Turnstile, Langfuse, and DNS (Porkbun — the records `frontend.tf` needs are listed in [docs/DEPLOY.md](../docs/DEPLOY.md)).

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
`langfuse_secret_key`, `acr_admin_password`, and optionally `turnstile_secret_key` (empty = Turnstile off) and `ip_hash_secret`
(the HMAC key behind the IP fingerprints in admission logs; empty = `IP_HASH_SECRET` not set). Both are
set on the live API app; leave either empty here and an apply removes it.

One non-secret variable has no default: `web_image_tag`, the `arxivisual-web`
image tag the frontend app is *created* with. Build it first (`gh workflow run
deploy-frontend.yml -f roll=false` on `main`) and pass `gh-<sha>`; afterwards
the deploy workflow rolls images and Terraform ignores the attribute.

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

`frontend.tf` is created in two steps because Terraform cannot see Porkbun:

1. Build the image on `main` (`gh workflow run deploy-frontend.yml -f roll=false`),
   then `terraform apply` with `web_image_tag = "gh-<sha>"` and the default
   `web_custom_domains_enabled = false`. Expect: `+ azurerm_user_assigned_identity.web`,
   `+ azurerm_role_assignment.web_acr_pull`, `+ azurerm_container_app.web`, and
   two new env vars on `arxivisual-api` (`CORS_EXTRA_ORIGINS`,
   `TURNSTILE_ALLOWED_HOSTNAMES`). Anything else in the plan is drift from
   `az containerapp update --set-env-vars` runs on the API app — read it
   before applying.
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
destroyed`; the post-apply plan was "No changes", see `PLAN_SNAPSHOT.txt`).
Since then Terraform owns everything here, so the expected plan is "No
changes" plus whatever you are deliberately changing.

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

## azapi usage

`MonthlyReset` is a Cost Management budget scoped to the *billing account*
(`Microsoft.Billing/billingAccounts/...`), a scope the azurerm provider cannot
express (`azurerm_consumption_budget_*` covers subscription / resource group /
management group only). It is modeled as
`azapi_resource` (`Microsoft.CostManagement/budgets@2023-11-01`) in
`budgets.tf`. Everything else is plain azurerm/azuread.
