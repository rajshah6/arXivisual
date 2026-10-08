# Subscription-scoped monthly cost budget in the billing currency (CAD).
#
# 575 = the average monthly burn at which the remaining Azure credit lasts to
# its expiry on 2028-07-29: US$8,786.40 left on 2026-10-08 (balanceSummary)
# / 660 days x 30.44 days/month x 1.41655 CAD/USD = CA$574.04. Recompute it
# quarterly (credit left / months left x FX); the burn was ~CA$1,170/mo when
# this was set, so the alerts below are expected to fire until the cost cuts
# land.
#
# What a budget can and cannot do: it evaluates cost BEFORE credits are
# applied and it only sends email; it stops nothing. The guardrail that would
# actually stop spend is the subscription spending limit (portal only).
#
# Thresholds: 50% / 90% actual fired every month even when spending exactly on
# pace, so they are gone. 100% forecast is the early warning (this month is
# heading over pace), 100% actual means it went over, 150% actual means
# something is badly wrong (a runaway deployment, a leaked key).
resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "arxivisual-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"

  amount     = 575
  time_grain = "Monthly"

  time_period {
    start_date = "2026-08-01T00:00:00Z"
    end_date   = "2028-07-31T00:00:00Z"
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Forecasted"
    contact_emails = [var.contact_email]
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Actual"
    contact_emails = [var.contact_email]
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 150
    threshold_type = "Actual"
    contact_emails = [var.contact_email]
  }
}

# Cost anomaly alert (free): Cost Management compares each day's subscription
# usage with a forecast from the previous 60 days and mails when it falls
# outside the expected range. Detection runs 36 h after the end of the UTC day
# (Learn: analyze-unexpected-charges), so a spike is reported within ~2 days
# instead of at the next monthly budget threshold. There was no anomaly alert
# before this (scheduledActions on the subscription was empty, 2026-10-08).
#
# EXPIRY: the provider writes the schedule with end date = now + 1 year on
# every create or update (azurerm 4.81 cost_anomaly_alert_resource.go), the
# API caps end dates at one year anyway (Learn: save-share-views), and the
# schedule is not in Terraform state, so the expiry never shows in a plan. To
# renew, change the date in `message` and apply before the stamp is a year
# old. Mail goes out only while the identity that applied this can still read
# the subscription's costs.
resource "azurerm_cost_anomaly_alert" "subscription" {
  name            = "arxivisual-cost-anomaly"
  display_name    = "arXivisual cost anomaly"
  subscription_id = "/subscriptions/${var.subscription_id}"
  email_subject   = "arXivisual: Azure cost anomaly"
  email_addresses = [var.contact_email]
  message         = "Daily Azure usage left its expected range. Renewed 2026-10; renew by 2027-10."
}

# "MonthlyReset" is a $5 budget scoped to the BILLING ACCOUNT (Microsoft
# Customer Agreement), not the subscription or resource group. azurerm has no
# resource type for billing-account budgets, so it is expressed with azapi.
resource "azapi_resource" "billing_monthly_reset_budget" {
  type      = "Microsoft.CostManagement/budgets@2023-11-01"
  name      = "MonthlyReset"
  parent_id = "/providers/Microsoft.Billing/billingAccounts/3f54dc1c-3b08-5841-bb04-33a83cf4e3a7:9dc3de7a-80d3-4d17-baf3-665da89267cd_2019-05-31"

  body = {
    properties = {
      amount    = 5
      category  = "Cost"
      timeGrain = "Monthly"

      timePeriod = {
        startDate = "2026-07-01T00:00:00Z"
        endDate   = "2030-06-30T00:00:00Z"
      }

      notifications = {
        actual_GreaterThan_50_Percent = {
          contactEmails = [var.contact_email]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 50
          thresholdType = "Actual"
        }
        actual_GreaterThan_80_Percent = {
          contactEmails = [var.contact_email]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 80
          thresholdType = "Actual"
        }
        forecasted_GreaterThan_100_Percent = {
          contactEmails = [var.contact_email]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 100
          thresholdType = "Forecasted"
        }
      }
    }
  }
}
