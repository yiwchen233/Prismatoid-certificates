#!/usr/bin/env bash
# Sage-safe launcher for the prismatoid batch pipeline.
#
# Arguments are forwarded through environment variables because some Sage
# front ends consume option-style script arguments. Relative paths are anchored
# to the directory from which this launcher was invoked.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CALLER_CWD="$(pwd -P)"
SAGE_BIN="${SAGE_BIN:-sage}"

# This versioned launcher is intentionally distinct from every earlier overlay.
# Report its identity without starting Sage so stale-installation checks are reliable.
if [[ "${1:-}" == "--version" || "${1:-}" == "version" ]]; then
    printf 'prismatoid-batch 1.2.9-core-patch\nlauncher=%s\nparser=%s\n' \
        "$SCRIPT_DIR/run_prismatoid_batch.sh" \
        "$SCRIPT_DIR/prismatoid_batch/cli.py"
    exit 0
fi

# Prefer the user's Sage; the exact Python backend runs the same patched class.
if [[ -n "${PRISMATOID_PYTHON:-}" ]]; then
    SAGE_PATH="$(command -v -- "$PRISMATOID_PYTHON")"
elif SAGE_PATH="$(command -v -- "$SAGE_BIN" 2>/dev/null)"; then
    :
else
    SAGE_PATH="$(command -v python3)"
    printf 'Sage not found; using the exact Python backend: %s\n' "$SAGE_PATH"
fi

args=("$@")
output_abs=""
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[$i]}" in
        --output)
            if (( i + 1 >= ${#args[@]} )); then
                echo "ERROR: --output requires a path" >&2
                exit 2
            fi
            raw="${args[$((i + 1))]}"
            if [[ "$raw" = /* ]]; then
                output_abs="$raw"
            else
                output_abs="$CALLER_CWD/$raw"
            fi
            mkdir -p -- "$output_abs"
            output_abs="$(cd -- "$output_abs" && pwd -P)"
            args[$((i + 1))]="$output_abs"
            ;;
        --output=*)
            raw="${args[$i]#--output=}"
            if [[ "$raw" = /* ]]; then
                output_abs="$raw"
            else
                output_abs="$CALLER_CWD/$raw"
            fi
            mkdir -p -- "$output_abs"
            output_abs="$(cd -- "$output_abs" && pwd -P)"
            args[$i]="--output=$output_abs"
            ;;
    esac
done

export PRISMATOID_BATCH_CALLER_CWD="$CALLER_CWD"
export PRISMATOID_BATCH_SAGE_PATH="$SAGE_PATH"
if [[ -n "$output_abs" ]]; then
    export PRISMATOID_BATCH_OUTPUT_ABS="$output_abs"
    {
        echo "launcher_version=1.2.9-core-patch"
        echo "caller_cwd=$CALLER_CWD"
        echo "script_dir=$SCRIPT_DIR"
        echo "sage=$SAGE_PATH"
        printf 'argv='; printf '%q ' "${args[@]}"; echo
    } > "$output_abs/LAUNCHER_INFO.txt"
    printf 'prismatoid-batch 1.2.9-core-patch\nOutput directory: %s\n' "$output_abs"
else
    printf 'prismatoid-batch 1.2.9-core-patch\n'
fi

PACKAGE_DIR="$SCRIPT_DIR/prismatoid_batch"
CLI_FILE="$PACKAGE_DIR/cli.py"
if [[ ! -f "$CLI_FILE" ]]; then
    echo "ERROR: batch package is incomplete: $CLI_FILE was not found." >&2
    echo "Please extract the complete standalone ZIP, not only the launcher files." >&2
    exit 3
fi

# Sage installations differ in how they construct sys.path for scripts.  Put
# the bundle root on PYTHONPATH before Sage starts so the versioned package is
# importable even when Sage does not add the script directory to sys.path.
if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
else
    export PYTHONPATH="$SCRIPT_DIR"
fi
export PRISMATOID_BATCH_BUNDLE_ROOT="$SCRIPT_DIR"

export PRISMATOID_BATCH_ARGC="${#args[@]}"
for ((i=0; i<${#args[@]}; i++)); do
    export "PRISMATOID_BATCH_ARG_${i}=${args[$i]}"
done

exec "$SAGE_PATH" "$SCRIPT_DIR/run_prismatoid_batch.py"
