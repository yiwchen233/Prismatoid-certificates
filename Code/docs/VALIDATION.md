# Validation record

The initial cleaned code distribution was validated on 2026-10-07 in native Windows with Python 3.11.9:

| Dependency | Version used |
| --- | --- |
| NumPy | 1.26.4 |
| SciPy / bundled HiGHS backend | 1.10.1 |
| SymPy | 1.14.0 |
| NetworkX | 3.6.1 |
| pytest | 9.1.1 |

`python -m pytest -q Code/tests` (from the current repository root): **29 passed, 5 skipped**, plus four passing corruption
subtests. The skipped tests are one native Sage polynomial-conversion test and
four tests requiring POSIX executable scripts/Bash. They are retained for runs
on a suitable Linux/macOS/WSL environment; skipping does not validate Sage.

The first Windows run exposed temporary-directory teardown failures caused by
open logger/database handles. Logger replacement now closes old handlers, and
test cleanup closes resources before deleting their temporary directories.
All executable Windows tests passed after these changes.

## Real mathematical smoke test

Ran `Code/examples/prepared/0213.txt` through the actual batch CLI and patched core,
using SciPy/HiGHS, prepared input, two factors, degree 3, the extended search
variant, seed 0, at most two flags, and a 180-second per-invocation timeout.

- Candidate: `0213`, 15 vertices.
- Result: `certificate_exact`, first flag attempt.
- Independent verifier: `verified_exact`, **3 terms**.
- Independent checks include rank, facet bases, positive scaling, orientation,
  and exact positive rational identity.
- Integration regression repeats the command and checks that resume preserves
  the proof file without rerunning the completed candidate.
- Integration regression runs from outside the repository and uses paths with
  spaces.

Generated local validation results are outside the publishable repository and
are not bundled as evidence that every input works. Users can regenerate the
example with the README commands.

## Additional checks

- All 13 patch-payload files matched their installed counterparts byte for byte.
- Python files parsed/compiled and local dependency paths were inspected.
- Git Bash: shell syntax check, `--version`, and `validate-data` passed; the
  example reported `candidates=1 invalid=0`.
- Publication ZIP excludes credentials, Python caches, old dumps, and validation
  work directories. Source and archive inventories were checked before delivery.

## Not validated here

- Gurobi execution or the private Gurobi license.
- Native Sage mathematical behavior and full POSIX/Sage launcher regressions.
- Full-dataset recomputation: the data and archived results are now included in
  the repository, but were not part of the original `Code.zip` validation.
- The 20-vertex, 10,000-flag, ten-hour-per-invocation experiment.
- General dimensions/input classes outside the independent verifier's supported
  five-dimensional prismatoids.

This is a packaging and regression validation, not a new mathematical correctness
proof or a claim of exhaustive non-realizability detection.


## Layout update

Runtime files, examples, tests, and these technical documents were relocated
together under `Code/`; their internal relative paths are unchanged. See the
root [README](../../README.md) for current commands. Archived results were not
rewritten or regenerated during this move.
