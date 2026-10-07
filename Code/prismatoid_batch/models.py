from __future__ import annotations

from dataclasses import dataclass, field, asdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Optional
import json


def fraction_to_text(value: Fraction | int | str) -> str:
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    return str(value)


def fraction_from_text(value: Any) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(str(value))


@dataclass(frozen=True)
class FacetComplex:
    path: Path
    facets: tuple[tuple[int, ...], ...]
    vertices: tuple[int, ...]
    base_facets: tuple[int, int] | None = None

    @property
    def n_vertices(self) -> int:
        return len(self.vertices)

    @property
    def n_facets(self) -> int:
        return len(self.facets)


@dataclass
class LinearVariable:
    name: str
    lb: str
    ub: str
    vtype: str = "C"
    objective: str = "0"
    value: str | None = None


@dataclass
class LinearConstraint:
    name: str
    sense: str
    rhs: str
    coefficients: dict[str, str]


@dataclass
class CapturedModel:
    name: str
    variables: list[LinearVariable]
    constraints: list[LinearConstraint]
    status: int | None = None
    solution_count: int = 0
    objective_value: str | None = None
    optimize_index: int = 0
    unsupported_features: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CapturedModel":
        return cls(
            name=data.get("name", "model"),
            variables=[LinearVariable(**v) for v in data.get("variables", [])],
            constraints=[LinearConstraint(**c) for c in data.get("constraints", [])],
            status=data.get("status"),
            solution_count=int(data.get("solution_count", 0) or 0),
            objective_value=data.get("objective_value"),
            optimize_index=int(data.get("optimize_index", 0) or 0),
            unsupported_features=list(data.get("unsupported_features", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ExactWitness:
    values: dict[str, str]
    active_variables: list[str]
    verified: bool
    verification_message: str
    reduced: bool = False
    reduction_message: str = ""
    exact_objective: str | None = None

    def fractions(self) -> dict[str, Fraction]:
        return {k: fraction_from_text(v) for k, v in self.values.items()}


@dataclass
class CertificateResult:
    candidate_id: str
    source_path: str
    prepared_path: str | None
    status: str
    exact: bool
    witness: ExactWitness | None = None
    template_id: str | None = None
    template_attempts: list[dict[str, Any]] = field(default_factory=list)
    flag_attempts: list[dict[str, Any]] = field(default_factory=list)
    solver_returncode: int | None = None
    solver_command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    model_capture: str | None = None
    elapsed_seconds: float = 0.0
    sha256: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def write_text(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"candidate: {self.candidate_id}",
            f"source: {self.source_path}",
            f"prepared_input: {self.prepared_path or '-'}",
            f"sha256: {self.sha256}",
            f"status: {self.status}",
            f"exact_certificate: {'yes' if self.exact else 'no'}",
            f"template: {self.template_id or '-'}",
            f"elapsed_seconds: {self.elapsed_seconds:.6f}",
            f"solver_returncode: {self.solver_returncode if self.solver_returncode is not None else '-'}",
            f"solver_command: {' '.join(self.solver_command) if self.solver_command else '-'}",
        ]
        if self.error:
            lines += ["", "[error]", self.error]
        if self.template_attempts:
            lines += ["", "[template attempts]"]
            for attempt in self.template_attempts:
                lines.append(json.dumps(attempt, sort_keys=True))
        if self.flag_attempts:
            lines += ["", "[flag attempts]"]
            for attempt in self.flag_attempts:
                lines.append(json.dumps(attempt, sort_keys=True))
        if self.witness:
            lines += [
                "",
                "[exact witness]",
                f"verified: {self.witness.verified}",
                f"verification: {self.witness.verification_message}",
                f"support_reduced: {self.witness.reduced}",
                f"reduction: {self.witness.reduction_message}",
                f"active_count: {len(self.witness.active_variables)}",
                "active_variables: " + " ".join(self.witness.active_variables),
                "coefficients:",
            ]
            for name in sorted(self.witness.values):
                value = self.witness.values[name]
                if value != "0":
                    lines.append(f"  {name} = {value}")
            active_rows = (
                self.metadata.get("captured_model_metadata", {})
                .get("active_row_descriptions", {})
            )
            if active_rows:
                lines += ["", "[positive polynomial identity]", "The following exactly weighted positive rows sum coefficientwise to zero:"]
                for name in self.witness.active_variables:
                    description = active_rows.get(name, {})
                    coefficient = self.witness.values.get(name, "0")
                    polynomial = description.get("positive_polynomial", "<description unavailable>")
                    row_index = description.get("row_index_zero_based", "?")
                    provenance = description.get("provenance", "")
                    lines.append(f"  {coefficient} * ({polynomial})    # LP row {row_index}")
                    if provenance:
                        lines.append(f"      provenance: {provenance}")
        if self.metadata:
            lines += ["", "[metadata]", json.dumps(self.metadata, indent=2, sort_keys=True)]
        lines += ["", "[legacy solver stdout]", self.stdout.rstrip(), "", "[legacy solver stderr]", self.stderr.rstrip(), ""]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        tmp.replace(path)


@dataclass
class TemplateRecord:
    template_id: str
    canonical_hash: str
    representative_candidate: str
    graph: dict[str, Any]
    active_count: int
    witness_values: dict[str, str]
    representative_variable_names: list[str]
    covered_candidates: list[str] = field(default_factory=list)
    creation_order: int = 0
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemplateRecord":
        return cls(**data)
