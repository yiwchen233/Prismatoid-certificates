from __future__ import annotations
from contextlib import ExitStack

from pathlib import Path
import csv
import tempfile
import unittest

from prismatoid_batch.cli import build_parser
from prismatoid_batch.facet_io import candidate_vertex_count
from prismatoid_batch.pipeline import BatchPipeline, PipelineOptions


def _write_box_candidate(path: Path, lower: list[int], upper: list[int]) -> None:
    # The parser only requires a valid box header and all source vertices to
    # occur in the declared lateral facets. One synthetic lateral facet is
    # sufficient for selection/filter tests.
    vertices = lower + upper
    path.write_text(
        "5 1\n" + " ".join(map(str, vertices)) + "\n",
        encoding="utf-8",
    )


class VertexFilterTests(unittest.TestCase):
    def test_cli_accepts_repeatable_vertex_counts(self):
        args = build_parser().parse_args(
            [
                "run",
                "--data",
                "/tmp/data",
                "--output",
                "/tmp/output",
                "--vertex-count",
                "15",
                "--vertex-count",
                "14",
                "--vertex-count",
                "15",
            ]
        )
        self.assertEqual(args.vertex_counts, [15, 14, 15])

    def test_raw_box_vertex_count(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as cleanup:
            path = Path(temporary) / "0001"
            _write_box_candidate(path, list(range(7)), list(range(14, 21)))
            self.assertEqual(candidate_vertex_count(path), 14)

    def test_pipeline_filters_before_start_and_limit_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as cleanup:
            root = Path(temporary)
            data = root / "data"
            project = root / "project"
            output = root / "output"
            data.mkdir()
            project.mkdir()

            _write_box_candidate(data / "0001", list(range(7)), list(range(14, 21)))  # 14
            _write_box_candidate(data / "0002", list(range(8)), list(range(14, 21)))  # 15
            _write_box_candidate(data / "0003", list(range(7)), list(range(14, 21)))  # 14
            _write_box_candidate(data / "0004", list(range(9)), list(range(14, 21)))  # 16
            _write_box_candidate(data / "0005", list(range(7)), list(range(14, 21)))  # 14

            pipeline = BatchPipeline(
                PipelineOptions(
                    data_root=data,
                    project_root=project,
                    output_root=output,
                    vertex_counts=(14,),
                    start=1,
                    limit=1,
                )
            )
            cleanup.callback(pipeline.db.connection.close)
            selected = pipeline._select_candidates()
            self.assertEqual([(path.name, n) for path, n in selected], [("0003", 14)])

            with (output / "CANDIDATE_SELECTION.tsv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["candidate"], "0003")
            self.assertEqual(rows[0]["vertex_count"], "14")

            summary = (output / "SELECTION_SUMMARY.txt").read_text(encoding="utf-8")
            self.assertIn("after_vertex_filter: 3", summary)
            self.assertIn("selected_for_run: 1", summary)


if __name__ == "__main__":
    unittest.main()
