variable "subscription_id" {
  description = "Azure subscription that hosts all arXivisual resources."
  type        = string
  default     = "4301c7fd-ffa2-4ad1-bca9-a15ef2d2bd59"
}

# ---------------------------------------------------------------------------
# Secret values. NEVER commit real values; supply them via TF_VAR_* env vars
# or an untracked terraform.tfvars (see README.md and terraform.tfvars.example).
# ---------------------------------------------------------------------------

variable "postgres_admin_password" {
  description = "Password for the 'rabidcheese9' admin login on arxivisual-db. Also injected into the Temporal container app as the 'pg-pwd' secret."
  type        = string
  sensitive   = true
}

variable "database_url" {
  description = "Full Postgres connection string used by the API and worker apps ('database-url' container app secret)."
  type        = string
  sensitive   = true
}

variable "azure_openai_api_key" {
  description = "API key for the arxivisual-openai Cognitive account ('azure-openai-api-key' container app secret)."
  type        = string
  sensitive   = true
}

variable "s3_access_key" {
  description = "Cloudflare R2 access key id ('s3-access-key' container app secret)."
  type        = string
  sensitive   = true
}

variable "s3_secret_key" {
  description = "Cloudflare R2 secret access key ('s3-secret-key' container app secret)."
  type        = string
  sensitive   = true
}

variable "langfuse_public_key" {
  description = "Langfuse public key ('langfuse-public-key' container app secret)."
  type        = string
  sensitive   = true
}

variable "langfuse_secret_key" {
  description = "Langfuse secret key ('langfuse-secret-key' container app secret)."
  type        = string
  sensitive   = true
}

variable "acr_admin_password" {
  description = "Admin password of the ca82c08e2eadacr registry, stored as the worker app's registry pull secret. Retrieve with: az acr credential show -n ca82c08e2eadacr."
  type        = string
  sensitive   = true
}

# The next two are REQUIRED in practice. They keep a "" default only so that a
# missing value reaches the validation below and fails the plan with an
# explanation, instead of an interactive prompt. The secret/env blocks in
# container_apps.tf are dynamic on non-empty, so without the validation an
# apply from a machine that simply lacks these TF_VARs would quietly REMOVE
# them from the live API.

variable "ip_hash_secret" {
  description = "HMAC key behind the pseudonymous client-IP fingerprints in admission logs (IP_HASH_SECRET). Set on the live API app; must be supplied on every plan/apply."
  type        = string
  sensitive   = true
  default     = ""

  validation {
    condition     = trimspace(var.ip_hash_secret) != ""
    error_message = "The ip_hash_secret variable is empty. It is set on the live arxivisual-api app, and an apply without it would remove IP_HASH_SECRET: the client-IP fingerprints in the admission logs would silently fall back to the public default key in the open-source code, i.e. become reversible by lookup. Supply the live value (TF_VAR_ip_hash_secret or terraform.tfvars)."
  }
}

variable "turnstile_secret_key" {
  description = "Cloudflare Turnstile secret for POST /api/process human verification (TURNSTILE_SECRET_KEY). Set on the live API app; must be supplied on every plan/apply. The backend SKIPS verification when the secret is absent."
  type        = string
  sensitive   = true
  default     = ""

  validation {
    condition     = trimspace(var.turnstile_secret_key) != ""
    error_message = "The turnstile_secret_key variable is empty. It is set on the live arxivisual-api app, and an apply without it would remove TURNSTILE_SECRET_KEY: the backend skips Turnstile verification when the secret is unset, so proof-of-humanity on POST /api/process would silently turn off. Supply the live value (TF_VAR_turnstile_secret_key or terraform.tfvars)."
  }
}

variable "posthog_api_key" {
  description = "PostHog project token for server-side product events (POSTHOG_API_KEY on the API and worker apps, 'posthog-api-key' secret). Empty = analytics off; the backend is a no-op without it."
  type        = string
  sensitive   = true
  default     = ""
}

variable "posthog_host" {
  description = "PostHog ingestion host set as POSTHOG_HOST alongside the token (US cloud by default; EU is https://eu.i.posthog.com). Only materialized when posthog_api_key is set."
  type        = string
  default     = "https://us.i.posthog.com"
}

# ---------------------------------------------------------------------------
# Alerting (alerts.tf) and budget notifications (budgets.tf).
# ---------------------------------------------------------------------------

variable "contact_email" {
  description = "Address that receives budget notifications (budgets.tf) and every Azure Monitor alert (the arxivisual-alerts action group in alerts.tf)."
  type        = string
  default     = "ajithbon05@gmail.com"
}

variable "alert_postgres_storage_percent" {
  description = "Alert when arxivisual-db storage use (storage_percent, hourly average) exceeds this. Storage auto-grow is off, and a full disk puts the server in read-only mode."
  type        = number
  default     = 80
}

variable "alert_restart_count" {
  description = "Alert when the container restarts of one backend app (RestartCount, summed over 15 minutes) exceed this, i.e. a crash loop rather than a single restart."
  type        = number
  default     = 3
}

variable "alert_temporal_fallback_count" {
  description = "Alert when more than this many 'Temporal unavailable' lines (API fell back to the in-process pipeline) are logged in 15 minutes. 0 = any fallback; they ran at 2-11 a day in early Sept 2026 with nobody noticing."
  type        = number
  default     = 0
}

variable "alert_api_5xx_count" {
  description = "Alert when the estimated number of API 5xx responses in 15 minutes exceeds this. Estimated = sum(ItemCount) over AppRequests, which undoes the 20% trace sampling (one sampled row counts as 5), so the value moves in steps of 5. Baseline is zero: the only window with any 5xx in the first 8 days of data was the 2026-09-14 Postgres restart (115)."
  type        = number
  default     = 5
}

variable "alert_worker_error_count" {
  description = "Alert when arxivisual-worker logs more than this many 'Traceback' / 'Pipeline failed' lines in 15 minutes. Tracebacks are routine here (LLM-written Manim code failing a render is part of the loop): over 14 days in Sept 2026 the 15-minute count had p50 4, p90 10, p99 20, max 24, so the default sits just above everything seen."
  type        = number
  default     = 30
}

variable "web_image_tag" {
  description = "Tag of the arxivisual-web image the frontend Container App is created (or replaced) with. Every deploy-frontend.yml run tags its build both gh-<sha> and latest, so the default always names an existing image once the first build has run; the image is ignored by Terraform after creation (see infra/frontend.tf)."
  type        = string
  default     = "latest"
}

variable "web_custom_domains_enabled" {
  description = "Bind arxivisual.org + www.arxivisual.org to the frontend app with managed certificates. Leave false until the Porkbun records from output web_dns_records resolve (see docs/DEPLOY.md); every custom-domain step fails without them."
  type        = bool
  default     = false
}
