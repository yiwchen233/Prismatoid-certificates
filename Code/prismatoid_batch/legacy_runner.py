from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import shlex
import time
import traceback

from .autodetect import discover_entrypoints
from .models import CapturedModel


@dataclass
class RunRecord:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    captures: list[Path]
    elapsed_seconds: float
    sandbox: Path
    artifacts: list[Path]


def _copy_candidate_to_literals(candidate: Path, sandbox_project: Path, entrypoint: Path, literals: list[str]) -> None:
    for literal in literals:
        if not literal or "{" in literal or literal.startswith(("http://", "https://")):
            continue
        target = Path(literal)
        if target.is_absolute():
            continue
        # Only redirect likely input files; avoid overwriting source/output artifacts.
        name = target.name.lower()
        if any(word in name for word in ("output", "result", "certificate", "log")):
            continue
        full = (entrypoint.parent / target).resolve()
        try:
            full.relative_to(sandbox_project.resolve())
        except ValueError:
            continue
        full.parent.mkdir(parents=True, exist_ok=True)
        if not full.exists() or full.suffix.lower() in {".txt", ".dat", ".inc", ""}:
            shutil.copy2(candidate, full)


def _patch_input_markers(entrypoint: Path, candidate: Path) -> list[str]:
    """Patch only source literals that are very likely to select the input instance.

    This occurs in the per-candidate sandbox, never in the user's source tree. The
    positional argument and environment variables remain the preferred interface.
    """
    text = entrypoint.read_text(encoding="utf-8", errors="ignore")
    original = text
    notes: list[str] = []
    marker = "__PRISMATOID_INPUT__"
    if marker in text:
        text = text.replace(marker, candidate.as_posix())
        notes.append("replaced __PRISMATOID_INPUT__ marker")

    legacy_heading = "---- RUNNING GUROBI VIA SAGE ----"
    if legacy_heading in text:
        text = text.replace(
            legacy_heading,
            "---- RUNNING CERTIFICATE LP VIA BATCH ADAPTER ----",
        )
        notes.append("updated the sandbox-only LP heading; solver logic is supplied by the batch adapter")

    # Common single-instance patterns: input_file = '...', filename = '...', etc.
    assignment = re.compile(
        r"(?m)^(?P<prefix>\s*(?P<name>[A-Za-z_]\w*)\s*=\s*)(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)(?P<tail>\s*(?:#.*)?)$"
    )
    input_tokens = ("input", "file", "filename", "fname", "path", "sphere", "prismatoid", "complex", "data")
    output_tokens = ("output", "result", "certificate", "log", "save", "write", "template")
    def replace_assignment(match):
        name = match.group("name").lower()
        value = match.group("value")
        likely_name = any(token in name for token in input_tokens) and not any(token in name for token in output_tokens)
        likely_value = bool(re.search(r"(?:^|[/\\])\d{3,}(?:\.[A-Za-z0-9]+)?$", value)) or "prismatoid" in value.lower()
        if likely_name and likely_value:
            notes.append(f"patched sandbox assignment {match.group('name')}={value!r}")
            quote = match.group("quote")
            return match.group("prefix") + quote + candidate.as_posix() + quote + match.group("tail")
        return match.group(0)
    text = assignment.sub(replace_assignment, text)

    # Top-level numeric selector such as instance = 2105 or prismatoid_id = 2105.
    stem_numbers = re.findall(r"\d+", candidate.stem)
    if stem_numbers:
        number = str(int(stem_numbers[-1]))
        selector = re.compile(r"(?m)^(?P<prefix>\s*(?P<name>(?:instance|example|prismatoid|sphere|candidate)(?:_id|_index|_number|_nr)?)\s*=\s*)\d+(?P<tail>\s*(?:#.*)?)$")
        def replace_selector(match):
            notes.append(f"patched sandbox numeric selector {match.group('name')}={number}")
            return match.group("prefix") + number + match.group("tail")
        text = selector.sub(replace_selector, text)

    if text != original:
        entrypoint.write_text(text, encoding="utf-8")
    return notes


def _load_captures(capture_dir: Path, phase: str = "post") -> list[Path]:
    return sorted(capture_dir.glob(f"model_*_{phase}.json"))


