from __future__ import annotations
from contextlib import ExitStack

from pathlib import Path
import json
import tempfile
import unittest

from prismatoid_batch.cli import build_parser
from prismatoid_batch.flag_search import (
    flag_intersection_cardinalities,
    flag_literal,
    is_simplicial_facet_flag,
    parse_flag_indices,
    sample_simplicial_facet_flags,
    _triangular_rank_witness,
)
from prismatoid_batch.legacy_runner import RunRecord
from prismatoid_batch.pipeline import BatchPipeline, PipelineOptions


# Boundary complex of a three-dimensional octahedron.  Each facet chooses one
# vertex from each opposite pair (0,1), (2,3), and (4,5).
OCTAHEDRON_FACETS = tuple(
    (a, b, c)
    for a in (0, 1)
    for b in (2, 3)
    for c in (4, 5)
)


def _write_facets(path: Path) -> None:
    path.write_text(
        "".join(" ".join(map(str, facet)) + "\n" for facet in OCTAHEDRON_FACETS),
        encoding="utf-8",
    )


class FlagSearchTests(unittest.TestCase):
    def test_macaulay2_flag_literal_round_trip_preserves_order(self):
        self.assertEqual(flag_literal((3, 1, 4, 2)), "{3, 1, 4, 2}")
        self.assertEqual(parse_flag_indices("{3, 1, 4, 2}"), (3, 1, 4, 2))
        self.assertIsNone(parse_flag_indices("{}"))

    def test_cli_accepts_flag_attempt_count(self):
        args = build_parser().parse_args(
            [
                "run",
                "--data",
                "/tmp/data",
                "--output",
                "/tmp/output",
                "--flag-attempts",
                "4",
            ]
        )
        self.assertEqual(args.flag_attempts, 4)

    def test_sampler_is_deterministic_distinct_and_checked(self):
        first = sample_simplicial_facet_flags(
            OCTAHEDRON_FACETS,
            3,
            6,
            random_seed=23,
            candidate_id="octahedron",
        )
        second = sample_simplicial_facet_flags(
            OCTAHEDRON_FACETS,
            3,
            6,
            random_seed=23,
            candidate_id="octahedron",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6)
        self.assertEqual(len({frozenset(flag) for flag in first}), 6)
        for flag in first:
            self.assertTrue(
                is_simplicial_facet_flag(OCTAHEDRON_FACETS, flag, 3)
            )
            self.assertEqual(
                flag_intersection_cardinalities(OCTAHEDRON_FACETS, flag),
                (3, 2, 1, 0),
            )

    def test_pipeline_tries_default_then_checked_distinct_flags(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as cleanup:
            root = Path(temporary)
            data = root / "data"
            project = root / "project"
            output = root / "output"
            data.mkdir()
            project.mkdir()
            source = data / "octahedron.txt"
            _write_facets(source)

            pipeline = BatchPipeline(
                PipelineOptions(
                    data_root=data,
                    project_root=project,
                    output_root=output,
                    dimension=3,
                    flag_attempts=4,
                    random_seed=5,
                )
            )
            cleanup.callback(pipeline.db.connection.close)
            calls: list[dict] = []

            def fake_solve(prepared, cid, allowed=None, capture_only=False, **kwargs):
                calls.append(
                    {
                        "prepared": prepared,
                        "cid": cid,
                        "allowed": allowed,
                        "capture_only": capture_only,
                        **kwargs,
                    }
                )
                sandbox = root / f"sandbox_{len(calls)}"
                sandbox.mkdir()
                return RunRecord(
                    command=["fake-solver"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    captures=[],
                    elapsed_seconds=0.01,
                    sandbox=sandbox,
                    artifacts=[],
                )

            pipeline._solve = fake_solve  # type: ignore[method-assign]
            result = pipeline.process_one(
                source, "octahedron", "digest", vertex_count=6
            )

            self.assertEqual(result.status, "no_certificate")
            self.assertEqual(len(calls), 4)
            self.assertEqual(calls[0]["flag"], "{}")
            self.assertFalse(calls[0]["force_new_flag"])
            explicit = [parse_flag_indices(call["flag"]) for call in calls[1:]]
            self.assertTrue(all(flag is not None for flag in explicit))
            self.assertEqual(
                len({frozenset(flag) for flag in explicit if flag is not None}),
                3,
            )
            for flag in explicit:
                assert flag is not None
                self.assertIsNotNone(_triangular_rank_witness(
                    [[v not in OCTAHEDRON_FACETS[j] for j in flag] for v in range(6)]
                ))
            self.assertEqual(len(result.flag_attempts), 4)
            self.assertTrue(
                all(
                    attempt["combinatorially_checked"]
                    for attempt in result.flag_attempts[1:]
                )
            )
            self.assertTrue(result.flag_attempts[0]["selected_for_final_result"])


    def test_pipeline_stops_after_first_exact_alternate_flag(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as cleanup:
            root = Path(temporary)
            data = root / "data"
            project = root / "project"
            output = root / "output"
            data.mkdir()
            project.mkdir()
            source = data / "octahedron.txt"
            _write_facets(source)

            pipeline = BatchPipeline(
                PipelineOptions(
                    data_root=data,
                    project_root=project,
                    output_root=output,
                    dimension=3,
                    flag_attempts=5,
                    random_seed=7,
                )
            )
            cleanup.callback(pipeline.db.connection.close)
            calls: list[dict] = []

            def fake_solve(prepared, cid, allowed=None, capture_only=False, **kwargs):
                calls.append(kwargs)
                sandbox = root / f"exact_sandbox_{len(calls)}"
                capture_dir = sandbox / "capture"
                capture_dir.mkdir(parents=True)
                captures: list[Path] = []
                if len(calls) == 2:
                    model_path = capture_dir / "model_001_post.json"
                    model_path.write_text(
                        json.dumps(
                            {
                                "name": "mock-exact-certificate",
                                "variables": [
                                    {
                                        "name": "lambda_000000001",
                                        "lb": "0",
                                        "ub": "inf",
                                        "vtype": "C",
                                        "objective": "0",
                                        "value": "1",
                                    }
                                ],
                                "constraints": [
                                    {
                                        "name": "normalization",
                                        "sense": "=",
                                        "rhs": "1",
                                        "coefficients": {
                                            "lambda_000000001": "1"
                                        },
                                    }
                                ],
                                "status": 2,
                                "solution_count": 1,
                                "objective_value": "0",
                                "optimize_index": 0,
                                "unsupported_features": [],
                                "metadata": {},
                            },
                            indent=2,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    captures = [model_path]
                return RunRecord(
                    command=["fake-solver"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    captures=captures,
                    elapsed_seconds=0.01,
                    sandbox=sandbox,
                    artifacts=[],
                )

            pipeline._solve = fake_solve  # type: ignore[method-assign]
            result = pipeline.process_one(
                source, "octahedron", "digest", vertex_count=6
            )

            self.assertEqual(result.status, "certificate_exact")
            self.assertTrue(result.exact)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(result.flag_attempts), 2)
            self.assertFalse(result.flag_attempts[0]["selected_for_final_result"])
            self.assertTrue(result.flag_attempts[1]["selected_for_final_result"])
            flag_metadata = result.metadata["flag_search"]
            self.assertTrue(flag_metadata["stopped_after_exact_certificate"])
            self.assertEqual(flag_metadata["sampled_checked_flags_generated"], 4)
            self.assertEqual(flag_metadata["sampled_checked_attempts_executed"], 1)
            self.assertEqual(flag_metadata["sampled_checked_flag_count"], 1)


    def test_pipeline_rejects_too_many_nonsimplicial_facets(self):
        # Boundary facets of a cube: all facets are quadrilaterals, so the
        # sufficient simplicial-first sampler intentionally returns no flag.
        cube_facets = (
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            (0, 1, 4, 5),
            (1, 2, 5, 6),
            (2, 3, 6, 7),
            (0, 3, 4, 7),
        )
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as cleanup:
            root = Path(temporary)
            data = root / "data"
            project = root / "project"
            output = root / "output"
            data.mkdir()
            project.mkdir()
            source = data / "cube.txt"
            source.write_text(
                "".join(" ".join(map(str, facet)) + "\n" for facet in cube_facets),
                encoding="utf-8",
            )

            pipeline = BatchPipeline(
                PipelineOptions(
                    data_root=data,
                    project_root=project,
                    output_root=output,
                    dimension=3,
                    flag_attempts=3,
                    random_seed=11,
                )
            )
            cleanup.callback(pipeline.db.connection.close)
            calls: list[dict] = []

            def fake_solve(prepared, cid, allowed=None, capture_only=False, **kwargs):
                calls.append(kwargs)
                sandbox = root / f"fallback_sandbox_{len(calls)}"
                sandbox.mkdir()
                return RunRecord(
                    command=["fake-solver"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    captures=[],
                    elapsed_seconds=0.01,
                    sandbox=sandbox,
                    artifacts=[],
                )

            pipeline._solve = fake_solve  # type: ignore[method-assign]
            with self.assertRaisesRegex(ValueError, 'Too many nonsimplicial'):
                pipeline.process_one(source, "cube", "digest", vertex_count=8)
            self.assertEqual(len(calls), 1)



if __name__ == "__main__":
    unittest.main()
