# Sourced by the *.test.sh files: run a command, assert on its exit code and
# output, print one line per case (and the captured output when a case fails).
#
#   begin "<case name>"
#   run <command> [args...]        # leaves $out (stdout+stderr) and $code
#   expect_exit 1
#   expect_out "text that must appear"
#   refute_out "text that must not"
#   finish
#
# The file ends with `summary`, whose exit code is the file's verdict.

tests_run=0
tests_failed=0
case_name=""
case_errors=""
out=""
code=0

begin() {
  case_name=$1
  case_errors=""
  tests_run=$((tests_run + 1))
}

run() {
  set +e
  out=$("$@" 2>&1)
  code=$?
  set -e
}

expect_exit() {
  if [ "$code" -ne "$1" ]; then
    case_errors="${case_errors}    exit code $code, expected $1"$'\n'
  fi
}

expect_out() {
  if ! grep -qF -- "$1" <<<"$out"; then
    case_errors="${case_errors}    output does not contain: $1"$'\n'
  fi
}

refute_out() {
  if grep -qF -- "$1" <<<"$out"; then
    case_errors="${case_errors}    output must not contain: $1"$'\n'
  fi
}

finish() {
  if [ -z "$case_errors" ]; then
    echo "ok    $case_name"
    return
  fi
  tests_failed=$((tests_failed + 1))
  echo "FAIL  $case_name"
  printf '%s' "$case_errors"
  echo "    --- output ---"
  sed 's/^/    | /' <<<"$out"
}

summary() {
  echo "$((tests_run - tests_failed))/$tests_run passed"
  [ "$tests_failed" -eq 0 ]
}
