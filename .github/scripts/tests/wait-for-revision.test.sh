#!/usr/bin/env bash
# wait-for-revision.sh against a stub `az` (tests/stub/az): every state a roll
# can be in, without touching Azure. The script only ever runs for real in the
# middle of a production deploy, which is the wrong place to find its bugs.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
script="$here/../wait-for-revision.sh"
# shellcheck source=.github/scripts/tests/lib.sh
source "$here/lib.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

image="acr.azurecr.io/arxivisual-api:gh-new"
old_image="acr.azurecr.io/arxivisual-api:gh-old"
dir=""

scenario() { # fresh stub state; the app is configured with the new image
  dir=$(mktemp -d "$tmp/scenario.XXXXXX")
  echo "$image" > "$dir/configured"
}

rev() { # <image> <provisioning> <health> <running> -> one newest-revision answer
  echo "{\"name\":\"app--0000037\",\"image\":\"$1\",\"provisioning\":\"$2\",\"health\":\"$3\",\"running\":\"$4\"}"
}
healthy() { rev "$image" Provisioned Healthy Running; }

containers() { # <restartCount>:<runningState> ... -> one replica-list answer
  local sep="" pair
  printf '['
  for pair in "$@"; do
    printf '%s{"restartCount":%s,"runningState":"%s"}' "$sep" "${pair%%:*}" "${pair##*:}"
    sep=","
  done
  printf ']\n'
}

wait_for() { # [VAR=value ...] — run the script against the current scenario
  env PATH="$here/stub:$PATH" AZ_STUB_DIR="$dir" RESOURCE_GROUP=rg \
    POLL_SECONDS=0.1 STABLE_POLLS=3 REVISION_WAIT_SECONDS=5 \
    RESTART_WATCH_SECONDS=1 DRAIN_WAIT_SECONDS=1 "$@" \
    bash "$script" arxivisual-worker "$image"
}

# ── the roll itself ──────────────────────────────────────────────────────────

begin "clean roll: no restarts, no watch"
scenario
healthy > "$dir/newest"
containers 0:Running > "$dir/replicas"
run wait_for
expect_exit 0
expect_out "no container of app--0000037 has restarted"
expect_out "is the only active revision"
refute_out "::warning::"
finish

begin "mid-roll: old revision newest, then provisioning, then healthy"
scenario
{
  rev "$old_image" Provisioned Healthy Running
  rev "$image" Provisioning None Activating
  healthy
} > "$dir/newest"
containers 0:Running > "$dir/replicas"
run wait_for
expect_exit 0
finish

begin "flapping health resets the stable streak"
scenario
{
  healthy
  rev "$image" Provisioned Unhealthy Running
  healthy
} > "$dir/newest"
containers 0:Running > "$dir/replicas"
run wait_for
expect_exit 0
finish

begin "az outage while polling is ridden out"
scenario
{
  echo ERROR
  echo ERROR
  healthy
} > "$dir/newest"
containers 0:Running > "$dir/replicas"
run wait_for
expect_exit 0
finish

begin "the update did not take"
scenario
echo "$old_image" > "$dir/configured"
healthy > "$dir/newest"
run wait_for
expect_exit 1
expect_out "the update did not take"
finish

begin "revision fails to activate"
scenario
rev "$image" Provisioned None ActivationFailed > "$dir/newest"
run wait_for
expect_exit 1
expect_out "failed to start"
finish

begin "never healthy: times out"
scenario
rev "$image" Provisioned Unhealthy Running > "$dir/newest"
run wait_for REVISION_WAIT_SECONDS=1
expect_exit 1
expect_out "no stable Healthy + Running revision"
finish

begin "replaced revision never drains: warns, still succeeds"
scenario
healthy > "$dir/newest"
containers 0:Running > "$dir/replicas"
echo 1 > "$dir/others"
run wait_for
expect_exit 0
expect_out "older revision(s) still active"
finish

# ── crash loop vs startup restart ────────────────────────────────────────────

begin "one startup restart, then stable: warns, succeeds"
scenario
healthy > "$dir/newest"
containers 1:Running > "$dir/replicas"
run wait_for
expect_exit 0
expect_out "::warning::arxivisual-worker: containers of app--0000037 have restarted 1 time(s)"
expect_out "a startup restart, not a crash loop"
refute_out "::error::"
finish

# The count is cumulative and a same-image deploy makes no new revision, so a
# re-run sees exactly the same state. It must not be red for the life of the
# revision — on the API step that left the worker un-rolled.
begin "re-run on that same revision succeeds too (no retry trap)"
run wait_for
expect_exit 0
refute_out "::error::"
finish

begin "restart count rises while watched: crash loop"
scenario
healthy > "$dir/newest"
{
  containers 1:Running
  containers 1:Running
  containers 2:Running
} > "$dir/replicas"
run wait_for
expect_exit 1
expect_out "restarted again while being watched (1 -> 2)"
expect_out "az containerapp logs show -n arxivisual-worker -g rg --revision app--0000037"
finish

begin "restarted container still down when the watch ends: loop in back-off"
scenario
healthy > "$dir/newest"
containers 5:Waiting > "$dir/replicas"
run wait_for
expect_exit 1
expect_out "still not running after 1s"
finish

begin "restarted container down at first, running by the end: succeeds"
scenario
healthy > "$dir/newest"
{
  containers 1:Waiting
  containers 1:Running
} > "$dir/replicas"
run wait_for
expect_exit 0
refute_out "::error::"
finish

begin "scale-out next to a restarted replica is not a loop"
scenario
healthy > "$dir/newest"
containers 1:Running 0:Waiting > "$dir/replicas"
run wait_for
expect_exit 0
refute_out "::error::"
finish

begin "unreadable replica data never fails the deploy"
scenario
healthy > "$dir/newest"
echo ERROR > "$dir/replicas"
run wait_for
expect_exit 0
expect_out "unreadable; skipping the crash-loop check"
finish

begin "replica data unreadable mid-watch is skipped over"
scenario
healthy > "$dir/newest"
{
  containers 1:Running
  echo ERROR
  containers 1:Running
} > "$dir/replicas"
run wait_for
expect_exit 0
expect_out "replica data unreadable"
finish

begin "scaled to zero: no replicas, nothing restarted"
scenario
healthy > "$dir/newest"
echo "[]" > "$dir/replicas"
run wait_for
expect_exit 0
expect_out "no container of app--0000037 has restarted"
finish

summary
