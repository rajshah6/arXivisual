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

variable "ip_hash_secret" {
  description = "HMAC key behind the pseudonymous client-IP fingerprints in admission logs (IP_HASH_SECRET). Set on the live API app; keep it here so an apply does not remove it."
  type        = string
  sensitive   = true
  default     = ""
}

variable "turnstile_secret_key" {
  description = "Cloudflare Turnstile secret for POST /api/process human verification. Empty = verification disabled."
  type        = string
  sensitive   = true
  default     = ""
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
