# Subscription-scoped monthly cost budget ($300 in the billing currency) with
# email alerts at 50% / 90% actual and 100% forecast.
resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "arxivisual-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"

  amount     = 300
  time_grain = "Monthly"

  time_period {
    start_date = "2026-08-01T00:00:00Z"
    end_date   = "2028-07-31T00:00:00Z"
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 50
    threshold_type = "Actual"
    contact_emails = ["ajithbon05@gmail.com"]
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 90
    threshold_type = "Actual"
    contact_emails = ["ajithbon05@gmail.com"]
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Forecasted"
    contact_emails = ["ajithbon05@gmail.com"]
  }
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
          contactEmails = ["ajithbon05@gmail.com"]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 50
          thresholdType = "Actual"
        }
        actual_GreaterThan_80_Percent = {
          contactEmails = ["ajithbon05@gmail.com"]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 80
          thresholdType = "Actual"
        }
        forecasted_GreaterThan_100_Percent = {
          contactEmails = ["ajithbon05@gmail.com"]
          enabled       = true
          operator      = "GreaterThan"
          threshold     = 100
          thresholdType = "Forecasted"
        }
      }
    }
  }
}
