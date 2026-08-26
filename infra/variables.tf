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
