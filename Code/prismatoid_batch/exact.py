from __future__ import annotations

from fractions import Fraction
from math import isfinite
from typing import Iterable, Sequence

from .models import CapturedModel, ExactWitness, fraction_from_text, fraction_to_text

INF = None


def _frac(text, *, max_denominator: int = 10**9) -> Fraction:
    s = str(text).strip()
    if s.lower() in {"inf", "+inf", "infinity", "+infinity"}:
        raise OverflowError("positive infinity")
    if s.lower() in {"-inf", "-infinity"}:
        raise OverflowError("negative infinity")
    try:
        return Fraction(s)
    except Exception:
        return Fraction(float(s)).limit_denominator(max_denominator)


def _bound(text: str, lower: bool) -> Fraction | None:
    s = str(text).lower().strip()
    if "inf" in s:
        return None
    try:
        value = _frac(text)
    except OverflowError:
        return None
    # Gurobi uses about 1e100 as infinity.
    if abs(value) >= 10**90:
        return None
    return value


def _dot(coefficients: dict[str, str], values: dict[str, Fraction]) -> Fraction:
    return sum((_frac(c) * values.get(v, Fraction(0)) for v, c in coefficients.items()), Fraction(0))


def verify_values(model: CapturedModel, values: dict[str, Fraction]) -> tuple[bool, str]:
    errors: list[str] = []
    variables = {v.name: v for v in model.variables}
    for name, variable in variables.items():
        x = values.get(name, Fraction(0))
        lb = _bound(variable.lb, True)
        ub = _bound(variable.ub, False)
        if lb is not None and x < lb:
            errors.append(f"{name}={x} violates lower bound {lb}")
        if ub is not None and x > ub:
            errors.append(f"{name}={x} violates upper bound {ub}")
        if variable.vtype in {"B", "I"} and x.denominator != 1:
            errors.append(f"{name}={x} is not integral")
        if variable.vtype == "B" and x not in {0, 1}:
            errors.append(f"{name}={x} is not binary")
    for constraint in model.constraints:
        lhs = _dot(constraint.coefficients, values)
        rhs = _frac(constraint.rhs)
        if constraint.sense in {"=", "E"} and lhs != rhs:
            errors.append(f"{constraint.name}: {lhs} != {rhs}")
        elif constraint.sense in {"<", "<=", "L"} and lhs > rhs:
            errors.append(f"{constraint.name}: {lhs} > {rhs}")
        elif constraint.sense in {">", ">=", "G"} and lhs < rhs:
            errors.append(f"{constraint.name}: {lhs} < {rhs}")
        if len(errors) >= 12:
            break
    if errors:
        return False, "; ".join(errors)
    return True, f"all {len(model.constraints)} linear constraints and {len(model.variables)} variable domains verified exactly"


def _rref_solution(model: CapturedModel, approximate: dict[str, float], active: list[str], max_denominator: int) -> dict[str, Fraction] | None:
    try:
        import sympy as sp
    except Exception:
        return None
    names = [v.name for v in model.variables]
    active_set = set(active)
    fixed_zero = [n for n in names if n not in active_set]
    equality_rows = [c for c in model.constraints if c.sense in {"=", "E"}]
    if not equality_rows:
        return {n: Fraction(str(approximate.get(n, 0.0))).limit_denominator(max_denominator) for n in names}
    A = sp.Matrix([[sp.Rational(_frac(c.coefficients.get(n, "0")).numerator, _frac(c.coefficients.get(n, "0")).denominator) for n in active] for c in equality_rows])
    b = sp.Matrix([sp.Rational(_frac(c.rhs).numerator, _frac(c.rhs).denominator) for c in equality_rows])
    aug = A.row_join(b)
    rref, pivots = aug.rref()
    if pivots and pivots[-1] == len(active):
        return None
    pivot_cols = [p for p in pivots if p < len(active)]
    free_cols = [j for j in range(len(active)) if j not in pivot_cols]
    x = [sp.Rational(0) for _ in active]
    for j in free_cols:
        q = Fraction(str(approximate.get(active[j], 0.0))).limit_denominator(max_denominator)
        x[j] = sp.Rational(q.numerator, q.denominator)
    # Each nonzero RREF row has x_p + sum_j r_j x_j = rhs.
    for row_index, pivot_col in enumerate(pivot_cols):
        rhs = rref[row_index, len(active)]
        x[pivot_col] = rhs - sum(rref[row_index, j] * x[j] for j in free_cols)
    result = {n: Fraction(0) for n in names}
    for n, q in zip(active, x):
        result[n] = Fraction(int(q.p), int(q.q))
    return result


