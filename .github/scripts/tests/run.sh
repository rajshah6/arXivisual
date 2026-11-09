#!/usr/bin/env bash
# Run every *.test.sh next to this file (CI job "Deploy & monitor script
# tests"; locally: bash .github/scripts/tests/run.sh). Needs bash, git and jq —
# no Azure login, no network: `az` is a stub and the repositories are throwaway.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=0

for script in "$here"/../*.sh; do
  if ! bash -n "$script"; then
    echo "FAIL  syntax: $script"
    failed=1
  fi
done

for test in "$here"/*.test.sh; do
  echo "── $(basename "$test")"
  if ! bash "$test"; then
    failed=1
  fi
done

exit "$failed"
