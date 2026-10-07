from __future__ import annotations

"""Secure Gurobi license discovery and subprocess configuration.

The license file is never opened, copied into a candidate sandbox, or included
in an artifact.  Only its absolute path is propagated through
``GRB_LICENSE_FILE``, which is the standard Gurobi mechanism for selecting a
license stored outside a default directory.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping
import os


@dataclass(frozen=True)
class LicenseSelection:
    path: Path | None
    source: str
    diagnostics: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return self.path is not None


def _normalise_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    text = os.path.expandvars(os.fspath(value))
    path = Path(text).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve(strict=False)


def _usable_license(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)


def resolve_gurobi_license(
    explicit: str | os.PathLike[str] | None,
    *,
    project_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LicenseSelection:
    """Locate the license file without reading its contents.

    Precedence is intentionally project-aware:

    1. ``--gurobi-license``;
    2. ``<project>/dev/gurobi.lic`` (the layout used by the supplied code);
    3. an already configured ``GRB_LICENSE_FILE``;
    4. ``<project>/gurobi.lic``;
    5. Gurobi's common Linux defaults in the user's home and ``/opt/gurobi``.

    A missing explicit path is an error.  Missing automatic candidates are
    recorded as diagnostics and otherwise ignored.
    """

    env = os.environ if environ is None else environ
    project = project_root.expanduser().resolve() if project_root is not None else None
    diagnostics: list[str] = []

    if explicit is not None:
        explicit_path = _normalise_path(explicit, base=project)
        if not explicit_path.is_file():
            raise FileNotFoundError(f"Gurobi license file does not exist: {explicit_path}")
        if not os.access(explicit_path, os.R_OK):
            raise PermissionError(f"Gurobi license file is not readable: {explicit_path}")
        return LicenseSelection(explicit_path, "command-line", tuple(diagnostics))

    candidates: list[tuple[str, Path]] = []
    if project is not None:
        candidates.append(("project-dev", project / "dev" / "gurobi.lic"))

    env_value = str(env.get("GRB_LICENSE_FILE", "")).strip()
    if env_value:
        candidates.append(("environment", _normalise_path(env_value, base=Path.cwd())))

    if project is not None:
        candidates.append(("project-root", project / "gurobi.lic"))

    home = Path.home()
    candidates.extend(
        [
            ("home-default", home / "gurobi.lic"),
            ("opt-default", Path("/opt/gurobi/gurobi.lic")),
        ]
    )

    seen: set[Path] = set()
    for source, candidate in candidates:
        candidate = candidate.expanduser().resolve(strict=False)
        if candidate in seen:
            continue
        seen.add(candidate)
        if _usable_license(candidate):
            return LicenseSelection(candidate, source, tuple(diagnostics))
        if candidate.exists() and not candidate.is_file():
            diagnostics.append(f"{source}: not a regular file: {candidate}")
        elif candidate.exists() and not os.access(candidate, os.R_OK):
            diagnostics.append(f"{source}: not readable: {candidate}")
        elif source == "environment":
            diagnostics.append(f"environment: GRB_LICENSE_FILE does not name a readable file: {candidate}")

    return LicenseSelection(None, "gurobi-default-search", tuple(diagnostics))


def apply_gurobi_license(
    selection: LicenseSelection,
    environment: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """Apply a selected path to an environment mapping.

    No license contents are read.  If no explicit file was found, the existing
    environment is left unchanged so Named-User or parameter-based setups can
    still use Gurobi's own default discovery.
    """

    target = os.environ if environment is None else environment
    target["PRISMATOID_GUROBI_LICENSE_SOURCE"] = selection.source
    if selection.path is not None:
        path_text = str(selection.path)
        target["GRB_LICENSE_FILE"] = path_text
        target["PRISMATOID_GUROBI_LICENSE_PATH"] = path_text
    else:
        target.pop("PRISMATOID_GUROBI_LICENSE_PATH", None)
    return target


def redacted_subprocess_text(text: str) -> str:
    """Remove credential-like values if a third-party error prints them."""

    redacted_lines: list[str] = []
    sensitive = ("WLSACCESSID", "WLSSECRET", "LICENSEID", "PASSWORD", "TOKENSERVER")
    for line in text.splitlines():
        upper = line.upper()
        if any(key in upper for key in sensitive):
            if "=" in line:
                line = line.split("=", 1)[0] + "=<redacted>"
            else:
                line = "<redacted Gurobi credential line>"
        redacted_lines.append(line)
    return "\n".join(redacted_lines)


def unrestricted_probe_code(variable_count: int = 2101) -> str:
    """Return a small script that exceeds the pip license's variable limit."""

    return (
        "import gurobipy as gp; "
        "env=gp.Env(empty=True); "
        "env.setParam('OutputFlag', 0); "
        "env.start(); "
        "m=gp.Model('prismatoid_license_probe', env=env); "
        "m.Params.OutputFlag=0; "
        f"x=m.addMVar({int(variable_count)}, lb=0.0, ub=1.0); "
        "m.setObjective(x.sum()); "
        "m.optimize(); "
        "print('gurobipy_version=' + '.'.join(map(str, gp.gurobi.version()))); "
        "print('gurobipy_status=' + str(m.Status)); "
        "print('gurobipy_num_variables=' + str(m.NumVars)); "
        "assert m.Status == gp.GRB.OPTIMAL; "
        "m.dispose(); env.dispose()"
    )
