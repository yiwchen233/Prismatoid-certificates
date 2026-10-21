"""LP assembly and solver backends retained from the original batch adapter."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import os, json
import numpy as np


def _env_int(name: str, default: int) -> int:
    text = os.environ.get(name)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {text!r}") from exc

def _env_float(name: str, default: float) -> float:
    text = os.environ.get(name)
    if text is None:
        return default
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {text!r}") from exc

@dataclass
class _LPSolveResult:
    feasible: bool
    values: np.ndarray
    backend: str
    status: str
    metadata: dict[str, Any]

def _build_equality_system(
    *,
    column_count: int,
    by_column: dict[int, dict[int, int]],
    solve_rows: list[int],
):
    """Build ``B^T lambda = 0, sum(lambda) = 1`` as a sparse system.

    Variables are restricted to ``solve_rows``.  Monomial equations that become
    identically zero after a support restriction are omitted; this is exact and
    can substantially reduce the LP size.
    """
    try:
        from scipy import sparse
    except Exception as exc:  # pragma: no cover - exercised on the user's Sage
        raise RuntimeError(
            "SciPy is required to assemble the sparse certificate LP. "
            "Install scipy in the active Sage/Python environment."
        ) from exc

    position = {row: index for index, row in enumerate(solve_rows)}
    used_columns: list[int] = []
    eq_rows: list[int] = []
    eq_cols: list[int] = []
    eq_values: list[float] = []

    for original_column in range(column_count):
        sparse_column = by_column.get(original_column, {})
        entries = [
            (position[row], coefficient)
            for row, coefficient in sparse_column.items()
            if row in position and coefficient
        ]
        if not entries:
            continue
        equation_index = len(used_columns)
        used_columns.append(original_column)
        for variable_index, coefficient in entries:
            eq_rows.append(equation_index)
            eq_cols.append(variable_index)
            eq_values.append(float(coefficient))

    normalization_index = len(used_columns)
    eq_rows.extend([normalization_index] * len(solve_rows))
    eq_cols.extend(range(len(solve_rows)))
    eq_values.extend([1.0] * len(solve_rows))

    matrix = sparse.coo_matrix(
        (eq_values, (eq_rows, eq_cols)),
        shape=(len(used_columns) + 1, len(solve_rows)),
        dtype=float,
    ).tocsr()
    rhs = np.zeros(len(used_columns) + 1, dtype=float)
    rhs[-1] = 1.0
    return matrix, rhs, used_columns

def _solve_with_gurobipy(
    *,
    equality_matrix: Any,
    rhs: np.ndarray,
    variable_count: int,
) -> _LPSolveResult:
    """Solve through direct ``gurobipy`` with an explicit Gurobi environment.

    ``GRB_LICENSE_FILE`` is set by the batch coordinator before this child
    process starts.  Creating a fresh environment *after* that setting avoids
    accidentally reusing gurobipy's cached default environment and its
    size-limited bundled license.  License contents are never read here.
    """
    import gurobipy as gp

    started = __import__("time").monotonic()
    output_flag = 1 if _env_int("PRISMATOID_GUROBI_LOG", 3) > 0 else 0
    license_path = os.environ.get("GRB_LICENSE_FILE")
    license_source = os.environ.get(
        "PRISMATOID_GUROBI_LICENSE_SOURCE", "gurobi-default-search"
    )
    env = None
    model = None
    try:
        # empty=True lets us suppress startup output before the WLS or local
        # license is activated.  env.start() consults GRB_LICENSE_FILE.
        env = gp.Env(empty=True)
        env.setParam("OutputFlag", output_flag)
        env.start()
        model = gp.Model("prismatoid_certificate", env=env)
        model.Params.Method = _env_int("PRISMATOID_GUROBI_METHOD", 0)
        model.Params.Threads = _env_int("PRISMATOID_GUROBI_THREADS", 8)
        model.Params.OutputFlag = output_flag
        variables = model.addMVar(
            shape=variable_count,
            lb=0.0,
            ub=gp.GRB.INFINITY,
            vtype=gp.GRB.CONTINUOUS,
            name="lambda",
        )
        model.addMConstr(
            equality_matrix,
            variables,
            gp.GRB.EQUAL,
            rhs,
            name="certificate_equations",
        )
        model.setObjective(0.0, gp.GRB.MINIMIZE)
        model.optimize()
        status = int(model.Status)
        solution_count = int(model.SolCount or 0)
        metadata = {
            "gurobipy_version": ".".join(map(str, gp.gurobi.version())),
            "gurobi_status": status,
            "gurobi_solution_count": solution_count,
            "gurobi_runtime": repr(float(getattr(model, "Runtime", 0.0))),
            "gurobi_num_variables": int(model.NumVars),
            "gurobi_num_constraints": int(model.NumConstrs),
            "solver_elapsed_seconds": repr(__import__("time").monotonic() - started),
            "gurobi_license_source": license_source,
            "gurobi_license_file_configured": bool(license_path),
            "gurobi_license_path": license_path,
            "gurobi_environment_mode": "explicit-fresh-environment",
        }
        if solution_count > 0:
            values = np.asarray(variables.X, dtype=float).reshape(-1)
            return _LPSolveResult(True, values, "gurobipy", str(status), metadata)
        infeasible_statuses = {
            int(gp.GRB.INFEASIBLE),
            int(gp.GRB.INF_OR_UNBD),
        }
        if status in infeasible_statuses:
            return _LPSolveResult(
                False,
                np.zeros(variable_count, dtype=float),
                "gurobipy",
                str(status),
                metadata,
            )
        raise RuntimeError(
            f"gurobipy ended with status {status} and no feasible solution"
        )
    finally:
        if model is not None:
            try:
                model.dispose()
            except Exception:
                pass
        if env is not None:
            try:
                env.dispose()
            except Exception:
                pass

def _solve_with_scipy_highs(
    *,
    equality_matrix: Any,
    rhs: np.ndarray,
    variable_count: int,
) -> _LPSolveResult:
    """License-free fallback using SciPy's HiGHS LP interface."""
    from scipy import __version__ as scipy_version
    from scipy.optimize import linprog

    started = __import__("time").monotonic()
    tolerance = _env_float("PRISMATOID_HIGHS_FEASIBILITY_TOLERANCE", 1e-8)
    options = {
        "presolve": True,
        "disp": bool(_env_int("PRISMATOID_GUROBI_LOG", 3) > 0),
        "primal_feasibility_tolerance": tolerance,
        "dual_feasibility_tolerance": tolerance,
    }
    result = linprog(
        c=np.zeros(variable_count, dtype=float),
        A_eq=equality_matrix,
        b_eq=rhs,
        bounds=(0.0, None),
        method="highs",
        options=options,
    )
    metadata = {
        "scipy_version": scipy_version,
        "highs_status": int(result.status),
        "highs_message": str(result.message),
        "highs_iterations": int(getattr(result, "nit", 0) or 0),
        "solver_elapsed_seconds": repr(__import__("time").monotonic() - started),
        "highs_num_variables": variable_count,
        "highs_num_constraints": int(equality_matrix.shape[0]),
    }
    if bool(result.success):
        return _LPSolveResult(
            True,
            np.asarray(result.x, dtype=float).reshape(-1),
            "scipy-highs",
            str(result.status),
            metadata,
        )
    if int(result.status) == 2:  # HiGHS reports infeasibility.
        return _LPSolveResult(
            False,
            np.zeros(variable_count, dtype=float),
            "scipy-highs",
            str(result.status),
            metadata,
        )
    raise RuntimeError(
        f"SciPy/HiGHS did not complete the certificate LP: status={result.status}; {result.message}"
    )

