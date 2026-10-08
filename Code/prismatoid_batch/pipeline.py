from __future__ import annotations

import hashlib

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections import Counter
import csv
import json
import shutil
import time
import traceback
import platform
import sys

from . import PACKAGE_ID
from .exact import rationalize_solution, reduce_support
from .facet_io import (
    candidate_id as make_candidate_id,
    candidate_vertex_count,
    enumerate_candidates,
    read_facets,
    sha256_file,
)
from .flag_search import (
    flag_intersection_cardinalities,
    flag_literal,
    parse_flag_indices,
    sample_rank_certified_facet_flags,
)
from .legacy_runner import load_best_model, run_legacy_solver
from .models import CertificateResult, CapturedModel
from .prepare import prepare_candidate
from .state import StateDB
from .template_library import TemplateLibrary


@dataclass
class PipelineOptions:
    data_root: Path
    project_root: Path
    output_root: Path
    entrypoint: Path | None = None
    interpreter: str | None = None
    prepare_mode: str = "auto"
    preprocess_command: str | None = None
    reorder_command: str | None = None
    timeout: float | None = None
    resume: bool = True
    retry_errors: bool = False
    start: int = 0
    stop: int | None = None
    limit: int | None = None
    vertex_counts: tuple[int, ...] | None = None
    exact_tolerance: float = 1e-8
    keep_sandboxes: bool = False
    template_first: bool = False
    max_templates: int | None = None
    dimension: int = 5
    n_factors: int = 2
    max_deg: int = 2
    search_variant: str = "legacy"
    random_seed: int = 0
    flag_attempts: int = 20
    gurobi_threads: int = 8
    gurobi_method: int = 0
    gurobi_log: int = 3
    lp_solver: str = "auto"
    gurobi_license: Path | None = None
    gurobi_license_source: str = "gurobi-default-search"


@dataclass
class _AttemptEvaluation:
    run: Any
    model: CapturedModel | None
    capture: Path | None
    witness: Any
    exact: bool
    status: str
    request: dict[str, Any]
    summary: dict[str, Any]
    model_capture_path: str | None = None
    copied_artifacts: list[str] | None = None


