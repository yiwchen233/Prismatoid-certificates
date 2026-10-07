from fractions import Fraction
from pathlib import Path
import json

from prismatoid_batch.facet_io import normalize_facet_file, read_facets
from prismatoid_batch.models import CapturedModel, LinearVariable, LinearConstraint
from prismatoid_batch.exact import rationalize_solution, reduce_support, verify_values
from prismatoid_batch.model_graph import build_support_graph, canonical_hash, graphs_isomorphic


def test_facet_normalization(tmp_path):
    raw = tmp_path / "raw"
    raw.write_text("3 1 2\n4 2 1\n")
    out = tmp_path / "out"
    complex_ = normalize_facet_file(raw, out)
    assert complex_.vertices == (0, 1, 2, 3)
    assert out.read_text() == "0 1 2\n0 1 3\n"


def _model():
    return CapturedModel(
        "test",
        [
            LinearVariable("x", "0", "1e100", value="0.5"),
            LinearVariable("y", "0", "1e100", value="0.5"),
            LinearVariable("z", "0", "1e100", value="0"),
        ],
        [
            LinearConstraint("normalization", "=", "1", {"x": "1", "y": "1", "z": "1"}),
            LinearConstraint("identity", "=", "0", {"x": "1", "y": "-1"}),
        ],
        status=2,
        solution_count=1,
    )


def test_exact_reconstruction_and_graph():
    model = _model()
    witness = rationalize_solution(model)
    assert witness.verified
    assert witness.values["x"] == "1/2"
    assert witness.values["y"] == "1/2"
    graph = build_support_graph(model, witness.active_variables)
    assert graphs_isomorphic(graph, graph)
    assert len(canonical_hash(graph)) == 64
