# Validation

Validated on 2026-10-21.

## Archived results

All **4,091** certificates and their supporting text files were checked against
the corresponding raw inputs. For every candidate, validation included:

1. Recover the prepared facets from the raw input and compare them with the
   saved facets and original vertex-label mapping.
2. Read the reduced matrix, ordered bases, rank pivots, orientations, generator
   sources and polynomials, and rational weights from the text files.
3. Recompute the coefficient table from the displayed polynomials and weights
   and compare it with the saved table.
4. Independently verify the reconstructed certificate against the input facets.

All 4,091 passed these checks. The checker uses exact arithmetic and does not
require an LP solver. Run it from the repository root:

```bash
python Code/human_certificate.py Results --data "Prismatoid data"
```

## Search and tests

The batch runner isolates each search attempt in temporary space and saves a
certificate only after exact verification succeeds.

Tests cover the mathematical core, a real SciPy/HiGHS search, readable proof
verification, explicit-flag reruns, successful resume, configuration mismatch
rejection, empty selection, failed-attempt cleanup, polynomial decoding, and
rejection of altered matrices, generators, signs, weights, and coefficient tables.

Run the tests from the repository root:

```bash
python -m pytest -q Code/tests
```

Validation environment: Windows; Python 3.12.14; NumPy 2.5.4; SciPy 1.18.1;
SymPy 1.14.0; pytest 9.1.1.

The Sage test was skipped because native Sage was unavailable. Gurobi was not
installed or exercised in this validation; its backend requires the user's
license. A successful example run does not establish search completeness, and
an unsuccessful bounded search makes no assertion of realizability.