def rationalize_solution(model: CapturedModel, tolerance: float = 1e-8) -> ExactWitness:
    approximate = {v.name: float(v.value or 0.0) for v in model.variables}
    if model.metadata.get("support_only_capture"):
        # The adapter has already removed numerically inactive LP rows.  Retain
        # every serialized row during exact reconstruction, including a genuinely
        # small positive coefficient in a normalized certificate.
        active = [v.name for v in model.variables if approximate[v.name] != 0.0]
    else:
        active = [v.name for v in model.variables if abs(approximate[v.name]) > tolerance or (_bound(v.lb, True) is not None and _bound(v.lb, True) != 0)]
    if not active:
        return ExactWitness({}, [], False, "captured model has no nonzero solution variables")
    attempts = [10**3, 10**5, 10**7, 10**9, 10**12]
    for denominator in attempts:
        values = _rref_solution(model, approximate, active, denominator)
        if values is None:
            continue
        ok, message = verify_values(model, values)
        if ok:
            exact_objective = sum((_frac(v.objective) * values.get(v.name, Fraction(0)) for v in model.variables), Fraction(0))
            text_values = {name: fraction_to_text(value) for name, value in values.items()}
            exact_active = sorted(name for name, value in values.items() if value != 0)
            return ExactWitness(text_values, exact_active, True, message, exact_objective=fraction_to_text(exact_objective))
    naive = {name: Fraction(str(value)).limit_denominator(10**9) for name, value in approximate.items()}
    ok, message = verify_values(model, naive)
    return ExactWitness(
        {name: fraction_to_text(value) for name, value in naive.items()},
        sorted(name for name, value in naive.items() if value != 0),
        ok,
        message if ok else "could not reconstruct an exact rational feasible point from the numerical solution: " + message,
    )


def _linear_form(constraint, direction: dict[str, Fraction]) -> Fraction:
    return _dot(constraint.coefficients, direction)


def _interval_update(low, high, a: Fraction, b: Fraction, sense: str):
    """Intersect t interval with a*t sense b. None means an infinite endpoint."""
    if a == 0:
        good = (b == 0 if sense == "=" else b >= 0 if sense == "<=" else b <= 0)
        return (low, high) if good else (Fraction(1), Fraction(0))
    q = b / a
    if sense == "=":
        return (q if low is None or q > low else low, q if high is None or q < high else high)
    if sense == "<=":
        if a > 0:
            high = q if high is None or q < high else high
        else:
            low = q if low is None or q > low else low
    else:
        if a > 0:
            low = q if low is None or q > low else low
        else:
            high = q if high is None or q < high else high
    return low, high


def reduce_support(model: CapturedModel, witness: ExactWitness) -> ExactWitness:
    """Remove affine dependencies while preserving every captured LP constraint exactly.

    This is a deterministic conic/affine support reduction, not a claim of globally
    minimum cardinality. The resulting support has no removable direction found by
    the exact nullspace procedure.
    """
    if not witness.verified:
        return witness
    try:
        import sympy as sp
    except Exception:
        witness.reduction_message = "SymPy unavailable; exact support reduction skipped"
        return witness
    values = witness.fractions()
    all_names = [v.name for v in model.variables]
    iterations = 0
    while True:
        active = [n for n in all_names if values.get(n, Fraction(0)) != 0]
        if len(active) <= 1:
            break
        equality_rows = [c for c in model.constraints if c.sense in {"=", "E"}]
        A = sp.Matrix([[sp.Rational(_frac(c.coefficients.get(n, "0")).numerator, _frac(c.coefficients.get(n, "0")).denominator) for n in active] for c in equality_rows])
        nullspace = A.nullspace()
        changed = False
        for basis in nullspace:
            direction = {n: Fraction(0) for n in all_names}
            for n, q in zip(active, basis):
                direction[n] = Fraction(int(q.p), int(q.q))
            if not any(direction.values()):
                continue
            low: Fraction | None = None
            high: Fraction | None = None
            # Variable bounds.
            variables = {v.name: v for v in model.variables}
            for n in active:
                x, d = values[n], direction[n]
                if d == 0:
                    continue
                lb = _bound(variables[n].lb, True)
                ub = _bound(variables[n].ub, False)
                if lb is not None:
                    low, high = _interval_update(low, high, -d, x - lb, "<=")  # x+t d >= lb
                if ub is not None:
                    low, high = _interval_update(low, high, d, ub - x, "<=")
            # General inequalities.
            for c in model.constraints:
                if c.sense in {"=", "E"}:
                    continue
                current = _dot(c.coefficients, values)
                slope = _dot(c.coefficients, direction)
                rhs = _frac(c.rhs)
                if c.sense in {"<", "<=", "L"}:
                    low, high = _interval_update(low, high, slope, rhs - current, "<=")
                else:
                    low, high = _interval_update(low, high, slope, rhs - current, ">=")
            if low is not None and high is not None and low > high:
                continue
            # Prefer a finite nonzero endpoint that deletes a variable.
            endpoints = []
            if low is not None and low != 0:
                endpoints.append(low)
            if high is not None and high != 0:
                endpoints.append(high)
            endpoints.sort(key=lambda q: (abs(q), q))
            for t in endpoints:
                trial = {n: values.get(n, Fraction(0)) + t * direction.get(n, Fraction(0)) for n in all_names}
                ok, _ = verify_values(model, trial)
                if ok and sum(v != 0 for v in trial.values()) < len(active):
                    values = trial
                    iterations += 1
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    ok, message = verify_values(model, values)
    witness.values = {n: fraction_to_text(values.get(n, Fraction(0))) for n in all_names}
    witness.active_variables = sorted(n for n in all_names if values.get(n, Fraction(0)) != 0)
    witness.verified = ok
    witness.verification_message = message
    witness.reduced = iterations > 0
    witness.reduction_message = f"exact affine/conic reduction removed variables in {iterations} step(s); final support has {len(witness.active_variables)} variables"
    return witness
