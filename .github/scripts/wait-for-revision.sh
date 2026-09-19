#!/usr/bin/env bash
# Wait until a Container App's newest revision runs IMAGE and is actually up.
#
# `az containerapp update` returns before the new revision is provisioned, and
# in single-revision mode the previous revision keeps running until the new
# one passes its probes — so neither the CLI's exit code nor "the app answers"
# proves the roll happened. This is the only check available for the worker
# (no ingress), and the API gets it too before its /api/health commit check.
#
#   usage: wait-for-revision.sh <app> <image>
#   env:   RESOURCE_GROUP          resource group of the app
#          REVISION_WAIT_SECONDS   timeout (1200 — the backend image is ~3 GB
#                                  and a cold pull alone can take minutes)
#          STABLE_POLLS            consecutive Healthy + Running reads required
#                                  (3 — a process that dies on startup reads
#                                  Running for a moment first)
#          RESTART_WATCH_SECONDS   how long a revision whose containers have
#                                  restarted is watched before a startup hiccup
#                                  is told from a crash loop (180; a revision
#                                  with no restarts is not watched at all)
#          DRAIN_WAIT_SECONDS      how long to wait afterwards for the replaced
#                                  revision to deactivate (180)
#          POLL_SECONDS            poll interval (15)
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <app> <image>" >&2
  exit 2
fi
app=$1
image=$2
: "${RESOURCE_GROUP:?RESOURCE_GROUP must be set}"

wait_seconds="${REVISION_WAIT_SECONDS:-1200}"
stable_polls="${STABLE_POLLS:-3}"
watch_seconds="${RESTART_WATCH_SECONDS:-180}"
drain_seconds="${DRAIN_WAIT_SECONDS:-180}"
poll_seconds="${POLL_SECONDS:-15}"

revision_table() {
  az containerapp revision list -n "$app" -g "$RESOURCE_GROUP" \
    --query "[].{name:name, image:properties.template.containers[0].image, provisioning:properties.provisioningState, health:properties.healthState, running:properties.runningState, traffic:properties.trafficWeight}" \
    -o table >&2 || true
}

# 1) The app's template must name the image — otherwise the update never took.
configured=$(az containerapp show -n "$app" -g "$RESOURCE_GROUP" \
  --query "properties.template.containers[0].image" -o tsv || true)
if [ "$configured" != "$image" ]; then
  echo "::error::$app is configured with '${configured:-<unreadable>}', expected '$image' — the update did not take."
  exit 1
fi

# 2) Its newest revision must carry the image and stay Healthy + Running. (The
#    list holds active revisions only; mid-roll that is the old and the new.)
echo "Waiting for the newest revision of $app to run $image ..."
started=$(date +%s)
name=""
stable=0
while true; do
  elapsed=$(( $(date +%s) - started ))

  newest=$(az containerapp revision list -n "$app" -g "$RESOURCE_GROUP" \
    --query "sort_by(@, &properties.createdTime)[-1].{name:name, image:properties.template.containers[0].image, provisioning:properties.provisioningState, health:properties.healthState, running:properties.runningState}" \
    -o json || true)
  name=$(jq -r '.name // empty' <<<"$newest" 2>/dev/null || true)
  rev_image=$(jq -r '.image // empty' <<<"$newest" 2>/dev/null || true)
  provisioning=$(jq -r '.provisioning // empty' <<<"$newest" 2>/dev/null || true)
  health=$(jq -r '.health // empty' <<<"$newest" 2>/dev/null || true)
  running=$(jq -r '.running // empty' <<<"$newest" 2>/dev/null || true)

  echo "  ${elapsed}s: ${name:-<no revision>} provisioning=${provisioning:-?} health=${health:-?} running=${running:-?}"

  # RunningAtMaxScale is Running with every allowed replica up.
  if [ "$rev_image" = "$image" ] && [ "$health" = "Healthy" ] \
    && { [ "$running" = "Running" ] || [ "$running" = "RunningAtMaxScale" ]; }; then
    stable=$((stable + 1))
    if [ "$stable" -ge "$stable_polls" ]; then
      echo "$app: revision $name is Healthy and $running on $image."
      break
    fi
  else
    stable=0
    if [ "$rev_image" = "$image" ] \
      && { [ "$provisioning" = "Failed" ] || [ "$running" = "Failed" ] || [ "$running" = "ActivationFailed" ]; }; then
      echo "::error::$app: revision $name failed to start (provisioning=$provisioning, running=$running). Logs: az containerapp logs show -n $app -g $RESOURCE_GROUP --revision $name --tail 100"
      revision_table
      exit 1
    fi
  fi

  if [ "$elapsed" -ge "$wait_seconds" ]; then
    echo "::error::$app: no stable Healthy + Running revision on $image after ${wait_seconds}s. Logs: az containerapp logs show -n $app -g $RESOURCE_GROUP --tail 100"
    revision_table
    exit 1
  fi
  sleep "$poll_seconds"
