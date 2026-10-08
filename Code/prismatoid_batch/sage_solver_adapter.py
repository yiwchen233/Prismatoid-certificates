from __future__ import annotations

"""Programmatic adapter for the project's ``NonRealizabilityTest`` class.

The legacy command-line interface accepts facet data only as a Python literal on
``--facets``.  Passing a prepared filename as a positional argument therefore
cannot work.  This adapter imports the legacy module inside Sage, instantiates
its test class with the prepared facets, and overrides only the LP-output layer
so the batch coordinator receives a machine-verifiable rational certificate
model.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
import importlib.util
import json
import os
import re
import sys
import traceback

import numpy as np

from prismatoid_batch.facet_io import read_facets
from prismatoid_batch.flag_search import parse_flag_indices


_CAPTURE_VERSION = 2


class CaptureOnlyComplete(RuntimeError):
    """Raised after the coefficient LP has been serialized without solving."""


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


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


_LEGACY_SEARCH_VARIANT = "legacy"
_EXTENDED_SEARCH_VARIANT = "all-variable-products-simplified"


def _search_variant() -> str:
    raw = os.environ.get("PRISMATOID_SEARCH_VARIANT", _LEGACY_SEARCH_VARIANT)
    value = raw.strip().lower()
    aliases = {
        "extended": _EXTENDED_SEARCH_VARIANT,
        "all-variable-products": _EXTENDED_SEARCH_VARIANT,
        "all-products-simplified": _EXTENDED_SEARCH_VARIANT,
    }
    value = aliases.get(value, value)
    if value not in {_LEGACY_SEARCH_VARIANT, _EXTENDED_SEARCH_VARIANT}:
        raise ValueError(
            "PRISMATOID_SEARCH_VARIANT must be 'legacy' or "
            f"'{_EXTENDED_SEARCH_VARIANT}', got {raw!r}"
        )
    return value


def _variable_provenance(variable: Any, position: int) -> list[Any]:
    """Match the legacy metadata used when reduced-slack variables are appended."""
    match = re.search(r"(-?\d+)$", str(variable))
    variable_index = int(match.group(1)) if match else position + 1
    return [[(-variable_index, -variable_index)], 1]


def _coerce_positive_generators_to_active_ring(
    test: Any, constraint_dict: dict[Any, Any]
) -> tuple[dict[Any, Any], dict[str, int]]:
    """Coerce reconstructed entries and add every positive ring variable.

    The legacy routine changes ``self.R`` immediately before product generation.
    Reconstructed entries can still belong to the earlier polynomial ring, so an
    explicit coercion is required before multiplying them by generators of the
    active reduced-slack ring.
    """
    augmented: dict[Any, Any] = {}
    coercion_collisions = 0
    for polynomial, provenance in constraint_dict.items():
        try:
            coerced = test.R(polynomial)
        except Exception:
            try:
                coerced = test.R(str(polynomial))
            except Exception as exc:
                raise RuntimeError(
                    "could not coerce a reconstructed positive polynomial into "
                    f"the active reduced-slack ring: {polynomial}"
                ) from exc
        if coerced in augmented:
            coercion_collisions += 1
            continue
        augmented[coerced] = provenance

    variables = list(test.R.gens())
    variables_added = 0
    variables_already_present = 0
    for position, variable in enumerate(variables):
        if variable in augmented:
            variables_already_present += 1
            continue
        augmented[variable] = _variable_provenance(variable, position)
        variables_added += 1

    statistics = {
        "reconstructed_generator_count_before_coercion": len(constraint_dict),
        "reconstructed_generator_count_after_coercion": len(augmented) - variables_added,
        "reconstructed_generator_coercion_collisions": coercion_collisions,
        "reduced_slack_variable_count": len(variables),
        "reduced_slack_variables_added": variables_added,
        "reduced_slack_variables_already_present": variables_already_present,
        "base_generator_count_with_variables": len(augmented),
    }
    return augmented, statistics


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    try:
        return [_json_safe(item) for item in value]
    except (TypeError, ValueError):
        return repr(value)


def _flag_search_metadata(test: Any) -> dict[str, Any]:
    selected_values: dict[str, Any] = {}
    for attribute in ("flag", "flag_old", "flag_indices", "selected_flag", "chosen_flag"):
        if hasattr(test, attribute):
            selected_values[attribute] = _json_safe(getattr(test, attribute))

    selected_indices = None
    for value in selected_values.values():
        selected_indices = parse_flag_indices(value)
        if selected_indices is not None:
            break

    return {
        "attempt_index_zero_based": int(
            getattr(test, "_batch_flag_attempt_index", 0)
        ),
        "source": str(getattr(test, "_batch_flag_source", "legacy-default")),
        "requested_flag": str(getattr(test, "_batch_requested_flag", "{}")),
        "force_new_flag": bool(getattr(test, "_batch_force_new_flag", False)),
        "random_seed": int(getattr(test, "_batch_flag_random_seed", 0)),
        "selected_flag_indices_zero_based": (
            list(selected_indices) if selected_indices is not None else None
        ),
        "legacy_flag_attributes": selected_values,
    }


def _batch_search_metadata(test: Any) -> dict[str, Any]:
    variant = getattr(test, "_batch_search_variant", _LEGACY_SEARCH_VARIANT)
    return {
        "search_variant": variant,
        "all_variable_products": bool(
            getattr(test, "_batch_all_variable_products", False)
        ),
        "monomial_simplification": bool(
            getattr(test, "_batch_monomial_simplification", False)
        ),
        "generator_statistics": dict(
            getattr(test, "_batch_generator_statistics", {})
        ),
        "flag_search": _flag_search_metadata(test),
        "generator_stages": getattr(test, 'generator_stages', []),
        "actual_generator_term_limit": getattr(test, '_generator_term_limit', None),
        "core_interface": 'prismatoid-exact-core',
    }


def _var_name(row_zero_based: int) -> str:
    # Fixed width makes lexical and numerical order agree for the entire data set.
    return f"lambda_{row_zero_based + 1:09d}"


def _load_allowed_rows(row_count: int) -> set[int] | None:
    path_text = os.environ.get("PRISMATOID_ALLOWED_VARIABLES")
    if not path_text:
        return None
    raw = json.loads(Path(path_text).read_text(encoding="utf-8"))
    allowed: set[int] = set()
    for value in raw:
        name = str(value)
        if not name.startswith("lambda_"):
            continue
        try:
            index = int(name.split("_", 1)[1]) - 1
        except ValueError:
            continue
        if 0 <= index < row_count:
            allowed.add(index)
    return allowed


def _sparse_coordinates(M: Any) -> tuple[int, int, dict[int, dict[int, int]]]:
    """Return row count, column count, and a sparse column dictionary.

    ``M`` is the legacy three-row coordinate representation with 1-based row and
    column indices.  Duplicate coordinates are summed defensively.
    """
    if M is None or len(M) != 3:
        raise ValueError("expected a three-row sparse coefficient representation")
    rows = [int(v) for v in M[0]]
    cols = [int(v) for v in M[1]]
    vals = [int(v) for v in M[2]]
    if not rows or not cols or len(rows) != len(cols) or len(rows) != len(vals):
        raise ValueError("malformed sparse coefficient representation")
    row_count = max(rows)
    column_count = max(cols)
    by_column: dict[int, dict[int, int]] = {}
    for row_one, col_one, value in zip(rows, cols, vals):
        if not value:
            continue
        row = row_one - 1
        col = col_one - 1
        column = by_column.setdefault(col, {})
        column[row] = column.get(row, 0) + value
        if column[row] == 0:
            del column[row]
    return row_count, column_count, by_column


def _row_descriptions(test: Any, active_rows: list[int]) -> dict[str, Any]:
    constraint_dict = getattr(test, "_batch_constraint_dict", None)
    if not constraint_dict or not active_rows:
        return {}
    wanted = set(active_rows)
    descriptions: dict[str, Any] = {}
    for index, (polynomial, provenance) in enumerate(constraint_dict.items()):
        if index not in wanted:
            continue
        descriptions[_var_name(index)] = {
            "row_index_zero_based": index,
            "row_index_one_based": index + 1,
            "positive_polynomial": str(polynomial),
            "provenance": str(provenance),
        }
        if len(descriptions) == len(wanted):
            break
    return descriptions


def _capture_payload(
    *,
    candidate_id: str,
    row_count: int,
    column_count: int,
    by_column: dict[int, dict[int, int]],
    rows_to_include: list[int],
    values: dict[int, float] | None,
    phase: str,
    solution_count: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    row_set = set(rows_to_include)
    variables = [
        {
            "name": _var_name(row),
            "lb": "0",
            "ub": "inf",
            "vtype": "C",
            "objective": "0",
            "value": repr(float(values[row])) if values is not None and row in values else None,
        }
        for row in rows_to_include
    ]
    constraints: list[dict[str, Any]] = []
    for col in range(column_count):
        sparse = by_column.get(col, {})
        coefficients = {
            _var_name(row): str(coefficient)
            for row, coefficient in sorted(sparse.items())
            if row in row_set and coefficient
        }
        # For a support-only post-capture, an untouched equation is identically
        # zero and can be omitted without changing the exact feasible set.
        if coefficients:
            constraints.append(
                {
                    "name": f"monomial_{col + 1:09d}",
                    "sense": "=",
                    "rhs": "0",
                    "coefficients": coefficients,
                }
            )
    if rows_to_include:
        constraints.append(
            {
                "name": "normalization",
                "sense": "=",
                "rhs": "1",
                "coefficients": {_var_name(row): "1" for row in rows_to_include},
            }
        )
    return {
        "format_version": _CAPTURE_VERSION,
        "phase": phase,
        "name": f"prismatoid_certificate_{candidate_id}",
        "variables": variables,
        "constraints": constraints,
        "status": 2 if solution_count else None,
        "solution_count": solution_count,
        "objective_value": "0" if solution_count else None,
        "optimize_index": 1,
        "unsupported_features": [],
        "metadata": {
            "candidate_id": candidate_id,
            "certificate_model": "lambda >= 0, B^T lambda = 0, sum(lambda) = 1",
            "legacy_row_count": row_count,
            "legacy_monomial_column_count": column_count,
            **metadata,
        },
    }


def _write_capture(payload: dict[str, Any], phase: str) -> Path:
    capture_dir = Path(os.environ.get("PRISMATOID_CAPTURE_DIR", ".prismatoid_capture"))
    capture_dir.mkdir(parents=True, exist_ok=True)
    target = capture_dir / f"model_001_{phase}.json"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
    return target



@dataclass
class _LPSolveResult:
    feasible: bool
    values: np.ndarray
    backend: str
    status: str
    metadata: dict[str, Any]


def _rows_for_solver(row_count: int, allowed_rows: set[int] | None) -> list[int]:
    if allowed_rows is None:
        return list(range(row_count))
    return sorted(row for row in allowed_rows if 0 <= row < row_count)


def _build_equality_system(
    *,
    column_count: int,
    by_column: dict[int, dict[int, int]],
    solve_rows: list[int],
):
    """Build ``B^T lambda = 0, sum(lambda) = 1`` as a sparse system.

    Variables are restricted to ``solve_rows``.  Monomial equations that become
    identically zero after a template restriction are omitted; this is exact and
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


