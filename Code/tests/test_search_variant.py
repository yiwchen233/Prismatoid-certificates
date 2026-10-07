from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from prismatoid_batch.cli import build_parser
from prismatoid_batch.sage_solver_adapter import execute_nonrealizability


_FAKE_LEGACY = r'''
CORE_PATCH_VERSION = '1.2.9-core-patch'
import json
import os
from pathlib import Path
import sympy as sp

class Logger:
    def info(self, *args, **kwargs):
        pass
    def warning(self, *args, **kwargs):
        pass

class Ring:
    def __init__(self):
        self._gens = sp.symbols("x1 x2")
    def gens(self):
        return self._gens
    def __call__(self, value):
        return sp.sympify(value, locals={str(x): x for x in self._gens})

class NonRealizabilityTest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.logger = Logger()
        self.R = Ring()
    def get_products(self, constraint_dict):
        keys = list(constraint_dict)
        if self.n_factors == 1:
            return dict(constraint_dict)
        out = dict(constraint_dict)
        for j, right in enumerate(keys):
            for i in range(j + 1):
                out[sp.expand(keys[i] * right)] = ["product"]
        return out
    @property
    def run(self):
        x1, x2 = self.R.gens()
        products = self.get_products({x1 + x2: [[(0, 0)], 1]})
        payload = {
            "small_determinants": self.small_determinants,
            "count": len(products),
            "products": sorted(str(sp.expand(p)) for p in products),
            "stats": getattr(self, "_batch_generator_statistics", {}),
            "flag": self.flag,
            "force_new_flag": self.force_new_flag,
            "random_seed": self.random_seed,
        }
        capture = Path(os.environ["PRISMATOID_CAPTURE_DIR"])
        capture.mkdir(parents=True, exist_ok=True)
        (capture / "fake_products.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return 0
'''


class SearchVariantTests(unittest.TestCase):
    def test_cli_accepts_extended_variant(self):
        args = build_parser().parse_args(
            [
                "run",
                "--data",
                "/tmp/data",
                "--output",
                "/tmp/output",
                "--search-variant",
                "all-variable-products-simplified",
            ]
        )
        self.assertEqual(args.search_variant, "all-variable-products-simplified")

    def _run_fake(self, variant: str, extra_environment: dict[str, str] | None = None) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entrypoint = root / "fake_legacy.py"
            entrypoint.write_text(textwrap.dedent(_FAKE_LEGACY), encoding="utf-8")
            candidate = root / "candidate.txt"
            candidate.write_text("0 1\n0 2\n1 2\n", encoding="utf-8")
            capture = root / "capture"
            environment = {
                "PRISMATOID_INPUT_FILE": str(candidate),
                "PRISMATOID_CANDIDATE_ID": "test",
                "PRISMATOID_CAPTURE_DIR": str(capture),
                "PRISMATOID_N_FACTORS": "2",
                "PRISMATOID_SEARCH_VARIANT": variant,
            }
            if extra_environment:
                environment.update(extra_environment)
            with patch.dict(os.environ, environment, clear=False):
                self.assertEqual(execute_nonrealizability(entrypoint), 0)
            payload = json.loads((capture / "fake_products.json").read_text(encoding="utf-8"))
            payload["adapter_result"] = json.loads(
                (capture / "adapter_result.json").read_text(encoding="utf-8")
            )
            return payload


    def test_adapter_forwards_explicit_flag_and_records_metadata(self):
        result = self._run_fake(
            "legacy",
            {
                "PRISMATOID_FLAG": "{1, 2, 3}",
                "PRISMATOID_FORCE_NEW_FLAG": "true",
                "PRISMATOID_FLAG_ATTEMPT_INDEX": "2",
                "PRISMATOID_FLAG_SOURCE": "unit-test",
                "PRISMATOID_RANDOM_SEED": "17",
            },
        )
        self.assertEqual(result["flag"], "{1, 2, 3}")
        self.assertEqual(result["force_new_flag"], "true")
        self.assertEqual(result["random_seed"], 17)
        metadata = result["adapter_result"]["flag_search"]
        self.assertEqual(metadata["attempt_index_zero_based"], 2)
        self.assertEqual(metadata["source"], "unit-test")
        self.assertEqual(metadata["requested_flag"], "{1, 2, 3}")
        self.assertTrue(metadata["force_new_flag"])
        self.assertEqual(metadata["random_seed"], 17)

    def test_extended_variant_uses_variables_and_simplification(self):
        result = self._run_fake("all-variable-products-simplified")
        self.assertEqual(result["small_determinants"], "true")
        self.assertEqual(result["count"], 9)
        self.assertEqual(result["stats"]["base_generator_count_with_variables"], 3)
        self.assertEqual(result["stats"]["reduced_slack_variables_added"], 2)
        self.assertIn("x1*x2", result["products"])
        self.assertIn("x1**2 + x1*x2", result["products"])

    def test_legacy_variant_is_unchanged(self):
        result = self._run_fake("legacy")
        self.assertEqual(result["small_determinants"], "false")
        self.assertEqual(result["count"], 2)
        self.assertNotIn("x1*x2", result["products"])


if __name__ == "__main__":
    unittest.main()
