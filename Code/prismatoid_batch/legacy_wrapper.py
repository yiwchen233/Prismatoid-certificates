from __future__ import annotations

from pathlib import Path
import argparse
import os
import runpy
import sys
import traceback

from prismatoid_batch.gurobi_hook import install
from prismatoid_batch.sage_solver_adapter import can_handle, execute_with_diagnostics


def execute_script(path: Path, forwarded: list[str]) -> int:
    # The shipped nonrealizability_certificate.py does not accept an input
    # filename positionally.  Use the programmatic Sage adapter for that class;
    # retain the generic runpy/Gurobi-hook path for unrelated legacy scripts.
    if can_handle(path):
        return execute_with_diagnostics(path)

    install()
    sys.argv = [str(path)] + forwarded
    try:
        if path.suffix.lower() == ".sage":
            try:
                from sage.repl.preparse import preparse_file
                source = path.read_text(encoding="utf-8")
                code = compile(preparse_file(source), str(path), "exec")
                namespace = {"__name__": "__main__", "__file__": str(path)}
                exec(code, namespace, namespace)
            except ImportError:
                raise RuntimeError("A .sage entry point requires SageMath")
        else:
            runpy.run_path(str(path), run_name="__main__")
        return 0
    except RuntimeError as exc:
        if str(exc) == "PRISMATOID_CAPTURE_ONLY":
            return 86
        traceback.print_exc()
        return 1
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) else 1
    except Exception:
        traceback.print_exc()
        return 1


def _environment_argv(prefix: str) -> list[str] | None:
    count_text = os.environ.get(f"{prefix}_ARGC")
    if count_text is None:
        return None
    try:
        count = int(count_text)
    except ValueError as exc:
        raise RuntimeError(f"invalid {prefix}_ARGC={count_text!r}") from exc
    values = []
    for index in range(count):
        name = f"{prefix}_ARG_{index}"
        if name not in os.environ:
            raise RuntimeError(f"missing launcher environment variable {name}")
        values.append(os.environ[name])
    return values


def main(argv=None) -> int:
    if argv is None:
        argv = _environment_argv("PRISMATOID_LEGACY")
    parser = argparse.ArgumentParser()
    parser.add_argument("entrypoint", type=Path)
    parser.add_argument("forwarded", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    return execute_script(args.entrypoint.resolve(), args.forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
