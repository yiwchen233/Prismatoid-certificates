from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


_OPEN_RE = re.compile(r"open\s*\(\s*(['\"])(?P<path>.+?)\1(?:\s*,\s*(['\"])(?P<mode>[^'\"]+)\3)?")


@dataclass
class HelperRun:
    returncode: int
    stdout: str
    stderr: str
    output: Path | None
    command: list[str]


def _patch_and_seed(script: Path, candidate: Path, requested_output: Path, sandbox: Path) -> tuple[Path, list[Path]]:
    text = script.read_text(encoding="utf-8", errors="ignore")
    source = sandbox / script.name
    seeded_outputs: list[Path] = []
    replacements: dict[str, str] = {}
    for match in _OPEN_RE.finditer(text):
        literal = match.group("path")
        mode = (match.group("mode") or "r").lower()
        path = Path(literal)
        if any(flag in mode for flag in ("w", "a", "x")):
            target = requested_output if path.is_absolute() else sandbox / path
            target.parent.mkdir(parents=True, exist_ok=True)
            seeded_outputs.append(target)
            if path.is_absolute():
                replacements[literal] = str(target)
        else:
            target = sandbox / path.name if path.is_absolute() else sandbox / path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(candidate, target)
            except shutil.SameFileError:
                pass
            if path.is_absolute():
                replacements[literal] = str(target)
    text = text.replace("__PRISMATOID_INPUT__", str(candidate)).replace("__PRISMATOID_OUTPUT__", str(requested_output))
    for old, new in replacements.items():
        text = text.replace(old, new)
    source.write_text(text, encoding="utf-8")
    return source, seeded_outputs


def run_helper(script: Path, candidate: Path, output: Path, timeout: float | None = None) -> HelperRun:
    sandbox = Path(tempfile.mkdtemp(prefix="prismatoid_helper_", dir=output.parent))
    local_input = sandbox / "input.txt"
    shutil.copy2(candidate, local_input)
    local_output = sandbox / "output.txt"
    local_script, expected_outputs = _patch_and_seed(script, local_input, local_output, sandbox)
    env = os.environ.copy()
    env.update({
        "PRISMATOID_INPUT": str(local_input),
        "PRISMATOID_INPUT_FILE": str(local_input),
        "PRISMATOID_OUTPUT": str(local_output),
        "PRISMATOID_OUTPUT_FILE": str(local_output),
    })
    source_text = local_script.read_text(encoding="utf-8", errors="ignore").lower()
    driver = Path(__file__).with_name("helper_function_driver.py")
    commands = [[sys.executable, str(driver), str(local_script), str(local_input), str(local_output)], [sys.executable, str(local_script), str(local_input), str(local_output)]]
    sage = shutil.which("sage")
    if sage:
        # Invoke Python helpers as ordinary Sage script files.  This is
        # compatible with Sage front ends that do not provide ``-python``.
        commands.append([sage, str(driver), str(local_script), str(local_input), str(local_output)])
        commands.append([sage, str(local_script), str(local_input), str(local_output)])
    attempts = []
    started = time.time()
    for command in commands:
        try:
            result = subprocess.run(command, cwd=sandbox, env=env, text=True, capture_output=True, timeout=timeout)
            attempts.append((command, result.returncode, result.stdout, result.stderr))
        except subprocess.TimeoutExpired as exc:
            attempts.append((command, 124, exc.stdout or "", (exc.stderr or "") + "\nhelper timed out"))
            continue
        # Accept the requested output or any newly written nonempty text-like file.
        candidates = [local_output] + expected_outputs
        candidates += [q for q in sandbox.rglob("*") if q.is_file() and q not in {local_input, local_script} and q.stat().st_mtime >= started - 1]
        def facet_score(q):
            if not q.exists() or not q.is_file() or q.stat().st_size == 0:
                return (-1, -1, -1)
            try:
                lines = [line.strip() for line in q.read_text(encoding="utf-8", errors="strict").splitlines() if line.strip() and not line.lstrip().startswith("#")]
                import re
                good = sum(bool(re.fullmatch(r"[\s\d+\-,:;{}\[\]()]+", line)) and len(re.findall(r"[-+]?\d+", line)) >= 2 for line in lines)
                ratio = good / max(1, len(lines))
                return (ratio, good, q.stat().st_mtime)
            except Exception:
                return (-1, -1, -1)
        candidates = sorted(set(candidates), key=facet_score, reverse=True)
        chosen = next((q for q in candidates if facet_score(q)[0] == 1 and facet_score(q)[1] >= 2), None)
        if result.returncode == 0 and chosen is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(chosen, output)
            shutil.rmtree(sandbox, ignore_errors=True)
            return HelperRun(0, result.stdout, result.stderr, output, command)
    stdout = "\n\n".join(f"$ {' '.join(cmd)}\n{out}" for cmd, _, out, _ in attempts)
    stderr = "\n\n".join(f"$ {' '.join(cmd)} [exit {code}]\n{err}" for cmd, code, _, err in attempts)
    last_command = attempts[-1][0] if attempts else []
    last_code = attempts[-1][1] if attempts else 1
    shutil.rmtree(sandbox, ignore_errors=True)
    return HelperRun(last_code, stdout, stderr, None, last_command)
