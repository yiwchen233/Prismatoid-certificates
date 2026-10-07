"""Sage-safe command-line launcher for the prismatoid batch pipeline."""

from pathlib import Path
import os
import sys
import traceback


def _environment_argv(prefix: str):
    count_text = os.environ.get(f"{prefix}_ARGC")
    if count_text is None:
        return None
    try:
        count = int(count_text)
    except ValueError as exc:
        raise RuntimeError(f"invalid {prefix}_ARGC={count_text!r}") from exc
    if count < 0:
        raise RuntimeError(f"invalid negative {prefix}_ARGC={count}")
    values = []
    for index in range(count):
        name = f"{prefix}_ARG_{index}"
        if name not in os.environ:
            raise RuntimeError(f"missing launcher environment variable {name}")
        values.append(os.environ[name])
    return values


def _write_fatal_error(text: str) -> None:
    output = os.environ.get("PRISMATOID_BATCH_OUTPUT_ABS")
    if not output:
        return
    try:
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        (path / "FATAL_ERROR.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


def _run() -> int:
    caller = os.environ.get("PRISMATOID_BATCH_CALLER_CWD")
    if caller:
        os.chdir(caller)

    bundle_root = Path(os.environ.get("PRISMATOID_BATCH_BUNDLE_ROOT", Path(__file__).resolve().parent)).resolve()
    package_dir = bundle_root / "prismatoid_batch"
    init_file = package_dir / "__init__.py"
    cli_file = package_dir / "cli.py"
    if not init_file.is_file() or not cli_file.is_file():
        raise RuntimeError(
            "incomplete standalone bundle: expected "
            f"{init_file} and {cli_file}"
        )

    # First use the ordinary import path after explicitly placing the bundle
    # root first.  This works under normal Python and most Sage installations.
    bundle_text = str(bundle_root)
    sys.path.insert(0, bundle_text)
    try:
        from prismatoid_batch.cli import main
    except ModuleNotFoundError as exc:
        # Some Sage launchers rebuild sys.path while executing a script.
        # Bootstrap the package from its absolute __init__.py path so no
        # assumption about Sage's script-directory handling remains.
        import importlib.util

        pkg_name = "prismatoid_batch"
        pkg_spec = importlib.util.spec_from_file_location(
            pkg_name,
            init_file,
            submodule_search_locations=[str(package_dir)],
        )
        if pkg_spec is None or pkg_spec.loader is None:
            raise RuntimeError(f"could not construct package spec for {init_file}") from exc
        pkg = importlib.util.module_from_spec(pkg_spec)
        sys.modules[pkg_name] = pkg
        pkg_spec.loader.exec_module(pkg)

        cli_spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.cli", cli_file
        )
        if cli_spec is None or cli_spec.loader is None:
            raise RuntimeError(f"could not construct CLI spec for {cli_file}") from exc
        cli_module = importlib.util.module_from_spec(cli_spec)
        sys.modules[f"{pkg_name}.cli"] = cli_module
        cli_spec.loader.exec_module(cli_module)
        main = cli_module.main

    forwarded = _environment_argv("PRISMATOID_BATCH")
    return int(main(forwarded) or 0)


try:
    raise SystemExit(_run())
except SystemExit:
    raise
except Exception:
    details = traceback.format_exc()
    _write_fatal_error(details)
    print(details, file=sys.stderr, flush=True)
    raise SystemExit(1)
