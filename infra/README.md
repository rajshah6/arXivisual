# arXivisual Infrastructure (Terraform)

Terraform codification of the **live, production** arXivisual Azure
infrastructure. Everything here was created by hand (az CLI / portal / GitHub
Actions) and is being adopted into Terraform via `import` blocks so that the
infra is reproducible and reviewable.

> **WARNING: `terraform apply` touches production.** The Container Apps serve
> arxivisual.org right now. Always run `terraform plan` first, read every diff,
> and only apply when the plan matches the "Known first-apply diffs" list below
> (plus whatever change you intended).

## What this manages

| File | Resources |
|---|---|
| `main.tf` | Resource group `arxivisual-rg` (eastus2) |
| `registry.tf` | ACR `ca82c08e2eadacr` (Basic, admin enabled) + AcrPull role for the API app's system identity |
| `openai.tf` | Azure OpenAI account `arxivisual-openai` + deployments `gpt-5-mini` (2025-08-07, GlobalStandard 250), `gpt-4o-mini-tts` (2025-12-15, GlobalStandard 50), `gpt-5.6-sol` (2026-07-09, GlobalStandard 250) |
| `database.tf` | Postgres flexible server `arxivisual-db` (**westus3**, B1ms, PG16, 32GB); databases `arxiviz`, `temporal`, `temporal_visibility`; `azure.extensions=BTREE_GIN`; allow-Azure-services firewall rule |
| `container_apps.tf` | Log Analytics workspace, managed environment `arxivisual-api-env`, and the three apps: `arxivisual-api` (external HTTP :8000), `arxivisual-temporal` (internal TCP :7233), `arxivisual-worker` (no ingress) |
| `budgets.tf` | Subscription budget `arxivisual-monthly` ($300, 50%/90%/forecast-100% alerts) and billing-account budget `MonthlyReset` ($5) via **azapi** (azurerm has no billing-account budget resource) |
| `github_oidc.tf` | Entra app `arxivisual-github-deploy`, its service principal, the GitHub OIDC federated credential (`repo:rajshah6/arXivisual:ref:refs/heads/main`), and its Contributor role on the RG |
| `state.tf` | The `arxivisualtfstate` storage account + `tfstate` container (the backend manages state *in* it and Terraform also *manages* it) |
| `imports.tf` | One `import` block per resource above |

Not managed here: Vercel (frontend), Cloudflare R2 (object storage), Langfuse.

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
terraform plan                       # review! see "Known first-apply diffs"
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
`langfuse_secret_key`, `acr_admin_password`.

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

`imports.tf` maps every existing Azure resource ID to its Terraform address.
`terraform plan` shows them as "N to import"; the first successful
`terraform apply` records them in state. After that first apply the import
blocks are inert and `imports.tf` can be deleted in a follow-up commit.

## Known first-apply diffs

The verified plan is: **26 to import, 0 to add, 5 to change, 0 to destroy**
(see `PLAN_SNAPSHOT.txt`). No replacements, no destroys. The five in-place
updates are benign:

| Resource | Diff | Why it's benign |
|---|---|---|
| all 3 container apps | `- secret` / `+ secret` blocks | The ACA API never returns secret values, so imported state has none; first apply rewrites the identical values from the vars. |
| `arxivisual-temporal` | probe `timeout 0 -> 1`, `success_count_threshold 0 -> 1` | Platform probe defaults made explicit; ingress is declared as the live http2 transport (gRPC via envoy TLS on :443). |
| `arxivisual-temporal` | probe `timeout 0 -> 1`, readiness `success_count_threshold 0 -> 1` | The live probes omit these fields; 1/1 are the platform defaults already in effect, now written explicitly. |
| `workspace-arxivisualrg2OvU` | `+ local_authentication_enabled = true` | API does not return the field; `true` is the current live behavior (local auth was never disabled). |
| `arxivisual-db` | `+ administrator_password` | ARM never returns the password; the first apply re-submits `var.postgres_admin_password`. Supply the current live password. |

Anything on a plan beyond this list (or beyond an intentional change) should
be treated as a red flag - stop and investigate before applying.

## azapi usage

`MonthlyReset` is a Cost Management budget scoped to the *billing account*
(`Microsoft.Billing/billingAccounts/...`), a scope the azurerm provider cannot
express (`azurerm_consumption_budget_*` covers subscription / resource group /
management group only). It is modeled as
`azapi_resource` (`Microsoft.CostManagement/budgets@2023-11-01`) in
`budgets.tf`. Everything else is plain azurerm/azuread.
