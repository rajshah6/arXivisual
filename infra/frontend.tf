# ---------------------------------------------------------------------------
# arxivisual-web: the Next.js frontend (SSR) as an external Container App on
# port 3000, replacing Vercel. Image built by .github/workflows/deploy-frontend.yml
# (frontend/Dockerfile) into the shared registry.
#
# It pulls with a USER-assigned identity, unlike the API app's system identity:
# a system identity only exists once the app exists, so a first apply cannot
# grant AcrPull before the app tries to pull. A user-assigned identity is
# created and granted first. Azure RBAC is eventually consistent (Microsoft:
# up to a few minutes), and Container Apps validates the pull during create,
# so a short wait sits between the grant and the app; if a first apply still
# fails with an ACR UNAUTHORIZED pull, wait and re-run apply.
#
# The app must stay SECRET-FREE: the custom-domain binding below goes through
# azapi_update_resource, which PUTs the GET body back, and the ACA API drops
# secret values absent from a PUT. Server-side secrets (if ever needed) go in
# Key Vault references, or the binding moves to `az containerapp hostname bind`.
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "web" {
  name                = "arxivisual-web-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

resource "azurerm_role_assignment" "web_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.web.principal_id
  # A managed identity is a service principal; saying so skips the AAD lookup
  # that races the brand-new identity's replication.
  principal_type = "ServicePrincipal"
}

# RBAC propagation window between the AcrPull grant and the first image pull.
resource "time_sleep" "web_acr_pull" {
  create_duration = "90s"
  depends_on      = [azurerm_role_assignment.web_acr_pull]
}

locals {
  # Only consulted when Terraform CREATES (or replaces) the app; afterwards
  # the deploy workflow rolls gh-<sha> tags and Terraform ignores the image,
  # exactly like the API app. The workflow also tags every build `latest`, so
  # the default always names an existing image (never prune that tag).
  web_image = "${azurerm_container_registry.main.login_server}/arxivisual-web:${var.web_image_tag}"
}

resource "azurerm_container_app" "web" {
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  name                         = "arxivisual-web"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web.id]
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"
    # http -> https redirect stays on (the default); Next.js serves plain HTTP
    # behind the environment's TLS-terminating ingress.
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.web.id
  }

  template {
    # One warm replica: the standalone server boots in well under a second,
    # but scale-to-zero would put a ~10-15 s image pull + cold start in front
    # of the first visit after idle. A quarter vCPU / 0.5 Gi (the smallest
    # Consumption pair) is plenty — the app serves HTML/JS/CSS and a cached
    # per-paper metadata fetch; videos come straight from R2. Marginal cost
    # at eastus2 list prices: ~$6/mo idle to ~$20/mo fully active (the
    # subscription's free grant is already consumed by the backend apps).
    min_replicas = 1
    max_replicas = 3

    http_scale_rule {
      name                = "http"
      concurrent_requests = "50"
    }

    container {
      name   = "arxivisual-web"
      image  = local.web_image
      cpu    = 0.25
      memory = "0.5Gi"

      # The image already sets PORT=3000/NODE_ENV/HOSTNAME=0.0.0.0, but the
      # kubelet injects HOSTNAME=<pod name> at runtime, and Next's standalone
      # server binds to $HOSTNAME — pin it here so the listener is 0.0.0.0.
      # NEXT_PUBLIC_* are build-time inputs and would be ignored here.
      env {
        name  = "HOSTNAME"
        value = "0.0.0.0"
      }

      # All three probes hit the app's own GET /healthz (any 2xx/3xx = ok).
      startup_probe {
        transport               = "HTTP"
        path                    = "/healthz"
        port                    = 3000
        initial_delay           = 2
        interval_seconds        = 3
        timeout                 = 3
        failure_count_threshold = 20 # ~60 s to boot; the server is ready in <1 s
      }

      liveness_probe {
        transport               = "HTTP"
        path                    = "/healthz"
        port                    = 3000
        initial_delay           = 5
        interval_seconds        = 15
        timeout                 = 3
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        path                    = "/healthz"
        port                    = 3000
        initial_delay           = 2
        interval_seconds        = 10
        timeout                 = 3
        failure_count_threshold = 3
        # Platform default is 1; the provider docs say 3 — write it explicitly
        # so the first apply does not show a perpetual diff (temporal app too).
        success_count_threshold = 1
      }
    }
  }

  depends_on = [time_sleep.web_acr_pull]
}