def run_legacy_solver(
    project_root: Path,
    candidate: Path,
    candidate_id: str,
    work_root: Path,
    *,
    entrypoint: Path | None = None,
    interpreter: str | None = None,
    extra_args: list[str] | None = None,
    allowed_variables: list[str] | None = None,
    capture_only: bool = False,
    timeout: float | None = None,
    keep_sandbox: bool = False,
    dimension: int = 5,
    n_factors: int = 2,
    max_deg: int = 2,
    random_seed: int = 0,
    flag: str = "{}",
    force_new_flag: bool = False,
    flag_attempt_index: int = 0,
    flag_source: str = "legacy-default",
    gurobi_threads: int = 8,
    gurobi_method: int = 0,
    gurobi_log: int = 3,
    lp_solver: str = "auto",
    search_variant: str = "legacy",
    gurobi_license: Path | None = None,
    gurobi_license_source: str = "gurobi-default-search",
) -> RunRecord:
    work_root.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix=f"{candidate_id}_", dir=work_root))
    sandbox_project = sandbox / "project"
    project_resolved = project_root.resolve()
    output_resolved = work_root.parent.resolve()

    def copy_ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {
            name
            for name in names
            if name in {".git", "__pycache__", ".prismatoid_capture"}
            or name.endswith(".pyc")
            or name.lower() == "gurobi.lic"
        }
        base = Path(directory).resolve()
        for name in names:
            child = (base / name).resolve()
            # The output directory may be inside the project.  Never copy it into
            # a sandbox located inside that same output directory.
            if child == output_resolved:
                ignored.add(name)
            if name.startswith("batch_output"):
                ignored.add(name)
        return ignored

    shutil.copytree(project_root, sandbox_project, ignore=copy_ignore)
    # The user's project may contain an older batch package.  Install this exact
    # versioned adapter alongside it in the sandbox and invoke only this namespace.
    current_package = Path(__file__).resolve().parent
    sandbox_package = sandbox_project / "prismatoid_batch"
    shutil.copytree(current_package, sandbox_package, dirs_exist_ok=True)
    if entrypoint is None:
        guesses = discover_entrypoints(sandbox_project)
        if not guesses:
            raise RuntimeError("Could not autodetect a legacy solver entry point; pass --entrypoint")
        chosen = guesses[0]
        entrypoint_in_sandbox = chosen.path
        literals = chosen.read_literals
    else:
        relative = entrypoint.resolve().relative_to(project_root.resolve())
        entrypoint_in_sandbox = sandbox_project / relative
        text = entrypoint_in_sandbox.read_text(encoding="utf-8", errors="ignore")
        from .autodetect import _read_literals
        literals = _read_literals(text)
    prepared = sandbox / "candidate.txt"
    shutil.copy2(candidate, prepared)
    patch_notes = _patch_input_markers(entrypoint_in_sandbox, prepared)
    (sandbox / "input_patch_notes.txt").write_text("\n".join(patch_notes) + ("\n" if patch_notes else ""), encoding="utf-8")
    _copy_candidate_to_literals(prepared, sandbox_project, entrypoint_in_sandbox, literals)
    capture_dir = sandbox / "capture"
    env = os.environ.copy()
    inherited_python_paths = [str(Path(item).resolve()) for item in sys.path if item]
    env.update({
        "PRISMATOID_INPUT": str(prepared),
        "PRISMATOID_INPUT_FILE": str(prepared),
        "PRISMATOID_CANDIDATE_ID": candidate_id,
        "PRISMATOID_CAPTURE_DIR": str(capture_dir),
        "PRISMATOID_DIMENSION": str(dimension),
        "PRISMATOID_N_FACTORS": str(n_factors),
        "PRISMATOID_MAX_DEG": str(max_deg),
        "PRISMATOID_RANDOM_SEED": str(random_seed),
        "PRISMATOID_FLAG": str(flag),
        "PRISMATOID_FORCE_NEW_FLAG": "true" if force_new_flag else "false",
        "PRISMATOID_FLAG_ATTEMPT_INDEX": str(flag_attempt_index),
        "PRISMATOID_FLAG_SOURCE": str(flag_source),
        "PRISMATOID_GUROBI_THREADS": str(gurobi_threads),
        "PRISMATOID_GUROBI_METHOD": str(gurobi_method),
        "PRISMATOID_GUROBI_LOG": str(gurobi_log),
        "PRISMATOID_LP_SOLVER": str(lp_solver),
        "PRISMATOID_SEARCH_VARIANT": str(search_variant),
        # Reusing sys.executable avoids a nested Sage launcher.  Carry the
        # parent's effective sys.path as well, because some Sage installations
        # inject their library paths at startup instead of exporting PYTHONPATH.
        "PYTHONPATH": os.pathsep.join(
            [str(sandbox_project), *inherited_python_paths, env.get("PYTHONPATH", "")]
        ),
    })
    # Never copy a private license into the sandbox.  Point the child process
    # at the original file through Gurobi's documented environment variable.
    if gurobi_license is not None:
        license_path = gurobi_license.expanduser().resolve()
        if not license_path.is_file():
            raise FileNotFoundError(f"Gurobi license file disappeared before solver launch: {license_path}")
        if not os.access(license_path, os.R_OK):
            raise PermissionError(f"Gurobi license file is not readable: {license_path}")
        env["GRB_LICENSE_FILE"] = str(license_path)
        env["PRISMATOID_GUROBI_LICENSE_PATH"] = str(license_path)
    env["PRISMATOID_GUROBI_LICENSE_SOURCE"] = gurobi_license_source
    if capture_only:
        env["PRISMATOID_CAPTURE_ONLY"] = "1"
    if allowed_variables is not None:
        allowed_path = sandbox / "allowed_variables.json"
        allowed_path.write_text(json.dumps(allowed_variables, indent=2), encoding="utf-8")
        env["PRISMATOID_ALLOWED_VARIABLES"] = str(allowed_path)
    wrapper = sandbox_project / "prismatoid_batch" / "legacy_wrapper.py"
    entrypoint_text = entrypoint_in_sandbox.read_text(encoding="utf-8", errors="ignore")
    requires_sage = (
        entrypoint_in_sandbox.suffix.lower() == ".sage"
        or bool(re.search(r"(?m)^\s*(?:from\s+sage(?:\.|\s)|import\s+sage(?:\.|\s|$))", entrypoint_text))
        or "sage.all" in entrypoint_text
        or "sageall" in entrypoint_text
    )

    if interpreter:
        # An explicitly requested Sage launcher is still supported.  With no
        # explicit override, however, reuse the *current* Python executable.
        # The top-level launcher is already running inside Sage, so
        # ``sys.executable`` has the same Sage modules and avoids a fragile
        # nested ``sage ...`` invocation.
        interpreter_path = Path(interpreter).expanduser()
        base = [str(interpreter_path)] if interpreter_path.exists() else shlex.split(interpreter)
        base = [part for part in base if part != "-python"]
        if not base:
            raise ValueError("--interpreter did not contain an executable")
        executable_name = Path(base[0]).name.lower()
        use_sage_script_mode = executable_name == "sage" or executable_name.startswith("sage-")
    else:
        base = [sys.executable]
        use_sage_script_mode = False

    forwarded = [str(entrypoint_in_sandbox), str(prepared)] + list(extra_args or [])
    if use_sage_script_mode:
        # Pass wrapper arguments through the environment.  Sage 10.8-style
        # front ends may consume option-looking arguments instead of forwarding
        # them to the script.  Calling Sage with only the wrapper filename avoids
        # both that parser bug and any dependency on ``sage -python``/``sage -m``.
        prefix = "PRISMATOID_LEGACY"
        for name in list(env):
            if name == f"{prefix}_ARGC" or name.startswith(f"{prefix}_ARG_"):
                env.pop(name, None)
        env[f"{prefix}_ARGC"] = str(len(forwarded))
        for index, value in enumerate(forwarded):
            env[f"{prefix}_ARG_{index}"] = value
        command = base + [str(wrapper)]
    else:
        command = base + ["-m", "prismatoid_batch.legacy_wrapper"] + forwarded
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=entrypoint_in_sandbox.parent,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimed out after {timeout} seconds"
    except OSError:
        # Preserve launch failures as ordinary per-candidate diagnostics instead
        # of losing the sandbox and collapsing to an uninformative 0.00 s error.
        returncode = 127
        stdout = ""
        stderr = traceback.format_exc()
    elapsed = time.monotonic() - started
    captures = _load_captures(capture_dir, "pre" if capture_only else "post")
    artifact_candidates: list[Path] = []
    dump_dir = entrypoint_in_sandbox.parent / "dump"
    if dump_dir.is_dir():
        patterns = [
            f"{candidate_id}_iter*_certificate*.txt",
            f"Pacos_P{candidate_id}_orientation*.txt",
        ]
        for pattern in patterns:
            artifact_candidates.extend(sorted(dump_dir.glob(pattern)))
    adapter_result = capture_dir / "adapter_result.json"
    adapter_error = capture_dir / "adapter_error.txt"
    for item in (adapter_result, adapter_error, sandbox / "input_patch_notes.txt"):
        if item.exists():
            artifact_candidates.append(item)
    artifacts = list(dict.fromkeys(path for path in artifact_candidates if path.is_file()))
    record = RunRecord(command, returncode, stdout, stderr, captures, elapsed, sandbox, artifacts)
    # Sandboxes carrying captures are retained until the coordinator copies them.
    return record


def load_best_model(captures: list[Path]) -> tuple[CapturedModel, Path] | None:
    choices = []
    for path in captures:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            model = CapturedModel.from_json(data)
            choices.append((model.solution_count > 0, len(model.variables), model.optimize_index, model, path))
        except Exception:
            continue
    if not choices:
        return None
    choices.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    _, _, _, model, path = choices[0]
    return model, path
