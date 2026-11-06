#!/usr/bin/env bash
# md_tools test runner — ONE stable, expansion-free command, so a Claude Code
# Bash permission grant covers every run.
#
# The interpreter is the one the installed `md_tools` console script runs under
# (pip wrote its path into the script's shebang at install time), so the suite
# always tests against the environment that actually serves the command.
#
# Usage:
#   bash test_scripts/run_md_tools_tests.sh                 # test the installed md_tools.py (default)
#   bash test_scripts/run_md_tools_tests.sh md_tools_v2.py  # test a dev copy mid-refactor
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="$(command -v md_tools)" || { echo "md_tools is not on PATH; run: pip install -e $REPO" >&2; exit 2; }
PY="$(sed -n '1s/^#!//p' "$CMD")"
TARGET_NAME="${1:-}"
if [ -n "$TARGET_NAME" ]; then
    export MD_TOOLS_PATH="$REPO/$TARGET_NAME"
    TARGET="$MD_TOOLS_PATH"
else
    TARGET="$REPO/md_tools.py"
fi

echo "=== pytest tests/  (python=$PY, md_tools=$TARGET) ==="
"$PY" -m pytest "$REPO/tests" -q
rc_pytest=$?

echo "=== built-in self-test: $TARGET test ==="
"$PY" "$TARGET" test
rc_self=$?

echo "=== summary: pytest rc=$rc_pytest | self-test rc=$rc_self ==="
[ "$rc_pytest" -ne 0 ] && exit "$rc_pytest"
exit "$rc_self"