# ---------------------------------------------------------------------------
# Custom domains: arxivisual.org (apex) + www.arxivisual.org with FREE managed
# (DigiCert) certificates. Three phases, mirroring `az containerapp hostname
# add` -> `az containerapp env certificate create` -> `hostname bind`:
#   1. register the hostnames on the app, unbound (validates the asuid TXTs)
#   2. issue managed certificates (apex: A record, HTTP validation;
#      www: direct CNAME, CNAME validation)
#   3. bind SniEnabled + certificateId through azapi — azurerm exposes the
#      managed-certificate id on the custom-domain resource as read-only, so
#      it cannot perform this step itself.
#
# Gated behind var.web_custom_domains_enabled because Terraform cannot see
# Porkbun: every phase fails (the certificate one after a 30-minute wait) if
# the DNS records do not resolve yet. Bootstrap = apply with the flag off,
# create the records from output "web_dns_records", wait for `dig` to agree,
# then apply with the flag on. See docs/DEPLOY.md.
# ---------------------------------------------------------------------------

locals {
  web_domains = var.web_custom_domains_enabled ? {
    apex = { host = "arxivisual.org", validation = "HTTP" }
    www  = { host = "www.arxivisual.org", validation = "CNAME" }
  } : {}
}

# Phase 1 — hostnames, unbound.
resource "azurerm_container_app_custom_domain" "web" {
  for_each         = local.web_domains
  name             = each.value.host # the FQDN itself, no "asuid." prefix
  container_app_id = azurerm_container_app.web.id
  # No certificate arguments: that selects the managed-certificate path.

  lifecycle {
    # Mandatory for managed certificates (provider docs): phase 3 flips the
    # binding to SniEnabled out-of-band, every argument here is ForceNew, and
    # without this each plan would destroy/recreate the domain (dropping TLS).
    ignore_changes = [certificate_binding_type, container_app_environment_certificate_id]
  }
}

# Phase 2 — free managed certificates (auto-renewed while DNS stays correct).
resource "azurerm_container_app_environment_managed_certificate" "web" {
  for_each                     = local.web_domains
  name                         = "arxivisual-web-${each.key}" # lowercase, unique per environment
  container_app_environment_id = azurerm_container_app_environment.main.id
  subject_name                 = each.value.host
  domain_control_validation    = each.value.validation

  depends_on = [azurerm_container_app_custom_domain.web]
}

# Phase 3 — bind. azapi GETs the app, merges this body in (list items matched
# by `name`, other ingress settings preserved) and PUTs the whole document
# back — which is why the app must carry no secrets (see the header). NOTE:
# azapi_update_resource's delete is a no-op — to remove a domain, unbind it
# first (`az containerapp hostname delete`), then destroy.
resource "azapi_update_resource" "web_domain_binding" {
  count       = var.web_custom_domains_enabled ? 1 : 0
  type        = "Microsoft.App/containerApps@2025-07-01"
  resource_id = azurerm_container_app.web.id

  body = {
    properties = {
      configuration = {
        ingress = {
          customDomains = [
            for k, d in local.web_domains : {
              name          = d.host
              bindingType   = "SniEnabled"
              certificateId = azurerm_container_app_environment_managed_certificate.web[k].id
            }
          ]
        }
      }
    }
  }

  depends_on = [azurerm_container_app_custom_domain.web]
}

# The records to create at Porkbun BEFORE enabling the custom domains. The
# verification id is read from the ENVIRONMENT: the same value is exported on
# the app, but the provider marks that attribute sensitive, which would force
# this whole output to be sensitive and hide the DNS rows.
output "web_dns_records" {
  description = "Porkbun records for arxivisual.org -> arxivisual-web. Create these, wait for propagation, then apply with web_custom_domains_enabled = true."
  value = {
    apex_A    = { type = "A", host = "", value = azurerm_container_app_environment.main.static_ip_address }
    apex_TXT  = { type = "TXT", host = "asuid", value = azurerm_container_app_environment.main.custom_domain_verification_id }
    www_CNAME = { type = "CNAME", host = "www", value = azurerm_container_app.web.ingress[0].fqdn }
    www_TXT   = { type = "TXT", host = "asuid.www", value = azurerm_container_app_environment.main.custom_domain_verification_id }
  }
}
