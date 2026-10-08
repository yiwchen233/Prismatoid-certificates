from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys
import os
import platform
import subprocess
import traceback

from . import PACKAGE_ID
from .autodetect import write_report
from .facet_io import enumerate_candidates, read_facets
from .license_config import (
    LicenseSelection,
    apply_gurobi_license,
    redacted_subprocess_text,
    resolve_gurobi_license,
    unrestricted_probe_code,
)
from .pipeline import BatchPipeline, PipelineOptions
from .prepare import prepare_candidate

SEARCH_VARIANTS = ("legacy", "all-variable-products-simplified")


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return value


def _bundle_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _add_license_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--gurobi-license",
        type=Path,
        help=(
            "path to gurobi.lic; when omitted, first try "
            "<project>/dev/gurobi.lic, then GRB_LICENSE_FILE and Gurobi defaults"
        ),
    )


def _child_environment(project_root: Path, selection: LicenseSelection) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(project_root),
            *[str(Path(item).resolve()) for item in sys.path if item],
            environment.get("PYTHONPATH", ""),
        ]
    )
    apply_gurobi_license(selection, environment)
    return environment


def _probe_unrestricted_gurobi(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", unrestricted_probe_code()],
        env=environment,
        text=True,
        capture_output=True,
    )


def _raise_failed_gurobi_preflight(
    probe: subprocess.CompletedProcess[str], selection: LicenseSelection
) -> None:
    stdout = redacted_subprocess_text(probe.stdout).strip()
    stderr = redacted_subprocess_text(probe.stderr).strip()
    details = stderr or stdout or f"process returned {probe.returncode}"
    selected = str(selection.path) if selection.path else "Gurobi default search"
    raise RuntimeError(
        "The unrestricted gurobipy preflight failed before candidate generation. "
        f"Selected license: {selected} ({selection.source}).\n{details}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prismatoid-batch",
        description="Batch non-realizability certificate search with an exactly verified template library.",
    )
    parser.add_argument("--info", "--version", action="version", version=PACKAGE_ID, help="show the batch runner identity and exit")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="scan candidates, save one TXT certificate result per candidate, and update templates")
    run.add_argument("--data", type=Path, required=True, help="root of the unchanged prismatoid data set")
    run.add_argument("--project", type=Path, default=Path.cwd(), help="root of the legacy certificate project")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--entrypoint", type=Path, help="legacy solver .py/.sage entry point; otherwise autodetected")
    run.add_argument("--interpreter", help="interpreter executable; default is Python or Sage autodetection")
    run.add_argument("--prepare-mode", choices=["auto", "prepared", "normalize", "external"], default="auto")
    run.add_argument("--preprocess-command", help="command template with {input}, {output}, and {cwd}")
    run.add_argument("--reorder-command", help="command template with {input}, {output}, and {cwd}")
    run.add_argument("--timeout", type=float, help="seconds per legacy solver invocation")
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--start", type=int, default=0)
    run.add_argument("--stop", type=int)
    run.add_argument("--limit", type=int)
    run.add_argument(
        "--vertex-count",
        "--num-vertices",
        dest="vertex_counts",
        action="append",
        type=_positive_int,
        help=(
            "select only candidates having exactly this number of vertices; "
            "repeat the option to select a union. The vertex filter is applied "
            "before --start, --stop, and --limit"
        ),
    )
    run.add_argument("--keep-sandboxes", action="store_true")
    template_group = run.add_mutually_exclusive_group()
    template_group.add_argument(
        "--template-first", action="store_true",
        help="after templates exist, capture each full LP and try matching template supports before the unrestricted solve",
    )
    template_group.add_argument("--no-template-first", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--max-templates", type=int)
    run.add_argument("--exact-tolerance", type=float, default=1e-8)
    run.add_argument("--dimension", type=int, default=5)
    run.add_argument("--n-factors", type=int, default=2)
    run.add_argument("--max-degree", type=int, default=2)
    run.add_argument(
        "--search-variant",
        choices=SEARCH_VARIANTS,
        default="legacy",
        help=(
            "positive-polynomial generator family: legacy uses signed raw determinants; "
            "all-variable-products-simplified "
            "divides common positive monomial factors from every reconstructed generator and then "
            "forms products using both reconstructed entries and every positive "
            "reduced-slack variable"
        ),
    )
    run.add_argument("--random-seed", type=int, default=0)
    run.add_argument(
        "--flag-attempts",
        type=_positive_int,
        default=20,
        help=(
            "maximum number of flag choices per candidate: use the legacy "
            "default first, then deterministic distinct flags that pass a "
            "triangular-rank check and include every nonsimplicial facet; stop after an exact certificate. "
            "The --timeout value applies separately to each attempt"
        ),
    )
    run.add_argument("--gurobi-threads", type=int, default=8)
    run.add_argument("--gurobi-method", type=int, default=0)
    run.add_argument("--gurobi-log", type=int, default=3)
    _add_license_argument(run)
    run.add_argument(
        "--lp-solver",
        choices=["auto", "gurobipy", "scipy-highs"],
        default="auto",
        help="LP backend: direct gurobipy, license-free SciPy/HiGHS, or automatic gurobipy-to-HiGHS fallback",
    )

    solve_matrix = sub.add_parser(
        "solve-matrix",
        help="solve an already generated three-line sparse coefficient matrix without rebuilding prismatoid constraints",
    )
    solve_matrix.add_argument("--matrix", type=Path, required=True)
    solve_matrix.add_argument("--output", type=Path, required=True)
    solve_matrix.add_argument("--candidate-id")
    solve_matrix.add_argument("--project", type=Path, default=Path.cwd())
    _add_license_argument(solve_matrix)
    solve_matrix.add_argument(
        "--lp-solver",
        choices=["auto", "gurobipy", "scipy-highs"],
        default="auto",
    )
    solve_matrix.add_argument("--exact-tolerance", type=float, default=1e-8)
    solve_matrix.add_argument("--gurobi-threads", type=int, default=8)
    solve_matrix.add_argument("--gurobi-method", type=int, default=0)
    solve_matrix.add_argument("--gurobi-log", type=int, default=3)

    detect = sub.add_parser("detect", help="report likely legacy solver entry points")
    detect.add_argument("--project", type=Path, default=Path.cwd())
    detect.add_argument("--output", type=Path, default=Path("entrypoint_detection.json"))

    validate = sub.add_parser("validate-data", help="validate raw box files or prepared zero-based/sorted facet files")
    validate.add_argument("--data", type=Path, required=True)

    doctor = sub.add_parser("doctor", help="check Sage, preprocessing, and an unrestricted Gurobi license")
    doctor.add_argument("--data", type=Path, required=True)
    doctor.add_argument("--project", type=Path, default=Path.cwd())
    doctor.add_argument("--entrypoint", type=Path, required=True)
    doctor.add_argument("--output", type=Path, required=True)
    _add_license_argument(doctor)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "solve-matrix":
        project_root = args.project.expanduser().resolve()
        selection = resolve_gurobi_license(args.gurobi_license, project_root=project_root)
        apply_gurobi_license(selection)
        child_env = _child_environment(project_root, selection)
        if args.lp_solver == "gurobipy":
            probe = _probe_unrestricted_gurobi(child_env)
            if probe.returncode != 0:
                _raise_failed_gurobi_preflight(probe, selection)

        import logging
        import numpy as np
        from .exact import rationalize_solution, reduce_support
        from .models import CapturedModel
        from .sage_solver_adapter import _solve_lp_and_capture

        matrix_path = args.matrix.expanduser().resolve()
        output_root = args.output.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        if not matrix_path.is_file():
            raise FileNotFoundError(f"coefficient matrix does not exist: {matrix_path}")
        candidate_id = args.candidate_id or matrix_path.stem.replace("_matrix", "")
        capture_dir = output_root / "capture"
        os.environ["PRISMATOID_CAPTURE_DIR"] = str(capture_dir)
        os.environ["PRISMATOID_CANDIDATE_ID"] = candidate_id
        os.environ["PRISMATOID_LP_SOLVER"] = args.lp_solver
        os.environ["PRISMATOID_GUROBI_THREADS"] = str(args.gurobi_threads)
        os.environ["PRISMATOID_GUROBI_METHOD"] = str(args.gurobi_method)
        os.environ["PRISMATOID_GUROBI_LOG"] = str(args.gurobi_log)

        logger = logging.getLogger(f"prismatoid.solve_matrix.{candidate_id}")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler(sys.stdout))

        class MatrixOnlyTest:
            pass

        matrix_test = MatrixOnlyTest()
        matrix_test.file_name_old = candidate_id
        matrix_test.full_file_name = str(output_root / candidate_id)
        matrix_test._batch_constraint_dict = {}
        matrix_test.logger = logger

        matrix = np.loadtxt(matrix_path).astype(np.int64)
        certificate_text, certificate_rows = _solve_lp_and_capture(matrix_test, None, M=matrix)
        capture_path = capture_dir / "model_001_post.json"
        if not capture_path.is_file():
            raise RuntimeError("matrix solve completed without writing a post-solve capture")
        model = CapturedModel.from_json(json.loads(capture_path.read_text(encoding="utf-8")))
        witness = None
        exact = False
        if model.solution_count > 0:
            witness = reduce_support(model, rationalize_solution(model, args.exact_tolerance))
            exact = bool(witness.verified)
        report_lines = [
            f"candidate: {candidate_id}",
            f"matrix: {matrix_path}",
            f"lp_backend_requested: {args.lp_solver}",
            f"lp_backend_used: {model.metadata.get('lp_backend_used', '-')}",
            f"gurobi_license_source: {selection.source}",
            f"gurobi_license_path: {selection.path or '<Gurobi default search>'}",
            f"solution_count: {model.solution_count}",
            f"exact_certificate: {'yes' if exact else 'no'}",
            f"certificate_rows_zero_based: {' '.join(map(str, certificate_rows.tolist())) if len(certificate_rows) else '-'}",
        ]
        if witness is not None:
            report_lines.extend([
                f"verification: {witness.verification_message}",
                f"active_count: {len(witness.active_variables)}",
                "coefficients:",
            ])
            for name in witness.active_variables:
                report_lines.append(f"  {name} = {witness.values[name]}")
        report_lines.extend(["", "[solver metadata]", json.dumps(model.metadata, indent=2, sort_keys=True)])
        if certificate_text:
            report_lines.extend(["", "[legacy certificate matrix]", certificate_text])
        report_path = output_root / "MATRIX_SOLVE_RESULT.txt"
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        (output_root / "MATRIX_SOLVE_RESULT.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "matrix": str(matrix_path),
                    "exact": exact,
                    "gurobi_license_source": selection.source,
                    "gurobi_license_path": str(selection.path) if selection.path else None,
                    "model_metadata": model.metadata,
                    "witness": witness.__dict__ if witness is not None else None,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"Gurobi license: {selection.path or 'Gurobi default search'} ({selection.source})")
        print(f"Matrix solve report: {report_path}")
        return 0 if exact or model.solution_count == 0 else 1

    if args.command == "detect":
        guesses = write_report(args.project.resolve(), args.output.resolve())
        print(f"wrote {len(guesses)} entry-point candidates to {args.output}")
        if guesses:
            print(f"top candidate: {guesses[0].path} (score {guesses[0].score})")
        return 0

    if args.command == "validate-data":
        candidates = enumerate_candidates(args.data)
        failures = 0
        for path in candidates:
            try:
                read_facets(path, require_prepared=True)
            except Exception as exc:
                failures += 1
                print(f"INVALID\t{path}\t{exc}")
        print(f"candidates={len(candidates)} invalid={failures}")
        return 1 if failures else 0

    if args.command == "doctor":
        data_root = args.data.expanduser().resolve()
        project_root = args.project.expanduser().resolve()
        entrypoint = args.entrypoint.expanduser().resolve()
        output_root = args.output.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        selection = resolve_gurobi_license(args.gurobi_license, project_root=project_root)
        apply_gurobi_license(selection)
        lines = [
            f"batch_package={PACKAGE_ID}",
            f"bundle_root={_bundle_root()}",
            f"cli_file={Path(__file__).resolve()}",
            f"cwd={Path.cwd()}",
            f"python_executable={sys.executable}",
            f"python_version={platform.python_version()}",
            f"data_root={data_root}",
            f"project_root={project_root}",
            f"entrypoint={entrypoint}",
            f"output_root={output_root}",
            f"gurobi_license_source={selection.source}",
            f"gurobi_license_path={selection.path or '<Gurobi default search>'}",
            f"gurobi_license_file_selected={selection.configured}",
        ]
        for diagnostic in selection.diagnostics:
            lines.append(f"gurobi_license_diagnostic={diagnostic}")
        if selection.path is not None:
            lines.append(f"gurobi_license_exists={selection.path.is_file()}")
            lines.append(f"gurobi_license_readable={os.access(selection.path, os.R_OK)}")

        ok = True
        for label, path, expected in (
            ("data_root", data_root, "dir"),
            ("project_root", project_root, "dir"),
            ("entrypoint", entrypoint, "file"),
        ):
            exists = path.is_dir() if expected == "dir" else path.is_file()
            lines.append(f"{label}_exists={exists}")
            ok = ok and exists
        try:
            import sage.version
            lines.append(f"sage_version={sage.version.version}")
            lines.append("parent_sage_import=ok")
        except Exception:
            lines.append("parent_sage_import=FAILED")
            lines.append(traceback.format_exc())
            ok = False

        child_env = _child_environment(project_root, selection)
        child = subprocess.run(
            [sys.executable, "-c", "from sage.all import ZZ; print('child_sage_import=ok', ZZ(1))"],
            env=child_env,
            text=True,
            capture_output=True,
        )
        lines.append(f"child_returncode={child.returncode}")
        lines.append("child_stdout=" + redacted_subprocess_text(child.stdout).strip())
        lines.append("child_stderr=" + redacted_subprocess_text(child.stderr).strip())
        ok = ok and child.returncode == 0

        # This model deliberately has more than 2,000 variables.  It therefore
        # distinguishes the bundled size-limited pip license from the selected
        # academic/unrestricted license before a costly prismatoid is generated.
        gurobipy_probe = _probe_unrestricted_gurobi(child_env)
        gurobi_stdout = redacted_subprocess_text(gurobipy_probe.stdout).strip()
        gurobi_stderr = redacted_subprocess_text(gurobipy_probe.stderr).strip()
        lines.append(f"gurobipy_unrestricted_probe_returncode={gurobipy_probe.returncode}")
        lines.append("gurobipy_unrestricted_probe_stdout=" + gurobi_stdout)
        lines.append("gurobipy_unrestricted_probe_stderr=" + gurobi_stderr)
        lines.append(f"gurobipy_unrestricted_license_ok={gurobipy_probe.returncode == 0}")
        gurobi_text = gurobi_stdout + "\n" + gurobi_stderr
        lines.append(
            "gurobipy_size_limited_license_detected="
            + str("Model too large for size-limited license" in gurobi_text or "Restricted license" in gurobi_text or "PIP license" in gurobi_text)
        )

        scipy_probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import scipy; "
                    "from scipy.optimize import linprog; "
                    "r=linprog([0.0], A_eq=[[1.0]], b_eq=[1.0], "
                    "bounds=[(0.0, None)], method='highs'); "
                    "print('scipy_version=' + scipy.__version__); "
                    "print('highs_status=' + str(r.status)); "
                    "assert r.success"
                ),
            ],
            env=child_env,
            text=True,
            capture_output=True,
        )
        lines.append(f"scipy_highs_probe_returncode={scipy_probe.returncode}")
        lines.append("scipy_highs_probe_stdout=" + redacted_subprocess_text(scipy_probe.stdout).strip())
        lines.append("scipy_highs_probe_stderr=" + redacted_subprocess_text(scipy_probe.stderr).strip())
        lp_solver_ok = gurobipy_probe.returncode == 0 or scipy_probe.returncode == 0
        lines.append(f"lp_solver_auto_available={lp_solver_ok}")
        ok = ok and lp_solver_ok
        # If a concrete project/CLI license was found, doctor must verify that
        # gurobipy can actually use it without the pip size limit.
        if selection.configured:
            ok = ok and gurobipy_probe.returncode == 0

        try:
            candidates = enumerate_candidates(data_root)
            lines.append(f"candidate_count={len(candidates)}")
            if not candidates:
                raise RuntimeError("no candidates found")
            prepared = output_root / "doctor_prepared" / f"{candidates[0].name}.txt"
            record = prepare_candidate(
                candidates[0],
                prepared,
                mode="external",
                bundled_tools_dir=_bundle_root() / "preprocessing",
            )
            lines.append(f"first_candidate={candidates[0]}")
            lines.append(f"prepared_candidate={prepared}")
            lines.append(f"preparation_mode={record.mode}")
            lines.append("preparation=ok")
        except Exception:
            lines.append("preparation=FAILED")
            lines.append(traceback.format_exc())
            ok = False

        report = output_root / "DOCTOR.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Gurobi license: {selection.path or 'Gurobi default search'} ({selection.source})")
        print(f"Doctor report: {report}")
        if gurobipy_probe.returncode == 0:
            print("Doctor Gurobi note: unrestricted gurobipy probe passed (2,101-variable model).")
        elif scipy_probe.returncode == 0:
            print("Doctor Gurobi note: the selected/default Gurobi license failed the unrestricted probe; SciPy/HiGHS remains available.")
        print("Doctor status: " + ("OK" if ok else "FAILED"))
        return 0 if ok else 1

    data_root = args.data.expanduser().resolve()
    project_root = args.project.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    entrypoint = args.entrypoint.expanduser().resolve() if args.entrypoint else None
    if not data_root.is_dir():
        raise FileNotFoundError(f"data directory does not exist: {data_root}")
    if not project_root.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_root}")
    if entrypoint is not None and not entrypoint.is_file():
        raise FileNotFoundError(f"entrypoint does not exist: {entrypoint}")
    if entrypoint is not None:
        try:
            entrypoint.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                f"entrypoint must be inside the project copied into each sandbox: {entrypoint} is not under {project_root}"
            ) from exc
    output_root.mkdir(parents=True, exist_ok=True)

    selection = resolve_gurobi_license(args.gurobi_license, project_root=project_root)
    apply_gurobi_license(selection)
    if args.lp_solver == "gurobipy":
        probe = _probe_unrestricted_gurobi(_child_environment(project_root, selection))
        if probe.returncode != 0:
            _raise_failed_gurobi_preflight(probe, selection)

    options = PipelineOptions(
        data_root=data_root,
        project_root=project_root,
        output_root=output_root,
        entrypoint=entrypoint,
        interpreter=args.interpreter,
        prepare_mode=args.prepare_mode,
        preprocess_command=args.preprocess_command,
        reorder_command=args.reorder_command,
        timeout=args.timeout,
        resume=not args.no_resume,
        start=args.start,
        stop=args.stop,
        limit=args.limit,
        vertex_counts=(
            tuple(sorted(set(args.vertex_counts))) if args.vertex_counts else None
        ),
        exact_tolerance=args.exact_tolerance,
        keep_sandboxes=args.keep_sandboxes,
        template_first=bool(args.template_first and not args.no_template_first),
        max_templates=args.max_templates,
        dimension=args.dimension,
        n_factors=args.n_factors,
        max_deg=args.max_degree,
        search_variant=args.search_variant,
        random_seed=args.random_seed,
        flag_attempts=args.flag_attempts,
        gurobi_threads=args.gurobi_threads,
        gurobi_method=args.gurobi_method,
        gurobi_log=args.gurobi_log,
        lp_solver=args.lp_solver,
        gurobi_license=selection.path,
        gurobi_license_source=selection.source,
    )
    return BatchPipeline(options).run()


if __name__ == "__main__":
    raise SystemExit(main())