def _write_legacy_certificate(
    test: Any,
    *,
    by_column: dict[int, dict[int, int]],
    column_count: int,
    lambdas: np.ndarray,
    active: list[int],
) -> str:
    """Retain the legacy certificate files without a Sage Gurobi matrix backend."""
    full = Path(test.full_file_name)
    full.parent.mkdir(parents=True, exist_ok=True)
    active_set = set(active)
    selected_columns = sorted(
        col
        for col in range(column_count)
        if any(row in active_set and coefficient for row, coefficient in by_column.get(col, {}).items())
    )
    lines = [" ".join(str(col + 1) for col in selected_columns)]
    for row in active:
        lines.append(
            " ".join(str(by_column.get(col, {}).get(row, 0)) for col in selected_columns)
        )
    certificate_text = "\n".join(lines)
    (full.parent / f"{full.name}_certificate.txt").write_text(certificate_text, encoding="utf-8")
    (full.parent / f"{full.name}_certificate_rows.txt").write_text(
        " ".join(str(row) for row in active) + "\n", encoding="utf-8"
    )
    coefficient_lines = [
        "# row_index_zero_based row_index_one_based coefficient",
        *[f"{row} {row + 1} {lambdas[row]:.17g}" for row in active],
    ]
    (full.parent / f"{full.name}_certificate_coefficients.txt").write_text(
        "\n".join(coefficient_lines) + "\n", encoding="utf-8"
    )
    return certificate_text


