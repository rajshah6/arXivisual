#!/usr/bin/env bash
# Production monitor: has main moved on from a deployed commit — and for how
# long? Called once per deployable by monitor.yml's drift job.
#
# Exits 1, with an ::error:: that names the fixing command, when changes under
# <path> landed on main more than DRIFT_GRACE_HOURS ago and are not in the
# deployed commit — or when the deployed commit cannot be placed on main at
# all. Exits 0 when it is current or still within the grace.
#
#   usage: check-drift.sh <label> <deployed sha> <path> <deploy workflow>
#   env:   DRIFT_GRACE_HOURS   a normal merge-then-deploy gap is not drift (24)
#   cwd:   the repository root of a full clone (fetch-depth: 0) with origin/main
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <label> <deployed sha> <path> <deploy workflow>" >&2
  exit 2
fi
label=$1
sha=$2
path=$3
workflow=$4
grace_hours="${DRIFT_GRACE_HOURS:-24}"
fix="Fix: gh workflow run $workflow --ref main"

# Files that change nothing a running process does. An explicit list, NOT
# "*.md": backend/prompts/**/*.md are the pipeline's LLM prompts, read at
# runtime (agents/base.py) from the image the worker runs — a prompt-only merge
# changes behaviour as much as any code, and a blanket Markdown exclude kept
# this check green on it for good. Anything not named here counts: a needless
# deploy is cheap, an undeployed prompt nobody can see is not.
docs=(
  ':(exclude,glob)**/README.md'
  ':(exclude,glob)**/CLAUDE.md'
  ':(exclude,glob)**/TESTING_GUIDE.md'
)

if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::$label: could not determine the deployed commit (got '${sha:-<nothing>}'), so drift cannot be checked. $fix"
  exit 1
fi
if ! git cat-file -e "$sha^{commit}" 2>/dev/null \
  || ! git merge-base --is-ancestor "$sha" origin/main; then
  echo "::error::$label runs $sha, which is not a commit on main (deployed by hand from a branch?). $fix"
  exit 1
fi

# --first-parent: one entry per merge INTO main, dated when it landed — a PR's
# own commits can be days older than its merge.
pending=$(git log --first-parent --format='%ct %h %s' "$sha..origin/main" -- "$path" "${docs[@]}")
if [ -z "$pending" ]; then
  echo "ok   $label: ${sha:0:7} is current — nothing under $path has landed on main since."
  exit 0
fi

oldest=$(tail -n 1 <<<"$pending" | cut -d' ' -f1)
age_hours=$(( ($(date +%s) - oldest) / 3600 ))
count=$(wc -l <<<"$pending" | tr -d ' ')
echo "$label: ${sha:0:7} is deployed; $count change(s) under $path landed on main since (oldest ${age_hours}h ago):"
cut -d' ' -f2- <<<"$pending" | sed 's/^/    /'
if [ "$age_hours" -ge "$grace_hours" ]; then
  echo "::error::$label is stale: $count change(s) under $path merged to main are not deployed, the oldest for ${age_hours}h (grace ${grace_hours}h). $fix"
  exit 1
fi
echo "     within the ${grace_hours}h merge-then-deploy grace — not failing."
