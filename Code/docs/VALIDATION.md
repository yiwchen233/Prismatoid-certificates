# Validation of the readable edition

Validated on 2026-10-21.

## Archived results

All **4,091** original proof bundles were converted to the short certificate
and four supporting text files. For every candidate:

1. Read the corresponding original raw input and recover its prepared facets.
2. Confirm those facets match the saved proof.
3. Write the human-readable matrix, bases, pivots, orientations, generator
   sources and polynomials, and rational weights.
4. Read those text files back, checking that every mathematical field matches
   the original proof and that the coefficient table matches the polynomials.
5. Independently verify the reconstructed certificate against the input facets.

All 4,091 passed. The same existing independent arithmetic checker is used;
the search's packed monomial representation is decoded before presentation.
These checks did not rerun the original full-dataset numerical searches.

## Runtime changes and tests

The reduced-matrix construction, polynomial generation, exact acceptance
routine, and independent verifier are retained. LP assembly and direct Gurobi /
SciPy solver functions were extracted from the previous adapter. The new batch
coordinator isolates each attempt in temporary space and publishes only the
verified successful witness. The stable Python and shell launchers remain.

The current suite reports **23 passed, 1 skipped**, with four additional passing
corruption subtests. Tests cover the actual mathematical core, a real SciPy/HiGHS
search, readable proof verification, explicit-flag reruns, successful resume,
configuration mismatch rejection, empty selection, failed-attempt cleanup,
polynomial decoding, and rejection of altered matrices, generators, signs,
weights, and coefficient tables.

Validation environment: Windows; Python 3.12.14; NumPy 2.5.4; SciPy 1.18.1;
SymPy 1.14.0; pytest 9.1.1. Python 3.11 was the earlier baseline.

The skipped test requires native Sage. Gurobi was not installed or exercised
in this validation; its retained backend needs the user's license. A successful
example run does not establish search completeness, and an unsuccessful bounded
search makes no assertion of realizability.