def _solve_lp_and_capture(test: Any, module: Any, matrix_fname: str | None = None, M: Any = None):
    if M is None:
        matrix_file_name = matrix_fname or f"{test.full_file_name}_matrix.txt"
        M = np.loadtxt(matrix_file_name).astype(np.int64)

    row_count, column_count, by_column = _sparse_coordinates(M)
    candidate_id = os.environ.get("PRISMATOID_CANDIDATE_ID", str(test.file_name_old))
    allowed_rows = _load_allowed_rows(row_count)
    capture_only = os.environ.get("PRISMATOID_CAPTURE_ONLY") == "1"

    if capture_only:
        rows = list(range(row_count))
        payload = _capture_payload(
            candidate_id=candidate_id,
            row_count=row_count,
            column_count=column_count,
            by_column=by_column,
            rows_to_include=rows,
            values=None,
            phase="pre",
            solution_count=0,
            metadata={
                "capture_only": True,
                "restriction_attempted": False,
                "full_model_capture": True,
                "lp_backend_requested": os.environ.get("PRISMATOID_LP_SOLVER", "auto"),
                **_batch_search_metadata(test),
            },
        )
        _write_capture(payload, "pre")
        raise CaptureOnlyComplete("coefficient LP captured before optimization")

    solve_rows = _rows_for_solver(row_count, allowed_rows)
    if not solve_rows:
        solve_result = _LPSolveResult(
            False,
            np.zeros(0, dtype=float),
            "none",
            "empty_restriction",
            {"empty_allowed_support": True},
        )
        used_columns: list[int] = []
        equality_shape = (1, 0)
    else:
        equality_matrix, rhs, used_columns = _build_equality_system(
            column_count=column_count,
            by_column=by_column,
            solve_rows=solve_rows,
        )
        equality_shape = equality_matrix.shape
        test.logger.info(
            "Batch normalized certificate LP: %s variables, %s equality constraints (%s nonzero monomial equations).",
            len(solve_rows),
            equality_matrix.shape[0],
            len(used_columns),
        )
        solve_result = _solve_certificate_lp(
            equality_matrix=equality_matrix,
            rhs=rhs,
            variable_count=len(solve_rows),
            logger=test.logger,
        )

    lambdas = np.zeros(row_count, dtype=float)
    if solve_result.feasible:
        for local_index, original_row in enumerate(solve_rows):
            lambdas[original_row] = float(solve_result.values[local_index])

    certificate_tolerance = _env_float("PRISMATOID_CERTIFICATE_TOLERANCE", 1e-7)
    active_tolerance = _env_float("PRISMATOID_ACTIVE_TOLERANCE", 1e-10)
    if solve_result.feasible:
        lambdas = np.where(lambdas > 0.0, lambdas, 0.0)
        total_lambda = float(np.sum(lambdas))
        if total_lambda > 0.0:
            lambdas /= total_lambda
        total_lambda = float(np.sum(lambdas))
        max_equation_residual = 0.0
        for sparse_column in by_column.values():
            residual = sum(float(coefficient) * lambdas[row] for row, coefficient in sparse_column.items())
            max_equation_residual = max(max_equation_residual, abs(residual))
        normalization_residual = abs(float(np.sum(lambdas)) - 1.0)
        if max_equation_residual > 100 * certificate_tolerance or normalization_residual > 100 * certificate_tolerance:
            raise RuntimeError(
                "LP backend returned a numerically invalid normalized certificate: "
                f"max equation residual={max_equation_residual:.3e}, "
                f"normalization residual={normalization_residual:.3e}"
            )
    else:
        total_lambda = 0.0
        max_equation_residual = 0.0
        normalization_residual = 1.0

    has_certificate = (
        solve_result.feasible
        and total_lambda >= 1.0 - certificate_tolerance
        and max_equation_residual <= 100 * certificate_tolerance
    )
    active = [i for i, value in enumerate(lambdas) if value > active_tolerance] if has_certificate else []
    computed_objective = 0.0 if has_certificate else 1.0

    test.logger.info(f"Certificate LP backend used: {solve_result.backend}")
    test.logger.info(f"Objective value: {computed_objective}")
    test.logger.info(f"Indices of nonzero certificate variables: {[i + 1 for i in active]}")

    metadata: dict[str, Any] = {
        "capture_only": False,
        "restriction_attempted": allowed_rows is not None,
        "allowed_variable_count": len(allowed_rows) if allowed_rows is not None else None,
        "lp_backend_requested": os.environ.get("PRISMATOID_LP_SOLVER", "auto"),
        "lp_backend_used": solve_result.backend,
        "lp_backend_status": solve_result.status,
        "lp_backend_metadata": solve_result.metadata,
        "computed_legacy_objective": repr(computed_objective),
        "active_tolerance": active_tolerance,
        "certificate_tolerance": certificate_tolerance,
        "solver_variable_count": len(solve_rows),
        "solver_constraint_count": int(equality_shape[0]),
        "nonzero_monomial_equation_count": len(used_columns),
        "max_equation_residual": repr(max_equation_residual),
        "normalization_residual": repr(normalization_residual),
        **_batch_search_metadata(test),
    }

    if has_certificate and active:
        if hasattr(test, 'accept_exact_solution'):
            test.accept_exact_solution(lambdas)
            metadata['core_interface'] = getattr(module, 'CORE_INTERFACE', None)
            metadata['geometric_certificate_verification'] = test.certificate_bundle['verification']
            # Preserve the complete independent witness in the captured model.
            metadata['certificate_bundle'] = test.certificate_bundle
            metadata['exact_weights'] = {str(k):v for k,v in test.exact_weights.items()}
        numeric_values = {row: float(lambdas[row]) for row in active}
        metadata["active_row_descriptions"] = _row_descriptions(test, active)
        metadata["support_only_capture"] = True
        payload = _capture_payload(
            candidate_id=candidate_id,
            row_count=row_count,
            column_count=column_count,
            by_column=by_column,
            rows_to_include=active,
            values=numeric_values,
            phase="post",
            solution_count=1,
            metadata=metadata,
        )
        _write_capture(payload, "post")
        certificate_text = _write_legacy_certificate(
            test,
            by_column=by_column,
            column_count=column_count,
            lambdas=lambdas,
            active=active,
        )
        return certificate_text, np.array(active, dtype=int)

    payload = _capture_payload(
        candidate_id=candidate_id,
        row_count=row_count,
        column_count=column_count,
        by_column={},
        rows_to_include=[],
        values=None,
        phase="post",
        solution_count=0,
        metadata={**metadata, "no_certificate_at_this_search_level": True},
    )
    _write_capture(payload, "post")
    return "", np.array([], dtype=int)