class BatchPipeline:
    def __init__(self, options: PipelineOptions):
        self.o = options
        if self.o.flag_attempts < 1:
            raise ValueError("flag_attempts must be a positive integer")
        # Resolve once and report the exact location.  This removes any
        # ambiguity caused by Sage launchers changing or obscuring cwd.
        self.o.output_root = self.o.output_root.expanduser().resolve()
        self.o.data_root = self.o.data_root.expanduser().resolve()
        self.o.project_root = self.o.project_root.expanduser().resolve()
        if self.o.entrypoint is not None:
            self.o.entrypoint = self.o.entrypoint.expanduser().resolve()
        if self.o.gurobi_license is not None:
            self.o.gurobi_license = self.o.gurobi_license.expanduser().resolve()
        if self.o.vertex_counts is not None:
            self.o.vertex_counts = tuple(sorted(set(self.o.vertex_counts)))
        self.o.output_root.mkdir(parents=True, exist_ok=True)
        self.results_dir = self.o.output_root / "certificates"
        self.prepared_dir = self.o.output_root / "prepared"
        self.capture_dir = self.o.output_root / "model_captures"
        self.legacy_artifacts_dir = self.o.output_root / "legacy_artifacts"
        self.work_dir = self.o.output_root / "work"
        for directory in (
            self.results_dir,
            self.prepared_dir,
            self.capture_dir,
            self.legacy_artifacts_dir,
            self.work_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        search_configuration = {
            "configuration_version": 4,
            "core_interface": "prismatoid-exact-core",
            "dimension": self.o.dimension,
            "n_factors": self.o.n_factors,
            "max_degree": self.o.max_deg,
            "random_seed": self.o.random_seed,
            "flag_attempts": self.o.flag_attempts,
            "prepare_mode": self.o.prepare_mode,
            "search_variant": self.o.search_variant,
            "vertex_counts": list(self.o.vertex_counts) if self.o.vertex_counts else None,
        }
        configuration_path = self.o.output_root / "SEARCH_CONFIG.json"
        if configuration_path.is_file():
            existing_configuration = json.loads(
                configuration_path.read_text(encoding="utf-8")
            )
            if existing_configuration != search_configuration:
                raise RuntimeError(
                    "the output directory belongs to a different certificate-search "
                    "configuration; use a new --output directory or remove the old "
                    f"output. Existing: {existing_configuration}; requested: "
                    f"{search_configuration}"
                )
        else:
            old_results = any(self.results_dir.glob("*.json"))
            old_database = (self.o.output_root / "batch_state.sqlite3").is_file()
            if old_results or old_database:
                raise RuntimeError(
                    "the output directory contains results from an older batch release "
                    "without SEARCH_CONFIG.json. Use a new --output directory so "
                    "different search configurations are not mixed."
                )
            configuration_path.write_text(
                json.dumps(search_configuration, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        self.search_configuration = search_configuration
        self.db = StateDB(self.o.output_root / "batch_state.sqlite3")
        self.library = TemplateLibrary(
            self.o.output_root / "templates" / "final_templates.json"
        )
        run_info = [
            f"batch_package={PACKAGE_ID}",
            f"output_root={self.o.output_root}",
            f"data_root={self.o.data_root}",
            f"project_root={self.o.project_root}",
            f"entrypoint={self.o.entrypoint or '<autodetect>'}",
            f"cwd={Path.cwd()}",
            f"python_executable={sys.executable}",
            f"python_version={platform.python_version()}",
            f"lp_solver={self.o.lp_solver}",
            f"search_variant={self.o.search_variant}",
            f"flag_attempts={self.o.flag_attempts}",
            "flag_attempt_strategy=rank-certified-flags-including-nonsimplicial-facets",
            "timeout_scope=per solver invocation (each flag/template attempt)",
            "vertex_counts="
            + (
                ",".join(map(str, self.o.vertex_counts))
                if self.o.vertex_counts
                else "all"
            ),
            f"gurobi_license_source={self.o.gurobi_license_source}",
            f"gurobi_license_path={self.o.gurobi_license or '<Gurobi default search>'}",
            "search_configuration="
            + json.dumps(self.search_configuration, sort_keys=True),
        ]
        (self.o.output_root / "RUN_INFO.txt").write_text(
            "\n".join(run_info) + "\n", encoding="utf-8"
        )
        print(f"Batch package: {PACKAGE_ID}", flush=True)
        print(f"Batch output directory: {self.o.output_root}", flush=True)
        print(f"Per-candidate reports: {self.results_dir}", flush=True)
        print(f"LP solver policy: {self.o.lp_solver}", flush=True)
        print(f"Search variant: {self.o.search_variant}", flush=True)
        print(
            f"Flag choices per candidate: up to {self.o.flag_attempts} "
            "(default first; stop after an exact certificate)",
            flush=True,
        )
        print(
            "Vertex-count filter: "
            + (
                ", ".join(map(str, self.o.vertex_counts))
                if self.o.vertex_counts
                else "all candidates"
            ),
            flush=True,
        )
        print(
            "Gurobi license: "
            + (
                str(self.o.gurobi_license)
                if self.o.gurobi_license
                else "Gurobi default search"
            )
            + f" ({self.o.gurobi_license_source})",
            flush=True,
        )

    def _copy_capture(self, source: Path, cid: str, suffix: str) -> Path:
        destination = self.capture_dir / f"{cid}_{suffix}.json"
        shutil.copy2(source, destination)
        return destination

    def _solve(
        self,
        prepared: Path,
        cid: str,
        allowed: list[str] | None = None,
        capture_only: bool = False,
        *,
        flag: str = "{}",
        force_new_flag: bool = False,
        flag_attempt_index: int = 0,
        flag_source: str = "legacy-default",
        random_seed: int | None = None,
    ):
        return run_legacy_solver(
            self.o.project_root,
            prepared,
            cid,
            self.work_dir,
            entrypoint=self.o.entrypoint,
            interpreter=self.o.interpreter,
            allowed_variables=allowed,
            capture_only=capture_only,
            timeout=self.o.timeout,
            keep_sandbox=self.o.keep_sandboxes,
            dimension=self.o.dimension,
            n_factors=self.o.n_factors,
            max_deg=self.o.max_deg,
            random_seed=(self.o.random_seed if random_seed is None else random_seed),
            flag=flag,
            force_new_flag=force_new_flag,
            flag_attempt_index=flag_attempt_index,
            flag_source=flag_source,
            gurobi_threads=self.o.gurobi_threads,
            gurobi_method=self.o.gurobi_method,
            gurobi_log=self.o.gurobi_log,
            lp_solver=self.o.lp_solver,
            search_variant=self.o.search_variant,
            gurobi_license=self.o.gurobi_license,
            gurobi_license_source=self.o.gurobi_license_source,
        )

    def _copy_run_artifacts(
        self, run: Any, cid: str, attempt_label: str
    ) -> list[str]:
        if not getattr(run, "artifacts", None):
            return []
        destination_dir = self.legacy_artifacts_dir / cid / attempt_label
        destination_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        seen: set[str] = set()
        for source in run.artifacts:
            name = source.name
            if name in seen:
                stem, suffix = source.stem, source.suffix
                index = 2
                while f"{stem}_{index}{suffix}" in seen:
                    index += 1
                name = f"{stem}_{index}{suffix}"
            seen.add(name)
            destination = destination_dir / name
            shutil.copy2(source, destination)
            copied.append(str(destination))
        return copied

    def _cleanup_run(self, run: Any) -> None:
        if self.o.keep_sandboxes:
            return
        try:
            shutil.rmtree(run.sandbox)
        except OSError:
            pass

    @staticmethod
    def _adapter_flag_metadata(run: Any) -> dict[str, Any]:
        for path in getattr(run, "artifacts", []):
            if path.name != "adapter_result.json":
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            metadata = payload.get("flag_search")
            if isinstance(metadata, dict):
                return metadata
        return {}

    def _inspect_run(
        self, run: Any, request: dict[str, Any]
    ) -> _AttemptEvaluation:
        loaded = load_best_model(run.captures)
        model: CapturedModel | None = None
        capture: Path | None = None
        if loaded:
            model, capture = loaded

        witness = None
        exact = False
        status = "no_certificate"
        if model is not None and model.solution_count > 0:
            witness = reduce_support(
                model, rationalize_solution(model, self.o.exact_tolerance)
            )
            if model.unsupported_features:
                witness.verified = False
                witness.verification_message += (
                    "; unsupported captured features: "
                    + "; ".join(model.unsupported_features)
                )
            exact = bool(witness.verified)
            status = (
                "certificate_exact" if exact else "certificate_numerical_only"
            )
        elif run.returncode == 124:
            status = "timeout"
        elif run.returncode != 0:
            status = "error"

        flag_metadata: dict[str, Any] = {}
        if model is not None:
            candidate_metadata = model.metadata.get("flag_search", {})
            if isinstance(candidate_metadata, dict):
                flag_metadata = dict(candidate_metadata)
        if not flag_metadata:
            flag_metadata = self._adapter_flag_metadata(run)

        legacy_selected = parse_flag_indices(
            flag_metadata.get("selected_flag_indices_zero_based")
        )
        requested_indices = parse_flag_indices(request.get("requested_flag"))
        selected_indices = legacy_selected or requested_indices
        summary = {
            "attempt_number": int(request["attempt_number"]),
            "attempt_index_zero_based": int(request["attempt_index_zero_based"]),
            "source": str(request["source"]),
            "requested_flag": str(request["requested_flag"]),
            "requested_flag_indices_zero_based": (
                list(requested_indices) if requested_indices is not None else None
            ),
            "force_new_flag": bool(request["force_new_flag"]),
            "random_seed": int(request["random_seed"]),
            "combinatorially_checked": bool(
                request.get("combinatorially_checked", False)
            ),
            "intersection_cardinalities": request.get(
                "intersection_cardinalities"
            ),
            "returncode": int(run.returncode),
            "elapsed_seconds": float(run.elapsed_seconds),
            "status": status,
            "exact": exact,
            "solution_count": int(model.solution_count) if model else 0,
            "selected_flag_indices_zero_based": (
                list(selected_indices) if selected_indices is not None else None
            ),
            "selected_flag_reported_by_legacy": legacy_selected is not None,
            "legacy_flag_attributes": flag_metadata.get(
                "legacy_flag_attributes", {}
            ),
            "model_capture": None,
            "legacy_artifacts": [],
            "selected_for_final_result": False,
        }
        if request.get("template_id"):
            summary["template_id"] = request["template_id"]
            summary["template_restricted"] = True

        return _AttemptEvaluation(
            run=run,
            model=model,
            capture=capture,
            witness=witness,
            exact=exact,
            status=status,
            request=request,
            summary=summary,
        )

    def _archive_attempt(
        self, evaluation: _AttemptEvaluation, cid: str, attempt_label: str
    ) -> None:
        if evaluation.capture is not None:
            destination = self._copy_capture(
                evaluation.capture, cid, attempt_label
            )
            evaluation.model_capture_path = str(destination)
            evaluation.summary["model_capture"] = str(destination)
        copied = self._copy_run_artifacts(
            evaluation.run, cid, attempt_label
        )
        evaluation.copied_artifacts = copied
        evaluation.summary["legacy_artifacts"] = copied

    @staticmethod
    def _choose_best_attempt(
        evaluations: list[_AttemptEvaluation],
    ) -> _AttemptEvaluation:
        if not evaluations:
            raise RuntimeError("no flag attempt was executed")
        priority = {
            "certificate_exact": 4,
            "certificate_numerical_only": 3,
            "no_certificate": 2,
            "timeout": 1,
            "error": 0,
        }
        return max(
            evaluations,
            key=lambda item: (
                priority.get(item.status, -1),
                -int(item.request["attempt_number"]),
            ),
        )

    def _run_flag_attempt(
        self,
        prepared: Path,
        cid: str,
        request: dict[str, Any],
    ) -> _AttemptEvaluation:
        number = int(request["attempt_number"])
        print(
            f"  {cid}: flag attempt {number}/{self.o.flag_attempts}; "
            f"source={request['source']}; requested={request['requested_flag']}",
            flush=True,
        )
        run = self._solve(
            prepared,
            cid,
            capture_only=False,
            flag=str(request["requested_flag"]),
            force_new_flag=bool(request["force_new_flag"]),
            flag_attempt_index=int(request["attempt_index_zero_based"]),
            flag_source=str(request["source"]),
            random_seed=int(request["random_seed"]),
        )
        evaluation = self._inspect_run(run, request)
        self._archive_attempt(evaluation, cid, f"flag_{number:02d}")
        self._cleanup_run(run)
        return evaluation

    def process_one(
        self,
        source: Path,
        cid: str,
        digest: str,
        vertex_count: int | None = None,
    ) -> CertificateResult:
        started = time.monotonic()
        if vertex_count is None:
            vertex_count = candidate_vertex_count(source)
        prepared = self.prepared_dir / f"{cid}.txt"
        prep = prepare_candidate(
            source,
            prepared,
            mode=self.o.prepare_mode,
            preprocess_command=self.o.preprocess_command,
            reorder_command=self.o.reorder_command,
            timeout=self.o.timeout,
            bundled_tools_dir=Path(__file__).resolve().parent.parent
            / "preprocessing",
        )
        template_attempts: list[dict[str, Any]] = []
        flag_attempt_summaries: list[dict[str, Any]] = []
        evaluations: list[_AttemptEvaluation] = []
        chosen: _AttemptEvaluation | None = None
        chosen_template = None
        sampled_flag_count = 0
        fallback_flag_count = 0

        # Templates are tied to a particular generated LP, so retain the legacy
        # default flag for this preliminary stage.  Alternate flags are tried only
        # when this stage does not yield an exactly verified certificate.
        if self.o.template_first and self.library.templates:
            pre_run = self._solve(
                prepared,
                cid,
                capture_only=True,
                flag="{}",
                force_new_flag=False,
                flag_attempt_index=0,
                flag_source="legacy-default-template-capture",
                random_seed=self.o.random_seed,
            )
            pre_loaded = load_best_model(pre_run.captures)
            if pre_loaded:
                pre_model, _ = pre_loaded
                for template, support in self.library.candidate_supports(
                    pre_model, self.o.max_templates
                ):
                    restricted = self._solve(
                        prepared,
                        cid,
                        allowed=support,
                        capture_only=False,
                        flag="{}",
                        force_new_flag=False,
                        flag_attempt_index=0,
                        flag_source="legacy-default-template-restricted",
                        random_seed=self.o.random_seed,
                    )
                    request = {
                        "attempt_number": 1,
                        "attempt_index_zero_based": 0,
                        "source": "legacy-default-template-restricted",
                        "requested_flag": "{}",
                        "force_new_flag": False,
                        "random_seed": self.o.random_seed,
                        "combinatorially_checked": False,
                        "intersection_cardinalities": None,
                        "template_id": template.template_id,
                    }
                    evaluation = self._inspect_run(restricted, request)
                    restriction_fallback = bool(
                        evaluation.model
                        and evaluation.model.metadata.get(
                            "restriction_fallback"
                        )
                    )
                    attempt = {
                        "template_id": template.template_id,
                        "mapped_support_size": len(support),
                        "returncode": restricted.returncode,
                        "status": evaluation.status,
                        "exact": evaluation.exact,
                        "restriction_fallback": restriction_fallback,
                    }
                    if evaluation.witness is not None:
                        attempt["final_support_size"] = len(
                            evaluation.witness.active_variables
                        )
                    template_attempts.append(attempt)
                    if evaluation.exact:
                        self._archive_attempt(
                            evaluation, cid, "flag_01_template"
                        )
                        chosen = evaluation
                        chosen_template = (
                            None if restriction_fallback else template
                        )
                        flag_attempt_summaries.append(evaluation.summary)
                        break
                    self._cleanup_run(restricted)
            self._cleanup_run(pre_run)

        if chosen is None:
            default_request = {
                "attempt_number": 1,
                "attempt_index_zero_based": 0,
                "source": "legacy-default",
                "requested_flag": "{}",
                "force_new_flag": False,
                "random_seed": self.o.random_seed,
                "combinatorially_checked": False,
                "intersection_cardinalities": None,
            }
            default_evaluation = self._run_flag_attempt(
                prepared, cid, default_request
            )
            evaluations.append(default_evaluation)
            flag_attempt_summaries.append(default_evaluation.summary)
            if default_evaluation.exact:
                chosen = default_evaluation

            if chosen is None and self.o.flag_attempts > 1:
                complex_data = read_facets(prepared, require_prepared=True)
                exclusions: list[tuple[int, ...]] = []
                selected_default = parse_flag_indices(
                    default_evaluation.summary.get(
                        "selected_flag_indices_zero_based"
                    )
                )
                if selected_default is not None:
                    exclusions.append(selected_default)

                remaining = self.o.flag_attempts - 1
                sampled_flags = sample_rank_certified_facet_flags(
                    complex_data.facets,
                    self.o.dimension,
                    remaining,
                    random_seed=self.o.random_seed,
                    candidate_id=cid,
                    exclude=exclusions,
                )
                sampled_flag_count = len(sampled_flags)
                requests: list[dict[str, Any]] = []
                for offset, indices in enumerate(sampled_flags, start=1):
                    requests.append(
                        {
                            "attempt_number": offset + 1,
                            "attempt_index_zero_based": offset,
                            "source": "sampled-rank-certified-facet-flag",
                            "requested_flag": flag_literal(indices),
                            "force_new_flag": False,
                            # Keep all non-flag random choices fixed so the flag is
                            # the intended difference between these attempts.
                            "random_seed": self.o.random_seed,
                            "combinatorially_checked": True,
                            "intersection_cardinalities": list(
                                flag_intersection_cardinalities(
                                    complex_data.facets, indices
                                )
                            ),
                        }
                    )

                # This should rarely be needed for the supplied prismatoids, whose
                # lateral facets are simplices.  It preserves a useful fallback for
                # other data sets: ask the legacy SlackIdeals machinery to choose a
                # fresh flag, with a distinct deterministic seed on each try.
                missing = remaining - len(sampled_flags)
                fallback_flag_count = missing
                for fallback_offset in range(missing):
                    attempt_index = len(sampled_flags) + fallback_offset + 1
                    requests.append(
                        {
                            "attempt_number": attempt_index + 1,
                            "attempt_index_zero_based": attempt_index,
                            "source": "legacy-force-new-flag-fallback",
                            "requested_flag": "{}",
                            "force_new_flag": True,
                            "random_seed": self.o.random_seed + attempt_index,
                            "combinatorially_checked": False,
                            "intersection_cardinalities": None,
                        }
                    )

                for request in requests:
                    evaluation = self._run_flag_attempt(
                        prepared, cid, request
                    )
                    evaluations.append(evaluation)
                    flag_attempt_summaries.append(evaluation.summary)
                    if evaluation.exact:
                        chosen = evaluation
                        break

            if chosen is None:
                chosen = self._choose_best_attempt(evaluations)

        if chosen is None:  # Defensive; every branch above selects an attempt.
            raise RuntimeError("certificate search ended without a selected run")
        chosen.summary["selected_for_final_result"] = True

        chosen_model = chosen.model
        witness = chosen.witness
        exact = chosen.exact
        status = chosen.status
        model_capture_path = chosen.model_capture_path
        copied_artifacts = [
            path
            for attempt in flag_attempt_summaries
            for path in attempt.get("legacy_artifacts", [])
        ]

        sampled_attempts_executed = sum(
            attempt.get("source") == "sampled-rank-certified-facet-flag"
            for attempt in flag_attempt_summaries
        )
        fallback_attempts_executed = sum(
            attempt.get("source") == "legacy-force-new-flag-fallback"
            for attempt in flag_attempt_summaries
        )

        metadata = {
            "batch_package": PACKAGE_ID,
            "candidate_vertex_count": vertex_count,
            "preparation_mode": prep.mode,
            "preparation_stdout": prep.stdout,
            "preparation_stderr": prep.stderr,
            "preparation_metadata": prep.metadata or {},
            "captured_model_name": chosen_model.name if chosen_model else None,
            "captured_model_unsupported_features": (
                chosen_model.unsupported_features if chosen_model else []
            ),
            "captured_model_metadata": (
                chosen_model.metadata if chosen_model else {}
            ),
            "legacy_artifacts": copied_artifacts,
            "flag_search": {
                "requested_attempts": self.o.flag_attempts,
                "executed_attempts": len(flag_attempt_summaries),
                "stopped_after_exact_certificate": bool(
                    exact
                    and len(flag_attempt_summaries) < self.o.flag_attempts
                ),
                "strategy": (
                    "legacy default first; then deterministic random sampling "
                    "of distinct rank-certified facet flags including every "
                    "nonsimplicial facet; fresh-flag fallback if necessary"
                ),
                # The compatibility count keys mean *executed* attempts.  The
                # explicit generated/planned keys distinguish unexecuted choices
                # left over after an early exact-certificate stop.
                "sampled_checked_flag_count": sampled_attempts_executed,
                "legacy_force_new_fallback_count": fallback_attempts_executed,
                "sampled_checked_flags_generated": sampled_flag_count,
                "sampled_checked_attempts_executed": sampled_attempts_executed,
                "legacy_force_new_fallbacks_planned": fallback_flag_count,
                "legacy_force_new_fallback_attempts_executed": (
                    fallback_attempts_executed
                ),
                "timeout_scope": "per solver invocation",
                "attempts": flag_attempt_summaries,
            },
            "search_parameters": {
                "dimension": self.o.dimension,
                "n_factors": self.o.n_factors,
                "max_deg": self.o.max_deg,
                "search_variant": self.o.search_variant,
                "flag_attempts": self.o.flag_attempts,
                "vertex_count_filter": (
                    list(self.o.vertex_counts)
                    if self.o.vertex_counts
                    else None
                ),
                "monomial_simplification": self.o.search_variant
                == "all-variable-products-simplified",
                "all_variable_products": self.o.search_variant
                == "all-variable-products-simplified",
                "random_seed": self.o.random_seed,
                "gurobi_threads": self.o.gurobi_threads,
                "gurobi_method": self.o.gurobi_method,
                "lp_solver": self.o.lp_solver,
                "gurobi_license_source": self.o.gurobi_license_source,
                "gurobi_license_path": (
                    str(self.o.gurobi_license)
                    if self.o.gurobi_license
                    else None
                ),
            },
        }
        template_id = None
        if exact and chosen_model is not None and witness is not None:
            bundle = chosen_model.metadata.get('certificate_bundle')
            if bundle is not None:
                proof_dir = self.o.output_root / 'exact_proofs'
                proof_dir.mkdir(exist_ok=True)
                bundle['input_file_sha256'] = digest
                bundle['prepared_file_sha256'] = hashlib.sha256(prepared.read_bytes()).hexdigest()
                (proof_dir / f'{cid}.json').write_text(json.dumps(bundle, indent=2, sort_keys=True))
                metadata['independent_proof_path'] = str(proof_dir / f'{cid}.json')
            template, created = self.library.add_or_cover(
                cid, chosen_model, witness
            )
            template_id = template.template_id
            metadata["new_template_created"] = created
            metadata["template_restriction_succeeded"] = (
                chosen_template.template_id if chosen_template else None
            )
            if created:
                template.notes["representative_legacy_stdout"] = (
                    chosen.run.stdout[-20000:]
                )
                template.notes["representative_legacy_stderr"] = (
                    chosen.run.stderr[-10000:]
                )
                self.library.save()

        elapsed = time.monotonic() - started
        result = CertificateResult(
            candidate_id=cid,
            source_path=str(source),
            prepared_path=str(prepared),
            status=status,
            exact=exact,
            witness=witness,
            template_id=template_id,
            template_attempts=template_attempts,
            flag_attempts=flag_attempt_summaries,
            solver_returncode=chosen.run.returncode,
            solver_command=chosen.run.command,
            stdout=chosen.run.stdout,
            stderr=chosen.run.stderr,
            model_capture=model_capture_path,
            elapsed_seconds=elapsed,
            sha256=digest,
            metadata=metadata,
        )
        self._cleanup_run(chosen.run)
        return result

    def _select_candidates(self) -> list[tuple[Path, int]]:
        all_candidates = enumerate_candidates(self.o.data_root)
        all_records = [
            (source, candidate_vertex_count(source)) for source in all_candidates
        ]
        distribution = Counter(vertex_count for _, vertex_count in all_records)

        if self.o.vertex_counts:
            allowed = set(self.o.vertex_counts)
            filtered = [
                record for record in all_records if record[1] in allowed
            ]
            if not filtered:
                requested = ", ".join(map(str, self.o.vertex_counts))
                available = ", ".join(
                    f"{vertex_count} ({count})"
                    for vertex_count, count in sorted(distribution.items())
                )
                raise RuntimeError(
                    "no candidates match the requested vertex count(s) "
                    f"{requested}. Available counts are: {available}"
                )
        else:
            filtered = list(all_records)

        selected = filtered[self.o.start:self.o.stop]
        if self.o.limit is not None:
            selected = selected[:self.o.limit]

        distribution_path = self.o.output_root / "VERTEX_COUNT_DISTRIBUTION.tsv"
        with distribution_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["vertex_count", "candidate_count"])
            for vertex_count, count in sorted(distribution.items()):
                writer.writerow([vertex_count, count])

        manifest_path = self.o.output_root / "CANDIDATE_SELECTION.tsv"
        with manifest_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["selection_order", "candidate", "vertex_count", "source"])
            for order, (source, vertex_count) in enumerate(selected, 1):
                writer.writerow(
                    [
                        order,
                        make_candidate_id(source, self.o.data_root),
                        vertex_count,
                        str(source),
                    ]
                )

        summary_lines = [
            "CANDIDATE SELECTION SUMMARY",
            "===========================",
            "",
            f"dataset_candidates: {len(all_records)}",
            "vertex_count_filter: "
            + (
                ",".join(map(str, self.o.vertex_counts))
                if self.o.vertex_counts
                else "all"
            ),
            f"after_vertex_filter: {len(filtered)}",
            f"start: {self.o.start}",
            f"stop: {self.o.stop if self.o.stop is not None else 'none'}",
            f"limit: {self.o.limit if self.o.limit is not None else 'none'}",
            f"selected_for_run: {len(selected)}",
            f"manifest: {manifest_path}",
            f"distribution: {distribution_path}",
        ]
        (self.o.output_root / "SELECTION_SUMMARY.txt").write_text(
            "\n".join(summary_lines) + "\n", encoding="utf-8"
        )

        print(
            f"Candidates selected: {len(selected)} of {len(all_records)} "
            f"({len(filtered)} after vertex filter)",
            flush=True,
        )
        print(f"Candidate manifest: {manifest_path}", flush=True)
        return selected

    def run(self) -> int:
        candidates = self._select_candidates()
        self.db.event(None, "batch_started", f"{len(candidates)} candidates selected")
        for index, (source, vertex_count) in enumerate(candidates, 1):
            cid = make_candidate_id(source, self.o.data_root)
            digest = sha256_file(source)
            if self.o.resume and self.db.completed(cid, digest):
                continue
            candidate_started = time.monotonic()
            (self.o.output_root / "CURRENT_CANDIDATE.txt").write_text(
                f"candidate={cid}\nsource={source}\nvertex_count={vertex_count}\n"
                f"search_variant={self.o.search_variant}\n",
                encoding="utf-8",
            )
            self.db.mark_running(cid, str(source), digest)
            try:
                result = self.process_one(
                    source, cid, digest, vertex_count=vertex_count
                )
            except Exception:
                prepared_guess = self.prepared_dir / f"{cid}.txt"
                result = CertificateResult(
                    candidate_id=cid,
                    source_path=str(source),
                    prepared_path=str(prepared_guess) if prepared_guess.exists() else None,
                    status="error",
                    exact=False,
                    elapsed_seconds=time.monotonic() - candidate_started,
                    sha256=digest,
                    error=traceback.format_exc(),
                    metadata={
                        "batch_package": PACKAGE_ID,
                        "candidate_vertex_count": vertex_count,
                        "vertex_count_filter": (
                            list(self.o.vertex_counts)
                            if self.o.vertex_counts
                            else None
                        ),
                    },
                )
            json_path = self.results_dir / f"{cid}.json"
            txt_path = self.results_dir / f"{cid}.txt"
            result.write_json(json_path)
            result.write_text(txt_path)
            self.db.save_result(cid, str(source), digest, result.status, result.exact, result.template_id, str(json_path), str(txt_path), result.elapsed_seconds)
            print(
                f"[{index}/{len(candidates)}] {cid} (n={vertex_count}): "
                f"{result.status}; template={result.template_id or '-'}; "
                f"{result.elapsed_seconds:.2f}s",
                flush=True,
            )
            if result.status in {"error", "timeout", "certificate_numerical_only"}:
                print(f"    details: {txt_path}", flush=True)
                diagnostic = result.error or result.stderr
                if diagnostic:
                    last_line = next((line.strip() for line in reversed(diagnostic.splitlines()) if line.strip()), "")
                    if last_line:
                        print(f"    diagnostic: {last_line[:500]}", flush=True)
            self.write_reports()
        self.db.event(None, "batch_finished", "")
        self.write_reports()
        current = self.o.output_root / "CURRENT_CANDIDATE.txt"
        if current.exists():
            current.unlink()
        print(f"Batch finished. Summary: {self.o.output_root / 'SUMMARY.txt'}", flush=True)
        rows = self.db.rows()
        failures = sum(1 for row in rows if row[1] in {"error", "timeout"})
        return 1 if failures else 0

    def write_reports(self) -> None:
        templates_dir = self.o.output_root / "templates"
        self.library.save()
        self.library.write_human_report(templates_dir / "final_templates.txt")
        rows = self.db.rows()
        summary_path = self.o.output_root / "summary.tsv"
        with summary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["candidate", "status", "exact", "template", "seconds", "source"])
            writer.writerows(rows)
        counts: dict[str, int] = {}
        for _, status, exact, template, _, _ in rows:
            counts[status] = counts.get(status, 0) + 1
        report = [
            "BATCH CERTIFICATE SUMMARY",
            "=========================",
            "",
            f"batch_package: {PACKAGE_ID}",
            f"search_variant: {self.o.search_variant}",
            f"n_factors: {self.o.n_factors}",
            f"max_degree: {self.o.max_deg}",
            "vertex_count_filter: "
            + (
                ",".join(map(str, self.o.vertex_counts))
                if self.o.vertex_counts
                else "all"
            ),
            f"processed: {len(rows)}",
            f"exact_certificates: {sum(int(r[2]) for r in rows)}",
            f"templates: {len(self.library.templates)}",
            "",
            "status_counts:",
        ] + [f"  {key}: {value}" for key, value in sorted(counts.items())]
        (self.o.output_root / "SUMMARY.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
