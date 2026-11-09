#!/usr/bin/env bash
# Deploy gate: refuse to ship a commit whose CI is not green.
#
# The deploy workflows are dispatched by hand, and the last three production
# deploys were dispatched ~90 s BEFORE CI finished on the commit they shipped.
# This makes "once CI is green" a fact instead of a convention.
#
#   usage: require-green-ci.sh "<check-run name prefix>" ["<prefix>" ...]
#   env:   DEPLOY_SHA          commit being deployed (github.sha)
#          GITHUB_REPOSITORY   owner/repo (set by Actions)
#          GH_TOKEN            github.token; the job needs `checks: read`
#          CI_WAIT_SECONDS     how long to wait for checks still running (1200)
#          CI_MISSING_SECONDS  how long to wait for a check that has not been
#                              created yet (180; a dispatch seconds after merge)
#
# A prefix (not an exact name) so a matrix job — "Backend tests (py3.11)",
# "Backend tests (py3.13)" — is covered whatever its legs are called. Every
# check run matching a prefix must have concluded `success`, and every prefix
# must match at least one check run. Checks still running are WAITED for (the
# dispatch-right-after-merge habit then just works); a finished check that is
# anything other than `success` fails immediately.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <check-run name prefix> [<prefix> ...]" >&2
  exit 2
fi
: "${DEPLOY_SHA:?DEPLOY_SHA must be set to the commit being deployed}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set (owner/repo)}"

wait_seconds="${CI_WAIT_SECONDS:-1200}"
missing_seconds="${CI_MISSING_SECONDS:-180}"
poll_seconds=20

prefixes_json=$(printf '%s\n' "$@" | jq -R . | jq -s .)

# Newest check run per name, as a JSON array: a re-run (or a second CI run on
# the same commit) supersedes the earlier one.
fetch_runs() {
  gh api --paginate \
    "repos/$GITHUB_REPOSITORY/commits/$DEPLOY_SHA/check-runs?per_page=100" \
    --jq '.check_runs[] | {id, name, status, conclusion, html_url}' \
    | jq -s 'group_by(.name) | map(max_by(.id))'
}

escape_hatch="To deploy anyway (emergency only), re-dispatch with skip_ci_check=true."
started=$(date +%s)

echo "Requiring green CI on $DEPLOY_SHA for: $*"
while true; do
  elapsed=$(( $(date +%s) - started ))

  if ! runs=$(fetch_runs); then
    echo "check-runs query failed; treating as not ready yet."
    runs='[]'
  fi

  report=$(jq --argjson prefixes "$prefixes_json" '
    . as $runs
    | [ $prefixes[] as $p
        | { prefix: $p, runs: [ $runs[] | select(.name | startswith($p)) ] } ]
    | {
        missing: [ .[] | select(.runs | length == 0) | .prefix ],
        failed:  [ .[].runs[] | select(.status == "completed" and .conclusion != "success") ],
        pending: [ .[].runs[] | select(.status != "completed") ],
        passed:  [ .[].runs[] | select(.status == "completed" and .conclusion == "success") ]
      }' <<<"$runs")

  jq -r '
    (.passed[]  | "  ok       \(.name)"),
    (.pending[] | "  \(.status)  \(.name)"),
    (.failed[]  | "  \(.conclusion)  \(.name)  \(.html_url)"),
    (.missing[] | "  missing  \(.)*")' <<<"$report"

  n_failed=$(jq '.failed | length' <<<"$report")
  n_pending=$(jq '.pending | length' <<<"$report")
  n_missing=$(jq '.missing | length' <<<"$report")

  if [ "$n_failed" -gt 0 ]; then
    names=$(jq -r '[.failed[] | "\(.name) (\(.conclusion))"] | join(", ")' <<<"$report")
    echo "::error::CI is not green on $DEPLOY_SHA: $names. Fix main (or re-run the failed job) and dispatch again. $escape_hatch"
    exit 1
  fi

  if [ "$n_pending" -eq 0 ] && [ "$n_missing" -eq 0 ]; then
    echo "CI is green on $DEPLOY_SHA."
    exit 0
  fi

  if [ "$n_pending" -eq 0 ] && [ "$elapsed" -ge "$missing_seconds" ]; then
    names=$(jq -r '.missing | join(", ")' <<<"$report")
    echo "::error::No check run named '$names*' exists for $DEPLOY_SHA, so CI never ran on it. Run it: gh workflow run ci.yml --ref main — then dispatch again. $escape_hatch"
    exit 1
  fi

  if [ "$elapsed" -ge "$wait_seconds" ]; then
    echo "::error::CI on $DEPLOY_SHA was still not finished after ${wait_seconds}s. Wait for it, then dispatch again. $escape_hatch"
    exit 1
  fi

  echo "CI not finished yet (${elapsed}s elapsed); checking again in ${poll_seconds}s..."
  sleep "$poll_seconds"
done
