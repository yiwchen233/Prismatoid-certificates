from __future__ import annotations

from pathlib import Path
from typing import Any
import inspect
import runpy
import shutil
import sys


def parse_facets(path: Path) -> list[list[int]]:
    output = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        import re
        values = [int(x) for x in re.findall(r"[-+]?\d+", stripped)]
        if values:
            output.append(values)
    return output


def extract_facets(value: Any) -> list[list[int]] | None:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.exists() and path.is_file():
            return parse_facets(path)
        return None
    if isinstance(value, dict):
        for key in ("facets", "oriented_facets", "complex", "data", "result"):
            if key in value:
                found = extract_facets(value[key])
                if found:
                    return found
        return None
    if isinstance(value, tuple):
        for item in value:
            found = extract_facets(item)
            if found:
                return found
    if isinstance(value, list) and value:
        if all(isinstance(row, (list, tuple, set)) for row in value):
            try:
                return [[int(x) for x in row] for row in value]
            except Exception:
                pass
        for item in value:
            found = extract_facets(item)
            if found:
                return found
    return None


def call_function(function, input_path: Path, output_path: Path, facets: list[list[int]], current: Any) -> Any:
    signature = inspect.signature(function)
    args = []
    kwargs = {}
    for parameter in signature.parameters.values():
        name = parameter.name.lower()
        value: Any
        if any(token in name for token in ("out", "dest", "save", "write")):
            value = str(output_path)
        elif any(token in name for token in ("file", "path", "name")):
            value = str(input_path)
        elif any(token in name for token in ("facet", "complex", "sphere", "data", "poly")):
            value = current if current is not None else facets
        elif parameter.default is not inspect.Parameter.empty:
            continue
        else:
            value = current if current is not None else facets
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(value)
        elif parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            kwargs[parameter.name] = value
        elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        elif parameter.kind == inspect.Parameter.VAR_KEYWORD:
            continue
    return function(*args, **kwargs)


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    script, input_name, output_name = map(Path, argv[:3])
    namespace = runpy.run_path(str(script), run_name="__prismatoid_helper_module__")
    facets = parse_facets(input_name)
    functions = [(name, value) for name, value in namespace.items() if callable(value) and getattr(value, "__module__", None) == "__prismatoid_helper_module__"]
    priority = []
    for name, function in functions:
        lower = name.lower()
        rank = 99
        if "preprocess" in lower: rank = 0
        elif "orient" in lower: rank = 1
        elif "reorder" in lower or "sort" in lower: rank = 2
        elif "facet" in lower: rank = 3
        if rank < 99:
            priority.append((rank, name, function))
    priority.sort()
    current: Any = facets
    called = 0
    errors = []
    for _, name, function in priority:
        try:
            result = call_function(function, input_name, output_name, facets, current)
            called += 1
            if result is not None:
                current = result
            if output_name.exists() and output_name.stat().st_size:
                return 0
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    found = extract_facets(current)
    if found:
        output_name.write_text("".join(" ".join(map(str, row)) + "\n" for row in found), encoding="utf-8")
        return 0
    print("No callable helper pipeline produced facets.", file=sys.stderr)
    for error in errors:
        print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
