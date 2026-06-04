#!/usr/bin/env bash
# Local CI entrypoint. Single source of truth for the check suite.
#
# Usage:
#   ./scripts/ci.sh              run all checks
#   ./scripts/ci.sh fmt          run only ruff format check
#   ./scripts/ci.sh lint         run only ruff lint
#   ./scripts/ci.sh type         run only pyright
#   ./scripts/ci.sh test         run only pytest
#   ./scripts/ci.sh slow         run only the slow pytest suite (downloads fastembed model)
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

run_fmt() {
    echo "==> ruff format --check"
    uv run ruff format --check src tests
}

run_lint() {
    echo "==> ruff check"
    uv run ruff check src tests
}

run_type() {
    echo "==> pyright"
    uv run pyright
}

run_test() {
    echo "==> pytest"
    uv run pytest
}

run_slow() {
    echo "==> pytest -m slow"
    uv run pytest -m slow
}

case "${1:-all}" in
    fmt)  run_fmt ;;
    lint) run_lint ;;
    type) run_type ;;
    test) run_test ;;
    slow) run_slow ;;
    all)
        run_fmt
        run_lint
        run_type
        run_test
        ;;
    *)
        echo "Unknown target: $1" >&2
        echo "Usage: $0 [fmt|lint|type|test|slow|all]" >&2
        exit 2
        ;;
esac

echo "==> CI OK"
