from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import subprocess

from .facet_io import (
    looks_like_box_prismatoid,
    normalize_facet_file,
    prepare_box_prismatoid,
    read_facets,
)
from .helper_scripts import run_helper


@dataclass
class PrepareRecord:
    path: Path
    mode: str
    stdout: str = ""
    stderr: str = ""
    metadata: dict | None = None


def _valid_prepared(path: Path) -> bool:
    try:
        # A raw box file has a valid-looking numeric body, but its first line is a
        # header and the two bases are omitted.  It must never be accepted as an
        # already-prepared legacy input.
        if looks_like_box_prismatoid(path):
            return False
        read_facets(path, require_prepared=True)
        return True
    except Exception:
        return False


def _run_command(
    template: str,
    input_path: Path,
    output_path: Path,
    cwd: Path,
    timeout: float | None,
) -> tuple[int, str, str]:
    import shlex

    command = template.format(input=str(input_path), output=str(output_path), cwd=str(cwd))
    completed = subprocess.run(
        shlex.split(command), cwd=cwd, text=True, capture_output=True, timeout=timeout
    )
    return completed.returncode, completed.stdout, completed.stderr


def prepare_candidate(
    source: Path,
    destination: Path,
    *,
    mode: str = "auto",
    preprocess_command: str | None = None,
    reorder_command: str | None = None,
    timeout: float | None = None,
    bundled_tools_dir: Path | None = None,
) -> PrepareRecord:
    """Create a solver input without modifying the source data.

    For the uploaded box, the correct preprocessing is built in: parse the
    ``dimension facet_count`` header, restore the two omitted bases, relabel the
    used labels base-by-base to 0,...,n-1, and sort the entries of every facet.
    This reproduces the existing ``Pacos_P####`` prepared files shipped with the
    legacy project.  The supplied helper scripts remain available for other
    aggregate-list inputs, but they are not applied to the box's per-candidate
    header format.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    if looks_like_box_prismatoid(source):
        if mode == "prepared":
            raise ValueError(
                f"{source} is a raw box file: it still has the header and omits the two bases; "
                "use --prepare-mode auto or external"
            )
        metadata_path = destination.with_suffix(destination.suffix + ".meta.json")
        metadata = prepare_box_prismatoid(source, destination, metadata_path=metadata_path)
        return PrepareRecord(
            destination,
            "box-prismatoid-restored-bases-and-relabelled",
            stdout=(
                f"restored base facets 0 and 1; relabelled "
                f"{len(metadata['source_to_prepared_vertex'])} vertices; wrote "
                f"{metadata['prepared_total_facets']} facets"
            ),
            metadata=metadata,
        )

    if mode in {"prepared", "auto"} and _valid_prepared(source):
        shutil.copy2(source, destination)
        return PrepareRecord(destination, "already-prepared")
    if mode == "prepared":
        read_facets(source, require_prepared=True)

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    current = source

    if mode in {"external", "auto"}:
        if preprocess_command:
            stage = destination.with_suffix(destination.suffix + ".orientation-stage")
            code, out, err = _run_command(
                preprocess_command, current, stage, destination.parent, timeout
            )
            stdout_parts.append(out)
            stderr_parts.append(err)
            if code == 0 and stage.exists() and stage.stat().st_size:
                current = stage
            elif mode == "external":
                raise RuntimeError(
                    f"preprocessing/orientation command failed with code {code}: {err}"
                )
        elif bundled_tools_dir and (bundled_tools_dir / "preprocess_and_findorientation.py").exists():
            stage = destination.with_suffix(destination.suffix + ".orientation-stage")
            result = run_helper(
                bundled_tools_dir / "preprocess_and_findorientation.py", current, stage, timeout
            )
            stdout_parts.append(result.stdout)
            stderr_parts.append(result.stderr)
            if result.output:
                current = result.output
            elif mode == "external":
                raise RuntimeError(
                    "bundled preprocessing/orientation script could not be adapted automatically: "
                    + result.stderr
                )

        if reorder_command:
            stage = destination.with_suffix(destination.suffix + ".reorder-stage")
            code, out, err = _run_command(
                reorder_command, current, stage, destination.parent, timeout
            )
            stdout_parts.append(out)
            stderr_parts.append(err)
            if code == 0 and stage.exists() and stage.stat().st_size:
                current = stage
            elif mode == "external":
                raise RuntimeError(f"facet reorder command failed with code {code}: {err}")
        elif bundled_tools_dir and (bundled_tools_dir / "reorderfacets.py").exists():
            stage = destination.with_suffix(destination.suffix + ".reorder-stage")
            result = run_helper(bundled_tools_dir / "reorderfacets.py", current, stage, timeout)
            stdout_parts.append(result.stdout)
            stderr_parts.append(result.stderr)
            if result.output:
                current = result.output
            elif mode == "external":
                raise RuntimeError(
                    "bundled facet-reorder script could not be adapted automatically: "
                    + result.stderr
                )

    if _valid_prepared(current):
        shutil.copy2(current, destination)
        return PrepareRecord(
            destination,
            "orientation-tools",
            "\n".join(stdout_parts),
            "\n".join(stderr_parts),
        )
    normalize_facet_file(current, destination)
    return PrepareRecord(
        destination,
        "normalized-format-only",
        "\n".join(stdout_parts),
        "\n".join(stderr_parts),
    )
