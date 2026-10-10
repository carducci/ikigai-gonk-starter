#!/usr/bin/env bash
# The gates CI runs, in CI's order: lint, format check, tests.
#
#   scripts/gates.sh
#
# ONE source of truth: .github/workflows/ci.yml calls this, and the justfile's `gates`
# recipe calls it locally (which is also what `just -f ~/git-personal/ikigai-devtools/justfile
# gates` runs in a repository with no Cargo.toml). Change the gates here and both follow.
#
# The tools are standard-library Python, so the only thing to find is ruff, a development
# tool: .venv/bin/ruff first, then ruff on PATH. Without it this REFUSES rather than running
# the tests alone, because a gate that silently covers less than CI is the failure it exists
# to stop. Install it with: python3 -m venv .venv && .venv/bin/pip install ruff==0.16.1
#
# The integration tests start a scratch gonk when `ikigai-gonk` and `ikigai` are on PATH,
# and skip, saying why, when they are not (as in CI).

set -u
cd "$(dirname "$0")/.." || exit 2

if [ -x .venv/bin/ruff ]; then
    RUFF=.venv/bin/ruff
elif command -v ruff >/dev/null 2>&1; then
    RUFF=ruff
else
    echo "gates: no ruff (.venv/bin/ruff or on PATH): NOTHING WAS GATED" >&2
    echo "  install with: python3 -m venv .venv && .venv/bin/pip install ruff==0.16.1" >&2
    exit 2
fi
PY=python3
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
    echo "gates: $PY is older than the 3.11 these tools need (tomllib)" >&2
    exit 2
}

echo "gates: $("$PY" --version 2>&1), $("$RUFF" --version)"
echo "-- ruff check" &&
    "$RUFF" check . &&
    echo "-- ruff format --check" &&
    "$RUFF" format --check . &&
    echo "-- unittest" &&
    "$PY" -m unittest discover -s tests -v
