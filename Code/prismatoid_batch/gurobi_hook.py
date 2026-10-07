from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import threading
import traceback

_INSTALLED = False
_LOCK = threading.Lock()
_COUNTER = 0


def _safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _number(value) -> str:
    try:
        return repr(float(value))
    except Exception:
        return str(value)


def capture_model(model, phase: str, index: int, capture_dir: Path, extra_metadata: dict[str, Any] | None = None) -> Path:
    model.update()
    variables = []
    for variable in model.getVars():
        item = {
            "name": str(_safe_attr(variable, "VarName", f"x{len(variables)}")),
            "lb": _number(_safe_attr(variable, "LB", 0)),
            "ub": _number(_safe_attr(variable, "UB", 1e100)),
            "vtype": str(_safe_attr(variable, "VType", "C")),
            "objective": _number(_safe_attr(variable, "Obj", 0)),
            "value": None,
        }
        try:
            if int(_safe_attr(model, "SolCount", 0) or 0) > 0:
                item["value"] = _number(variable.X)
        except Exception:
            pass
        variables.append(item)
    constraints = []
    unsupported = []
    for constraint in model.getConstrs():
        row = model.getRow(constraint)
        coeffs = {}
        for i in range(row.size()):
            coeffs[str(row.getVar(i).VarName)] = _number(row.getCoeff(i))
        constraints.append({
            "name": str(_safe_attr(constraint, "ConstrName", f"c{len(constraints)}")),
            "sense": str(_safe_attr(constraint, "Sense", "=")),
            "rhs": _number(_safe_attr(constraint, "RHS", 0)),
            "coefficients": coeffs,
        })
    try:
        if model.NumQConstrs:
            unsupported.append(f"{model.NumQConstrs} quadratic constraints were not serialized")
    except Exception:
        pass
    try:
        if model.NumSOS:
            unsupported.append(f"{model.NumSOS} SOS constraints were not serialized")
    except Exception:
        pass
    try:
        if model.NumGenConstrs:
            unsupported.append(f"{model.NumGenConstrs} general constraints were not serialized")
    except Exception:
        pass
    payload = {
        "format_version": 1,
        "phase": phase,
        "name": str(_safe_attr(model, "ModelName", "model")),
        "variables": variables,
        "constraints": constraints,
        "status": _safe_attr(model, "Status", None),
        "solution_count": int(_safe_attr(model, "SolCount", 0) or 0),
        "objective_value": _number(_safe_attr(model, "ObjVal", 0)) if int(_safe_attr(model, "SolCount", 0) or 0) > 0 else None,
        "optimize_index": index,
        "unsupported_features": unsupported,
        "metadata": {"candidate_id": os.environ.get("PRISMATOID_CANDIDATE_ID", ""), **(extra_metadata or {})},
    }
    capture_dir.mkdir(parents=True, exist_ok=True)
    path = capture_dir / f"model_{index:03d}_{phase}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import gurobipy as gp
    except Exception:
        return False
    original_optimize = gp.Model.optimize

    def wrapped_optimize(model, *args, **kwargs):
        global _COUNTER
        with _LOCK:
            _COUNTER += 1
            index = _COUNTER
        capture_dir = Path(os.environ.get("PRISMATOID_CAPTURE_DIR", ".prismatoid_capture"))
        restriction_metadata = {"restriction_attempted": False, "restriction_fallback": False, "allowed_variable_count": None}
        try:
            capture_model(model, "pre", index, capture_dir, restriction_metadata)
        except Exception:
            (capture_dir / f"model_{index:03d}_pre_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if os.environ.get("PRISMATOID_CAPTURE_ONLY") == "1":
            # An ordinary exception lets the wrapper stop before solving while still
            # permitting a clean diagnostic if legacy code catches it.
            raise RuntimeError("PRISMATOID_CAPTURE_ONLY")
        allowed_path = os.environ.get("PRISMATOID_ALLOWED_VARIABLES")
        old_bounds = {}
        restricted = False
        if allowed_path:
            try:
                allowed = set(json.loads(Path(allowed_path).read_text(encoding="utf-8")))
                restriction_metadata["restriction_attempted"] = True
                restriction_metadata["allowed_variable_count"] = len(allowed)
                for variable in model.getVars():
                    name = str(variable.VarName)
                    if name not in allowed and float(variable.LB) <= 0 <= float(variable.UB):
                        old_bounds[name] = (float(variable.LB), float(variable.UB))
                        variable.LB = 0
                        variable.UB = 0
                model.update()
                restricted = bool(old_bounds)
            except Exception:
                (capture_dir / f"model_{index:03d}_restriction_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        result = original_optimize(model, *args, **kwargs)
        try:
            feasible = int(model.SolCount or 0) > 0
        except Exception:
            feasible = False
        if restricted and not feasible:
            restriction_metadata["restriction_fallback"] = True
            # A template is only a search restriction. If it fails, restore the full
            # LP and let the original computation proceed unrestricted.
            for variable in model.getVars():
                if variable.VarName in old_bounds:
                    variable.LB, variable.UB = old_bounds[variable.VarName]
            model.update()
            result = original_optimize(model, *args, **kwargs)
        try:
            capture_model(model, "post", index, capture_dir, restriction_metadata)
        except Exception:
            capture_dir.mkdir(parents=True, exist_ok=True)
            (capture_dir / f"model_{index:03d}_post_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return result

    gp.Model.optimize = wrapped_optimize
    _INSTALLED = True
    return True