def _load_legacy_module(entrypoint: Path):
    module_name = f"_prismatoid_legacy_{entrypoint.stem}_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not create an import specification for {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def execute_nonrealizability(entrypoint: Path) -> int:
    """Run one prepared candidate through ``NonRealizabilityTest``.

    Return code zero means the computation itself completed.  Whether a
    certificate was found is communicated by the captured model's
    ``solution_count`` and by the legacy test's result field.
    """
    input_text = os.environ.get("PRISMATOID_INPUT_FILE") or os.environ.get("PRISMATOID_INPUT")
    if not input_text:
        raise RuntimeError("PRISMATOID_INPUT_FILE was not supplied by the batch runner")
    candidate_path = Path(input_text).resolve()
    candidate_id = os.environ.get("PRISMATOID_CANDIDATE_ID", candidate_path.stem)
    facets = [list(facet) for facet in read_facets(candidate_path, require_prepared=True).facets]

    entrypoint = entrypoint.resolve()
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    (entrypoint.parent / "dump").mkdir(parents=True, exist_ok=True)
    (entrypoint.parent / "logs").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(entrypoint.parent))
    try:
        with _working_directory(entrypoint.parent):
            module = _load_legacy_module(entrypoint)
            if getattr(module, 'CORE_INTERFACE', None) != 'prismatoid-exact-core':
                raise RuntimeError('The batch adapter requires the matching core/src/nonrealizability_certificate.py with CORE_INTERFACE=prismatoid-exact-core')
            if not hasattr(module, "NonRealizabilityTest"):
                raise RuntimeError(f"{entrypoint} does not define NonRealizabilityTest")

            class BatchNonRealizabilityTest(module.NonRealizabilityTest):
                def get_products(self, constraint_dict):
                    variant = getattr(
                        self, "_batch_search_variant", _LEGACY_SEARCH_VARIANT
                    )
                    if variant == _EXTENDED_SEARCH_VARIANT:
                        augmented, statistics = _coerce_positive_generators_to_active_ring(
                            self, constraint_dict
                        )
                        self.logger.info(
                            "Batch extended generator variant: %s reconstructed "
                            "generators and %s reduced-slack variables form products "
                            "together (total %s unique base generators).",
                            statistics["reconstructed_generator_count_after_coercion"],
                            statistics["reduced_slack_variable_count"],
                            statistics["base_generator_count_with_variables"],
                        )
                        products = super().get_products(augmented)
                        statistics[
                            "positive_polynomial_count_after_products_before_legacy_append"
                        ] = len(products)
                        self._batch_generator_statistics = statistics
                        return products

                    products = super().get_products(constraint_dict)
                    self._batch_generator_statistics = {
                        "reconstructed_generator_count": len(constraint_dict),
                        "reduced_slack_variable_count": len(self.R.gens()),
                        "base_generator_count_used_for_products": len(constraint_dict),
                        "positive_polynomial_count_after_products_before_legacy_append": len(products),
                    }
                    return products

                def get_coefficient_matrix(self, constraint_dict):
                    # Keep the insertion-ordered mapping by reference.  Only the
                    # few rows active in a final certificate are serialized.
                    self._batch_constraint_dict = constraint_dict
                    return super().get_coefficient_matrix(constraint_dict)

                def solve_lp(self, matrix_fname=None, M=None):
                    return _solve_lp_and_capture(self, module, matrix_fname=matrix_fname, M=M)

            search_variant = _search_variant()
            monomial_simplification = search_variant == _EXTENDED_SEARCH_VARIANT
            requested_flag = os.environ.get("PRISMATOID_FLAG", "{}")
            force_new_flag_text = os.environ.get(
                "PRISMATOID_FORCE_NEW_FLAG", "false"
            ).strip().lower()
            if force_new_flag_text not in {"true", "false"}:
                raise ValueError(
                    "PRISMATOID_FORCE_NEW_FLAG must be 'true' or 'false', got "
                    f"{force_new_flag_text!r}"
                )
            force_new_flag = force_new_flag_text == "true"
            flag_attempt_index = _env_int("PRISMATOID_FLAG_ATTEMPT_INDEX", 0)
            flag_source = os.environ.get("PRISMATOID_FLAG_SOURCE", "legacy-default")
            flag_random_seed = _env_int("PRISMATOID_RANDOM_SEED", 0)

            test = BatchNonRealizabilityTest(
                check_certificate_m2="false",
                dimension=_env_int("PRISMATOID_DIMENSION", 5),
                deep_sign_check=os.environ.get("PRISMATOID_DEEP_SIGN_CHECK", "false"),
                facets=facets,
                file_name=candidate_id,
                flag=requested_flag,
                force_new_flag="true" if force_new_flag else "false",
                gurobi_interface="sage",
                include_rows="{}",
                language="sage",
                load_data="false",
                matrix_method="sphere_new",
                max_deg=_env_int("PRISMATOID_MAX_DEG", 2),
                n_factors=_env_int("PRISMATOID_N_FACTORS", 2),
                oriented=os.environ.get("PRISMATOID_ORIENTED", "false"),
                prismatoid="true",
                random_seed=flag_random_seed,
                redundant_facets="false",
                selected_cols="{}",
                selected_rows="{}",
                shuffle_constraints=os.environ.get("PRISMATOID_SHUFFLE_CONSTRAINTS", "false"),
                sleep=0,
                small_determinants=(
                    "true"
                    if monomial_simplification
                    else os.environ.get("PRISMATOID_SMALL_DETERMINANTS", "false")
                ),
                suffix="",
                switch_to_sage="true",
            )
            test._batch_requested_flag = requested_flag
            test._batch_force_new_flag = force_new_flag
            test._batch_flag_attempt_index = flag_attempt_index
            test._batch_flag_source = flag_source
            test._batch_flag_random_seed = flag_random_seed
            test._batch_search_variant = search_variant
            # The patched core includes variables and 1 before products in both modes.
            test._batch_all_variable_products = True
            test._batch_monomial_simplification = (
                str(test.small_determinants).lower() == "true"
            )
            test.logger.info(f"Batch search variant: {search_variant}")
            test.logger.info(
                "Batch flag attempt %s: source=%s, requested=%s, force_new=%s, seed=%s",
                flag_attempt_index + 1,
                flag_source,
                requested_flag,
                force_new_flag,
                flag_random_seed,
            )
            test.logger.info(
                "Batch monomial-factor simplification: "
                + ("enabled" if test._batch_monomial_simplification else "disabled")
            )

            try:
                legacy_result = test.run
                adapter_state = {
                    "completed": True,
                    "capture_only": False,
                    "legacy_result": int(legacy_result),
                    "candidate_id": candidate_id,
                    "prepared_input": str(candidate_path),
                    "search_variant": search_variant,
                    "monomial_simplification": test._batch_monomial_simplification,
                    "all_variable_products": test._batch_all_variable_products,
                    "flag_search": _flag_search_metadata(test),
        "generator_stages": getattr(test, 'generator_stages', []),
        "actual_generator_term_limit": getattr(test, '_generator_term_limit', None),
        "core_interface": 'prismatoid-exact-core',
                }
            except CaptureOnlyComplete as exc:
                adapter_state = {
                    "completed": True,
                    "capture_only": True,
                    "legacy_result": None,
                    "message": str(exc),
                    "candidate_id": candidate_id,
                    "prepared_input": str(candidate_path),
                    "search_variant": search_variant,
                    "monomial_simplification": test._batch_monomial_simplification,
                    "all_variable_products": test._batch_all_variable_products,
                    "flag_search": _flag_search_metadata(test),
        "generator_stages": getattr(test, 'generator_stages', []),
        "actual_generator_term_limit": getattr(test, '_generator_term_limit', None),
        "core_interface": 'prismatoid-exact-core',
                }
            capture_dir = Path(os.environ.get("PRISMATOID_CAPTURE_DIR", ".prismatoid_capture"))
            capture_dir.mkdir(parents=True, exist_ok=True)
            (capture_dir / "adapter_result.json").write_text(
                json.dumps(adapter_state, indent=2, sort_keys=True), encoding="utf-8"
            )
            return 0
    finally:
        try:
            sys.path.remove(str(entrypoint.parent))
        except ValueError:
            pass


def can_handle(entrypoint: Path) -> bool:
    if entrypoint.name == "nonrealizability_certificate.py":
        return True
    try:
        text = entrypoint.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "class NonRealizabilityTest" in text


def execute_with_diagnostics(entrypoint: Path) -> int:
    try:
        return execute_nonrealizability(entrypoint)
    except Exception:
        capture_dir = Path(os.environ.get("PRISMATOID_CAPTURE_DIR", ".prismatoid_capture"))
        capture_dir.mkdir(parents=True, exist_ok=True)
        error_text = traceback.format_exc()
        (capture_dir / "adapter_error.txt").write_text(error_text, encoding="utf-8")
        traceback.print_exc()
        return 1
