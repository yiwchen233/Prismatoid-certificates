from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import json
import re


@dataclass
class EntrypointGuess:
    path: Path
    score: int
    reasons: list[str]
    read_literals: list[str]


def _read_literals(source: str) -> list[str]:
    literals: list[str] = []
    # AST handles ordinary Python; regex also works for Sage source.
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "load", "read"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.append(arg.value)
    except SyntaxError:
        pass
    for match in re.finditer(r"(?:open|load)\s*\(\s*['\"]([^'\"]+)['\"]", source):
        literals.append(match.group(1))
    return sorted(set(literals))


def discover_entrypoints(project_root: Path) -> list[EntrypointGuess]:
    guesses: list[EntrypointGuess] = []
    for path in project_root.rglob("*"):
        if (path.suffix.lower() not in {".py", ".sage"}
                or any(part.startswith("prismatoid_batch") for part in path.parts)
                or "preprocessing" in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        score = 0
        reasons = []
        for points, needle, reason in [
            (25, "gurobipy", "imports Gurobi"),
            (18, ".optimize(", "optimizes a model"),
            (12, "certificate", "mentions certificates"),
            (9, "non-realiz", "mentions non-realizability"),
            (5, "if __name__", "has a main guard"),
            (5, "sys.argv", "accepts command-line arguments"),
            (3, "open(", "reads or writes files"),
        ]:
            if needle in lower:
                score += points
                reasons.append(reason)
        if score:
            guesses.append(EntrypointGuess(path, score, reasons, _read_literals(text)))
    return sorted(guesses, key=lambda g: (-g.score, len(g.path.parts), g.path.as_posix()))


def write_report(project_root: Path, destination: Path) -> list[EntrypointGuess]:
    guesses = discover_entrypoints(project_root)
    payload = [
        {
            "path": str(g.path.relative_to(project_root)),
            "score": g.score,
            "reasons": g.reasons,
            "read_literals": g.read_literals,
        }
        for g in guesses
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return guesses
