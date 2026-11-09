#!/usr/bin/env bash
# check-drift.sh against throwaway repositories whose commits carry chosen
# dates: what counts as an undeployed change, and when it starts to fail.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
script="$here/../check-drift.sh"
# shellcheck source=.github/scripts/tests/lib.sh
source "$here/lib.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Nothing from the machine's own git setup (signing, hooks, templates).
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.invalid
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.invalid

repo=""
deployed=""

touch_files() { # <text> <file>...
  local text=$1 file
  shift
  for file in "$@"; do
    mkdir -p "$repo/$(dirname "$file")"
    echo "$text" >> "$repo/$file"
  done
  git -C "$repo" add -A
}

dated() { # <age in hours> <git command...>: run it with that commit date
  local when
  when="$(( $(date +%s) - $1 * 3600 )) +0000"
  shift
  GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" "$@"
}

land() { # <age in hours> <subject> <file>...: a commit straight onto main
  local age=$1 subject=$2
  shift 2
  touch_files "$subject" "$@"
  dated "$age" git -C "$repo" commit -q -m "$subject"
  git -C "$repo" update-ref refs/remotes/origin/main main
}

new_repo() { # main with one 30-day-old commit — the one that is deployed
  repo=$(mktemp -d "$tmp/repo.XXXXXX")
  git -C "$repo" init -q -b main
  land 720 "deployed" backend/app.py frontend/app/page.tsx
  deployed=$(git -C "$repo" rev-parse HEAD)
}

backend_drift() { # [sha]: check backend/ the way monitor.yml does
  (cd "$repo" && bash "$script" "Backend (api + worker)" "${1-$deployed}" backend/ deploy-backend.yml)
}

begin "nothing landed since the deployed commit"
new_repo
run backend_drift
expect_exit 0
expect_out "is current"
finish

begin "old code change: stale"
new_repo
land 408 "fix the renderer" backend/rendering/local_runner.py
run backend_drift
expect_exit 1
expect_out "fix the renderer"
expect_out "::error::Backend (api + worker) is stale: 1 change(s)"
expect_out "Fix: gh workflow run deploy-backend.yml --ref main"
finish

begin "recent code change: inside the grace"
new_repo
land 2 "fix the renderer" backend/rendering/local_runner.py
run backend_drift
expect_exit 0
expect_out "within the 24h merge-then-deploy grace"
refute_out "::error::"
finish

# The prompts are Markdown, ship in the image and are read at runtime
# (agents/base.py). Excluding "*.md" kept the monitor green on this for good.
begin "old prompt-only change: stale (prompts are runtime files)"
new_repo
land 408 "tune the manim prompt" backend/prompts/manim_generator.md
run backend_drift
expect_exit 1
expect_out "tune the manim prompt"
expect_out "is stale"
finish

begin "old system-prompt change in a nested directory: stale"
new_repo
land 408 "trim the manim reference" backend/prompts/system/manim_reference.md
run backend_drift
expect_exit 1
expect_out "trim the manim reference"
finish

begin "old docs-only change: not drift"
new_repo
land 408 "docs pass" backend/README.md backend/CLAUDE.md backend/evals/README.md \
  backend/tools/pipeline-tests/TESTING_GUIDE.md
run backend_drift
expect_exit 0
expect_out "is current"
refute_out "docs pass"
finish

begin "old change to docs AND code in one commit: stale"
new_repo
land 408 "feature with its docs" backend/README.md backend/api/routes.py
run backend_drift
expect_exit 1
expect_out "feature with its docs"
finish

begin "old change outside the path: not this deployable's drift"
new_repo
land 408 "restyle the reader" frontend/app/page.tsx
run backend_drift
expect_exit 0
expect_out "is current"
finish

# Age is when the change LANDED on main (--first-parent), not when the PR's
# own commits were written.
begin "PR written long ago, merged just now: inside the grace"
new_repo
git -C "$repo" checkout -q -b pr
touch_files "old work" backend/api/routes.py
dated 408 git -C "$repo" commit -q -m "old work on a branch"
git -C "$repo" checkout -q main
dated 2 git -C "$repo" merge -q --no-ff -m "Merge pull request #1" pr
git -C "$repo" update-ref refs/remotes/origin/main main
run backend_drift
expect_exit 0
expect_out "1 change(s)"
expect_out "Merge pull request #1"
expect_out "within the 24h"
finish

begin "deployed from a branch: not a commit on main"
new_repo
git -C "$repo" checkout -q -b side
touch_files "hotfix" backend/app.py
dated 3 git -C "$repo" commit -q -m "hand-deployed hotfix"
side=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" checkout -q main
run backend_drift "$side"
expect_exit 1
expect_out "is not a commit on main"
finish

begin "unknown commit"
new_repo
run backend_drift 0123456789abcdef0123456789abcdef01234567
expect_exit 1
expect_out "is not a commit on main"
finish

begin "deployed commit unreadable"
new_repo
run backend_drift ""
expect_exit 1
expect_out "could not determine the deployed commit (got '<nothing>')"
finish

begin "hand-made tag instead of a sha"
new_repo
run backend_drift "latest"
expect_exit 1
expect_out "could not determine the deployed commit (got 'latest')"
finish

summary