def _solve_certificate_lp(
    *,
    equality_matrix: Any,
    rhs: np.ndarray,
    variable_count: int,
    logger: Any,
) -> _LPSolveResult:
    requested = os.environ.get("PRISMATOID_LP_SOLVER", "auto").strip().lower()
    aliases = {
        "highs": "scipy-highs",
        "scipy": "scipy-highs",
        "gp": "gurobipy",
        "gurobi": "gurobipy",
    }
    requested = aliases.get(requested, requested)
    if requested not in {"auto", "gurobipy", "scipy-highs"}:
        raise ValueError(
            "PRISMATOID_LP_SOLVER must be one of auto, gurobipy, or scipy-highs; "
            f"got {requested!r}"
        )

    failures: list[dict[str, str]] = []
    if requested in {"auto", "gurobipy"}:
        logger.info("Batch LP backend attempt: direct gurobipy (Sage Gurobi backend bypassed).")
        try:
            result = _solve_with_gurobipy(
                equality_matrix=equality_matrix,
                rhs=rhs,
                variable_count=variable_count,
            )
            result.metadata["backend_failures_before_success"] = failures
            return result
        except Exception as exc:
            failure = {
                "backend": "gurobipy",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            failures.append(failure)
            logger.warning(
                "Direct gurobipy failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            if requested == "gurobipy":
                raise
            logger.info("Falling back to the license-free SciPy/HiGHS LP solver.")

    try:
        result = _solve_with_scipy_highs(
            equality_matrix=equality_matrix,
            rhs=rhs,
            variable_count=variable_count,
        )
        result.metadata["backend_failures_before_success"] = failures
        return result
    except Exception as exc:
        if requested == "scipy-highs":
            raise
        failures.append({
            "backend": "scipy-highs",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise RuntimeError(
            "No LP backend completed successfully. Attempts: "
            + json.dumps(failures, sort_keys=True)
        ) from exc