done

# 3) A container that KEEPS restarting is crash-looping, whatever the revision
#    state says right now — and the worker has no ingress or probe that would
#    ever surface it. Restarts that have STOPPED are not a loop: losing a
#    startup race (Postgres connections while old and new replicas overlap, the
#    worker up before Temporal answers) costs one restart, and restartCount is
#    cumulative — failing on "> 0" kept every re-run of the same image red for
#    the life of the revision (a same-image deploy makes no new revision), and
#    when it tripped on the API the worker was never rolled at all. So a
#    non-zero count only buys a watch. The deploy fails if the count RISES
#    while watched, or if a container that restarted is still not running when
#    the watch ends (the platform's restart back-off grows to 5 minutes, so a
#    loop can sit between two restarts for the whole watch). Judged on the last
#    readable answer; unreadable replica data never fails the deploy.
restart_state() { # -> "<restarts> <restarted containers not running>", nothing if unreadable
  az containerapp replica list -n "$app" -g "$RESOURCE_GROUP" --revision "$name" \
    --query "[].properties.containers[].{restartCount:restartCount, runningState:runningState}" \
    -o json \
    | jq -r '
        if type != "array" then empty else
          "\([.[].restartCount // 0] | add // 0) \([.[] | select((.restartCount // 0) > 0 and (.runningState == "Waiting" or .runningState == "Terminated"))] | length)"
        end' 2>/dev/null || true
}

logs_hint="Logs: az containerapp logs show -n $app -g $RESOURCE_GROUP --revision $name --tail 100"
read -r baseline down <<<"$(restart_state)" || true
if ! [[ "${baseline:-}" =~ ^[0-9]+$ ]]; then
  echo "$app: replica data of $name unreadable; skipping the crash-loop check."
elif [ "$baseline" -eq 0 ]; then
  echo "$app: no container of $name has restarted."
else
  echo "::warning::$app: containers of $name have restarted $baseline time(s). Watching for ${watch_seconds}s — a startup hiccup stops there, a crash loop keeps going."
  started=$(date +%s)
  while true; do
    sleep "$poll_seconds"
    elapsed=$(( $(date +%s) - started ))
    read -r restarts now_down <<<"$(restart_state)" || true
    if [[ "${restarts:-}" =~ ^[0-9]+$ ]]; then
      down=$now_down
      echo "  ${elapsed}s: restarts=$restarts, restarted containers not running: $down"
      if [ "$restarts" -gt "$baseline" ]; then
        echo "::error::$app: containers of $name restarted again while being watched ($baseline -> $restarts) — a crash loop. $logs_hint"
        revision_table
        exit 1
      fi
    else
      echo "  ${elapsed}s: replica data unreadable"
    fi
    if [ "$elapsed" -ge "$watch_seconds" ]; then
      break
    fi
  done
  if [ "$down" -gt 0 ]; then
    echo "::error::$app: $down container(s) of $name restarted and are still not running after ${watch_seconds}s — a crash loop in its restart back-off. $logs_hint"
    revision_table
    exit 1
  fi
  echo "$app: the restart count held at $baseline for ${watch_seconds}s and every container is running — a startup restart, not a crash loop."
fi

# 4) Best effort: let the replaced revision deactivate before the caller rolls
#    the next app, so old + new replicas of BOTH apps never hold Postgres
#    connections at the same time. Never fails the deploy — the roll is proven.
started=$(date +%s)
while true; do
  others=$(az containerapp revision list -n "$app" -g "$RESOURCE_GROUP" \
    --query "length([?name!='$name'])" -o tsv || true)
  if [ "$others" = "0" ]; then
    echo "$app: $name is the only active revision."
    exit 0
  fi
  if [ $(( $(date +%s) - started )) -ge "$drain_seconds" ]; then
    echo "::warning::$app: ${others:-?} older revision(s) still active after ${drain_seconds}s; continuing."
    revision_table
    exit 0
  fi
  sleep "$poll_seconds"
done
