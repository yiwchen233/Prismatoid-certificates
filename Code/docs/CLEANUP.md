# Publication cleanup audit

This audit describes the original cleanup from `Code.zip`. Code paths in the
original mapping below are relative to the current `Code/` directory. The original ZIP and synced project
sources were not modified. `source-map.json` maps retained files to archive
paths and records their original SHA-256 hashes.

## Consolidation

| Original location (inside Code.zip) | Publication location / decision |
| --- | --- |
| `Code/Code/src/nonrealizability_certificate.py`, `src/modules/` | `core/src/`; keep all eight modules because the core imports them, including conditional Sage imports and the independent checker. |
| `Code/prismatoid_batch_bundle/prismatoid_batch/` | `prismatoid_batch/`; update imports, subprocess module names, and package-copy paths. |
| Original batch launchers | Stable root-level `run_prismatoid_batch.py` and `.sh`. |
| New batch `legacy_tools/` | `preprocessing/`; update lookup paths and replace private absolute paths with the input/output environment variables already supplied by the runner. |
| New batch tests and core-patch tests | `tests/`; adjust imports and fixture paths. |
| Older `Code/Code/tests_batch/*.py` | Keep and run against the consolidated batch package; these cover exact LP checks, templates, and Sage invocation conventions. |
| Core-patch `tests/fixtures/0213.txt` | `examples/prepared/0213.txt`; tests use this one copy. |

## Exclusions

- `Code/Code/prismatoid_batch/` and its root launchers: superseded by the
  integrated batch package used by the user's command.
- `prismatoid_core_patch/payload/`: all **13 files** are byte-for-byte
  identical to the installed files. The patch installer, diff, and manifest are
  historical deployment machinery, unnecessary in an integrated distribution.
- `fake_solver.py`: no source or test references it; retained tests contain
  their own explicit mocks. No production search depends on it.
- `src/app.py`: unrelated Flask hello-world app, with no solver references.
- `src/run_matlab.sh`, `src/solve_lp_gurobi_matlab.sh`: no Python references;
  historical MATLAB replay is outside the supported patched workflow.
- `src/database/*.txt`, `src/Altshuler_M963_orientation.txt`, and `src/dump/`:
  historical datasets, saved reductions, and generated artifacts. The active
  batch adapter supplies explicit facets; the dormant text-file loader is not
  called by the patched run path. The still-imported in-code sphere database is
  retained for Sage compatibility.
- The older duplicate `legacy_tools/`, Docker/Flask development setup,
  patch-install instructions, old READMEs/changelogs, generated detection
  reports, saved validation outputs, test logs, caches, and Zone.Identifier
  sidecars: superseded documentation or non-source artifacts. New documentation
  describes the integrated layout and does not repeat old validation claims.
- `dev/gurobi.lic`: private credential; excluded without displaying its contents.
  It remains in the original private archive. The publishable ZIP contains no
  license credential, cache, or historical result dump.

## Dependency audit

Every retained production code file has an identified caller or entry-point role:

- Launchers and `__main__.py` invoke `cli.py`; `__init__.py` exports shared models.
- CLI uses autodetection, facet I/O, preparation, license configuration, pipeline,
  and LP adapter commands.
- Pipeline uses flag search, exact reconstruction, state, models, template
  library, and the legacy runner. Template library uses model graph routines.
- Runner launches `legacy_wrapper.py` in a subprocess; wrapper loads the Gurobi
  hook or patched-core adapter. These are dynamic dependencies, not dead files.
- Preparation invokes `helper_scripts.py`, which runs
  `helper_function_driver.py` and the two bundled preprocessing scripts.
- The core imports logger, parser, geometry, polynomial backend, and conditional
  Sage helpers (matrix, slack ideals, and sphere database); it invokes the
  independent verifier for supported certificate bundles.

The audit combines source/import/subprocess tracing with regression tests and
an actual batch run. It establishes file-level use, not execution coverage of
every legacy branch. Conditional Sage functionality has been retained rather
than deleted merely because Sage is absent from the validation machine.

## Small compatibility changes

- Close replaced log handlers to avoid retaining open files across core runs.
- Close test database handles before temporary-directory cleanup on Windows;
  close the final core-test logger before cleanup.
- Explicitly skip POSIX executable-script tests on native Windows or without Bash.
- Add a real batch example/independent-verification/resume regression.
- Update an old adapter error message to the integrated core location.

Search mathematics, degree/factor defaults, solver selection, and certificate
acceptance rules were otherwise retained. The adapter checks the descriptive
`CORE_INTERFACE = "prismatoid-exact-core"` marker to identify the supported core.

## Remaining publication decisions

The current repository includes an MIT [LICENSE](../../LICENSE), the full
`Prismatoid data/` collection, and archived `Results/n14/` through `Results/n28/`.
These were added after the original archive cleanup. Upstream data attribution
and redistribution terms remain separate from the software license. No claim
is made that the reorganization reran the full Gurobi experiments.


## Repository reorganization

All solver code, launchers, dependencies, tests, examples, and technical
documentation now live in `Code/`. The main README, LICENSE, Git configuration,
raw data, and archived results remain at the repository root. Relative layout
inside `Code/` is unchanged, so imports and test fixture discovery remain valid.
The root README uses repository-root commands and writes new output to `runs/`.
The source map's publication destinations now include the `Code/` prefix.

## Release-label cleanup

Project release labels have been replaced with descriptive names throughout the
source, tests, documentation, archived text outputs, and resume databases.
Historical archive and output path strings are normalized labels, not verbatim
original paths. Source hashes still identify the original archive bytes;
publication hashes describe the current retained files. Dependency versions and
file-format versions are retained. Certificate coefficients, facets, witnesses,
search settings, and recorded outcomes are unchanged. The `--info` option reports
the runner identity; `--version` remains an alias for existing commands.
