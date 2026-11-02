#!/usr/bin/env python3
"""arXivisual credit runway tracker.

Answers one question every day: at today's burn, do the Azure credits last
until they expire (2028-07-29)? Reads only, using the logged-in `az` CLI:

  * daily ActualCost per resource and meter (Cost Management query API, CAD)
  * the live settings each cost cut changes (container app sizes, the worker's
    model and image, model deployments, the budget, the hard stop)

and writes four JSON files of row objects to --out (default: print a summary):

  summary.json  one row: credits left, burn, required pace, runway, status
  daily.json    cost per day per component, last 60 days
  runway.json   projected credit balance per month until expiry
  cuts.json     each cost cut, whether it is live, and what it is set to

Credits: the billing API gives the exact balance as of the latest invoice
(monthly, issued around the 9th). Charges since then come from Cost
Management and are subtracted, so the figure is current to the day. If the
billing API cannot be read, a fixed reading (BASELINE_*) is used instead;
--baseline-cad and --baseline-date force one.

    python3 infra/credit_tracker.py                 # human summary
    python3 infra/credit_tracker.py --out /tmp/ct   # JSON for the dashboard
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import subprocess
import sys
import time

SUB = "4301c7fd-ffa2-4ad1-bca9-a15ef2d2bd59"
RG = "arxivisual-rg"
OPENAI_ACCOUNT = "arxivisual-openai"
BUDGET_NAME = "arxivisual-monthly"
BILLING_ACCOUNT = "3f54dc1c-3b08-5841-bb04-33a83cf4e3a7:9dc3de7a-80d3-4d17-baf3-665da89267cd_2019-05-31"
BILLING_PROFILE = "PVNY-KSBE-BG7-PGB"

# Fallback only, when the billing API cannot be read: a balance and the first
# day whose charges are not in it. Charges from this date on are subtracted.
BASELINE_CAD = 11937.0
BASELINE_DATE = dt.date(2026, 10, 20)
EXPIRY = dt.date(2028, 7, 29)

DAYS_PER_MONTH = 365.25 / 12
HISTORY_DAYS = 60
# Cost Management posts a day's charges over the following ~24-48 h, so the
# last two days read low. Burn rates use only days at least this old.
SETTLE_DAYS = 2

# Rough monthly savings per cut from the 2026-10-21 audit, in CAD at
# ~80 papers/day. Labelled as estimates wherever they are shown.
EST_SAVING = {
    "worker_model": 480,
    "worker_image": 120,
    "api_size": 70,
    "temporal_size": 80,
    "web_zero": 8,
    "sol_removed": 0,
    "budget": 0,
    "hard_stop": 0,
    "cap": 180,
    "tts": 130,
}


def az_json(*args: str, attempts: int = 3):
    """Run an az command and parse its JSON; None when it fails.

    Cost Management throttles bursts (429), so failures are retried.
    """
    for attempt in range(attempts):
        proc = subprocess.run(
            ["az", *args, "-o", "json"], capture_output=True, text=True, timeout=180
        )
        if proc.returncode == 0:
            break
        if attempt + 1 < attempts:
            time.sleep(20 * (attempt + 1))
    else:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def component(resource_id: str, meter: str) -> str:
    """Bucket a cost row into a component a reader recognises."""
    name = (resource_id or "").rsplit("/", 1)[-1].lower()
    if name == OPENAI_ACCOUNT:
        return "AI voice" if "tts" in meter.lower() else "AI text"
    return {
        "arxivisual-worker": "Worker",
        "arxivisual-temporal": "Temporal",
        "arxivisual-api": "API",
        "arxivisual-web": "Web",
        "arxivisual-db": "Database",
    }.get(name, "Other")


def daily_costs(start: dt.date, end: dt.date) -> dict[dt.date, dict[str, float]]:
    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ResourceId"},
                {"type": "Dimension", "name": "Meter"},
            ],
        },
    }
    url = (
        f"https://management.azure.com/subscriptions/{SUB}"
        "/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    )
    out: dict[dt.date, dict[str, float]] = collections.defaultdict(
        lambda: collections.defaultdict(float)
    )
    while url:
        res = az_json("rest", "--method", "post", "--url", url, "--body", json.dumps(body))
        if res is None:
            sys.exit("Cost Management query failed: is az logged in to the arXivisual subscription?")
        props = res["properties"]
        cols = [c["name"] for c in props["columns"]]
        for row in props["rows"]:
            r = dict(zip(cols, row))
            day = dt.datetime.strptime(str(r["UsageDate"]), "%Y%m%d").date()
            out[day][component(r.get("ResourceId", ""), r.get("Meter", ""))] += r["Cost"]
        url = props.get("nextLink")
    return out


def invoiced_baseline():
    """(balance_cad, first_unbilled_day, rate) from the billing API, or None.

    The credit lot's currentBalance is exact up to the end of the latest
    issued invoice's period; everything after that is unbilled. Azure's own
    estimatedBalance subtracts unbilled charges too, but it lags by a week or
    two (2026-11-02: it had only Oct 1-17 deducted), so the tracker subtracts
    Cost Management's charges from the invoiced balance itself.
    """
    base = f"https://management.azure.com/providers/Microsoft.Billing/billingAccounts/{BILLING_ACCOUNT}/billingProfiles/{BILLING_PROFILE}"
    bal = az_json("rest", "--method", "get", "--url",
                  f"{base}/providers/Microsoft.Consumption/credits/balanceSummary?api-version=2023-05-01")
    today = dt.datetime.now(dt.timezone.utc).date()
    inv = az_json("rest", "--method", "get", "--url",
                  f"{base}/invoices?periodStartDate={today - dt.timedelta(days=120)}"
                  f"&periodEndDate={today}&api-version=2020-05-01")
    try:
        summary = bal["properties"]["balanceSummary"]
        usd = float(summary["currentBalance"]["value"])
        rate = float(summary["estimatedBalanceInBillingCurrency"]["exchangeRate"])
        ends = [i["properties"]["invoicePeriodEndDate"][:10] for i in inv["value"]]
        due = sum(float((i["properties"].get("amountDue") or {}).get("value") or 0) for i in inv["value"])
    except (TypeError, KeyError, ValueError):
        return None
    if not ends:
        return None
    first_unbilled = dt.date.fromisoformat(max(ends)) + dt.timedelta(days=1)
    return usd * rate, first_unbilled, rate, usd, due


def app(name: str):
    return az_json("containerapp", "show", "-n", name, "-g", RG) or {}


def env_of(app_json, key: str):
    for e in app_json.get("properties", {}).get("template", {}).get("containers", [{}])[0].get("env", []):
        if e.get("name") == key:
            return e.get("value")
    return None


def container(app_json):
    return app_json.get("properties", {}).get("template", {}).get("containers", [{}])[0]


def live_cuts() -> list[dict]:
    api, worker, temporal, web = (app(n) for n in (
        "arxivisual-api", "arxivisual-worker", "arxivisual-temporal", "arxivisual-web"))
    deployments = az_json("cognitiveservices", "account", "deployment", "list",
                          "-n", OPENAI_ACCOUNT, "-g", RG) or []
    names = sorted(d["name"] for d in deployments)
    budget = az_json("consumption", "budget", "show", "--budget-name", BUDGET_NAME) or {}
    automation = az_json("resource", "list", "-g", RG,
                         "--resource-type", "Microsoft.Automation/automationAccounts") or []

    def tag(a):
        return (container(a).get("image") or "?").rsplit(":", 1)[-1][:10]

    worker_model = env_of(worker, "AZURE_OPENAI_DEPLOYMENT") or "?"
    cap = env_of(api, "DAILY_NEW_PAPER_CAP") or "80"
    tts = env_of(worker, "VOICEOVER_TTS_SERVICE") or "openai"
    # Azure reports min replicas 0 as null (the API's default is 0).
    web_min = web.get("properties", {}).get("template", {}).get("scale", {}).get("minReplicas") or 0 if web else None
    api_cpu = container(api).get("resources", {}).get("cpu")
    tp_cpu = container(temporal).get("resources", {}).get("cpu")
    amount = budget.get("amount")

    rows = [
        ("worker_model", "Worker uses gpt-6-luna", worker_model == "gpt-6-luna", f"model {worker_model}"),
        ("worker_image", "Worker runs current code", tag(worker) == tag(api),
         f"worker {tag(worker)}, api {tag(api)}"),
        ("api_size", "API at 0.5 vCPU", api_cpu is not None and float(api_cpu) <= 0.5, f"{api_cpu} vCPU"),
        ("temporal_size", "Temporal at 0.5 vCPU", tp_cpu is not None and float(tp_cpu) <= 0.5, f"{tp_cpu} vCPU"),
        ("web_zero", "Spare web app scales to zero", web_min == 0, f"min replicas {web_min}"),
        ("sol_removed", "Unused gpt-5.6-sol removed", "gpt-5.6-sol" not in names, ", ".join(names)),
        ("budget", "Budget alert at CA$575", amount is not None and float(amount) == 575,
         f"budget {amount}"),
        ("hard_stop", "Hard stop armed", bool(automation),
         "armed" if automation else "not armed (README: Hard stop)"),
        ("cap", "Daily paper cap at 50", cap.isdigit() and 0 < int(cap) <= 50, f"cap {cap}/day"),
        ("tts", "Free narration voice", tts == "gtts", f"voice service {tts}"),
    ]
    return [
        {"key": k, "cut": label, "live": "Live" if ok else "Not yet", "setting": now,
         "est_saving_cad_month": EST_SAVING[k]}
        for k, label, ok, now in rows
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=pathlib.Path, help="write the four JSON files here")
    ap.add_argument("--baseline-cad", type=float, help="force a balance in CAD (with --baseline-date)")
    ap.add_argument("--baseline-date", type=dt.date.fromisoformat, help="first day NOT in --baseline-cad")
    ap.add_argument("--skip-cuts", action="store_true", help="costs only, no live settings")
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).date()
    card_due = None
    if args.baseline_cad is not None and args.baseline_date is not None:
        source = "given on the command line"
    elif (live := invoiced_baseline()) is not None:
        args.baseline_cad, args.baseline_date, _rate, _usd, card_due = live
        source = f"invoiced balance US${_usd:,.2f} at {_rate:.4f} CAD/USD"
    else:
        args.baseline_cad, args.baseline_date = BASELINE_CAD, BASELINE_DATE
        source = "fixed reading (billing API unreadable)"
    start = min(args.baseline_date, today - dt.timedelta(days=HISTORY_DAYS))
    costs = daily_costs(start, today)

    settled_end = today - dt.timedelta(days=SETTLE_DAYS)
    day_total = {d: sum(v.values()) for d, v in costs.items()}
    last7 = [day_total.get(settled_end - dt.timedelta(days=i), 0.0) for i in range(7)]
    last30 = [day_total.get(settled_end - dt.timedelta(days=i), 0.0) for i in range(30)]
    burn7 = sum(last7) / 7
    burn30 = sum(last30) / 30

    # Charges since the baseline: settled days as billed; the unsettled tail
    # (still filling in) counted at the 7-day rate so it is not undercounted.
    settled_spend = sum(t for d, t in day_total.items() if args.baseline_date <= d <= settled_end)
    tail_days = (today - settled_end).days
    spent = settled_spend + burn7 * tail_days
    remaining = args.baseline_cad - spent

    days_left = (EXPIRY - today).days
    months_left = days_left / DAYS_PER_MONTH
    required_month = remaining / months_left
    burn_month = burn7 * DAYS_PER_MONTH
    runway_days = remaining / burn7 if burn7 > 0 else float("inf")
    runway_date = today + dt.timedelta(days=min(runway_days, 36500))
    short_days = max(0, (EXPIRY - runway_date).days)
    ratio = burn_month / required_month if required_month > 0 else float("inf")
    status = "On track" if ratio <= 1.0 else ("At risk" if ratio <= 1.25 else "Off track")
    mtd = sum(t for d, t in day_total.items() if d.year == today.year and d.month == today.month)

    summary = {
        "as_of": today.isoformat(),
        "status": status,
        "credits_left_cad": round(remaining, 2),
        "baseline_cad": args.baseline_cad,
        "baseline_date": args.baseline_date.isoformat(),
        "baseline_source": source,
        "card_amount_due_cad": card_due,
        "spent_since_baseline_cad": round(spent, 2),
        "burn_7d_cad_day": round(burn7, 2),
        "burn_30d_cad_day": round(burn30, 2),
        "burn_cad_month": round(burn_month, 2),
        "required_cad_month": round(required_month, 2),
        "required_cad_day": round(required_month / DAYS_PER_MONTH, 2),
        "over_pace_cad_month": round(burn_month - required_month, 2),
        "burn_vs_pace": round(ratio, 3),
        "runway_date": runway_date.isoformat(),
        "expiry_date": EXPIRY.isoformat(),
        "days_short": short_days,
        "months_left": round(months_left, 1),
        "month_to_date_cad": round(mtd, 2),
        "settled_through": settled_end.isoformat(),
    }

    components = ["AI text", "AI voice", "Worker", "Temporal", "API", "Database", "Web", "Other"]
    daily = [
        {"day": d.isoformat(), "component": c, "cost_cad": round(costs[d].get(c, 0.0), 2),
         "settled": d <= settled_end}
        for d in sorted(costs) if d >= today - dt.timedelta(days=HISTORY_DAYS)
        for c in components
    ]

    runway = []
    month = dt.date(today.year, today.month, 1)
    while month <= EXPIRY:
        elapsed = max(0, (month - today).days)
        runway.append({
            "month": month.isoformat(),
            "at_current_burn_cad": round(max(0.0, remaining - burn7 * elapsed), 2),
            "on_required_pace_cad": round(max(0.0, remaining - required_month / DAYS_PER_MONTH * elapsed), 2),
        })
        month = dt.date(month.year + (month.month == 12), month.month % 12 + 1, 1)

    cuts = [] if args.skip_cuts else live_cuts()

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for name, rows in (("summary", [summary]), ("daily", daily), ("runway", runway), ("cuts", cuts)):
            (args.out / f"{name}.json").write_text(json.dumps(rows, indent=1))
        print(f"wrote summary/daily/runway/cuts.json to {args.out}")

    s = summary
    print(f"\n{s['status']}  (as of {s['as_of']}, costs settled through {s['settled_through']})")
    print(f"  credits left (est.)   CA${s['credits_left_cad']:>10,.0f}   expire {s['expiry_date']} ({s['months_left']} months)")
    print(f"  burn, last 7 days     CA${s['burn_7d_cad_day']:>10,.2f}/day = CA${s['burn_cad_month']:,.0f}/month")
    print(f"  pace that lasts       CA${s['required_cad_day']:>10,.2f}/day = CA${s['required_cad_month']:,.0f}/month")
    print(f"  credits run out       {s['runway_date']}  ({s['days_short']} days before expiry)")
    print(f"  this month so far     CA${s['month_to_date_cad']:>10,.0f}")
    for c in cuts:
        print(f"  [{'x' if c['live'] == 'Live' else ' '}] {c['cut']:<32} {c['setting']}")


if __name__ == "__main__":
    main()
