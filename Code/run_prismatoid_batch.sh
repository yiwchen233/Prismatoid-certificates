#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${PRISMATOID_PYTHON:-python3}" "$ROOT/run_prismatoid_batch.py" "$@"
