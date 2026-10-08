# Prismatoid non-realizability certificates

This repository searches for exact non-realizability certificates from facet
descriptions of polytopes. It combines a slack-matrix certificate solver with a
batch runner that prepares inputs, tries different reductions (flags), solves
linear programs, checks rational witnesses, and saves reports and reusable
certificate templates.

The included solver is integrated with the batch runner; no separate patch
installation is needed. The supported example and independent geometric verifier
concern **five-dimensional prismatoids with two disjoint nonsimplicial bases
listed first**. The code searches for certificates that prove non-realizability.
If no certificate is found, the input may still be non-realizable: the search
only covers the chosen flags and degree/factor bounds. It does not determine
realizability for every input. For other input classes, an exact polynomial
identity alone is insufficient unless its geometric positivity assumptions
are also verified.

## Requirements

- **Python 3.11** is the validated baseline (tested with 3.11.9). Other Python
  versions have not been validated for this distribution.
- NumPy, SciPy, SymPy, and NetworkX; install from `Code/requirements.txt`.
- An LP backend: **SciPy/HiGHS** (included, no license required), or
  **Gurobi** through `gurobipy` with an appropriate Gurobi license.
- Bash for the `.sh` launcher, normally on Linux, macOS, or Windows through
  WSL. The `.py` launcher also runs directly in native Windows Python.
- **SageMath is optional**: ordinary Python uses the exact sparse polynomial
  backend. If you choose Sage, install the dependencies in Sage's Python
  environment; see the [SageMath installation guide](https://www.sagemath.org/doc/installation/).
  Macaulay2, MATLAB, Docker, and Flask are not needed for the documented workflow.

The requirements files specify dependency floors, not a claim that every newer
combination has been tested. See [validation details](Code/docs/VALIDATION.md) for the
actual environment and untested backends. Large searches can use substantial
memory, disk space, and time; no universal hardware minimum has been established.

## Installation

Download this repository as a ZIP and extract it, or clone it using its GitHub
URL. Open a terminal in the repository's top-level folder (the folder containing
this README and the `Code/` directory). On Linux/macOS/WSL:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r Code/requirements.txt
python Code/run_prismatoid_batch.py --info
```

On native Windows PowerShell, create the environment with `python -m venv .venv`
and use `.\.venv\Scripts\python.exe` in place of `python` in subsequent commands.
The examples below use Bash line continuations; enter them on one line when
using PowerShell. There is no separate package installation step: run from the
source checkout. For a Git clone, `git pull` updates the source.

### Gurobi setup

In the same environment:

```bash
python -m pip install -r Code/requirements-gurobi.txt
export GRB_LICENSE_FILE="/absolute/path/to/gurobi.lic"
python -c 'import gurobipy as gp; m = gp.Model(); m.addVar(); m.optimize()'
```

See Gurobi's [Python installation instructions](https://support.gurobi.com/hc/en-us/articles/360044290292-How-do-I-install-Gurobi-for-Python)
and [license environment configuration](https://support.gurobi.com/hc/en-us/articles/13443862111761-How-do-I-set-system-environment-variables-for-Gurobi).
Keep the license outside the public repository. No Gurobi license is distributed
here; `*.lic` files are ignored by Git.

You can also pass `--gurobi-license "/absolute/path/to/gurobi.lic"` to `run`.
This explicit option takes precedence. Otherwise the runner looks in
`<project>/dev/gurobi.lic`, then `GRB_LICENSE_FILE`, then `<project>/gurobi.lic`,
`~/gurobi.lic`, and `/opt/gurobi/gurobi.lic`. With the commands below,
`<project>` means `Code/core/`. An existing license in another checkout can stay
there; point `--gurobi-license` at it.

## Quick example

The supplied `Code/examples/prepared/0213.txt` is a **15-vertex prepared example**
from the original regression tests. The full set of 4,091 raw inputs is
available separately in [`Prismatoid data/`](Prismatoid%20data/).

Run a small license-free search from the repository root:

```bash
python Code/run_prismatoid_batch.py run \
  --data Code/examples/prepared \
  --project Code/core \
  --entrypoint Code/core/src/nonrealizability_certificate.py \
  --output runs/example \
  --prepare-mode prepared \
  --n-factors 2 \
  --max-degree 3 \
  --search-variant all-variable-products-simplified \
  --flag-attempts 2 \
  --random-seed 0 \
  --lp-solver scipy-highs \
  --timeout 180
```

In the validated environment this produces `certificate_exact` for `0213`.
Independently check the saved proof:

```bash
python Code/core/src/modules/verify_certificate.py runs/example/exact_proofs \
  --report runs/example/independent_verification.json
```

Expected: `0213: VERIFIED EXACT` and `Verified 1/1`. The checker uses Python's
standard library and does not need Sage, an LP solver, or a Gurobi license.

## Running your prismatoid dataset

This is the reorganized equivalent of the original 20-vertex command. Run it
from the repository root using the included data; replace the license path
with your own. New outputs go to `runs/n20/` to preserve the archived results:

```bash
PRISMATOID_PYTHON=python bash Code/run_prismatoid_batch.sh run \
  --data "$PWD/Prismatoid data" \
  --project "$PWD/Code/core" \
  --entrypoint "$PWD/Code/core/src/nonrealizability_certificate.py" \
  --output "$PWD/runs/n20" \
  --prepare-mode external \
  --vertex-count 20 \
  --n-factors 2 \
  --max-degree 3 \
  --search-variant all-variable-products-simplified \
  --flag-attempts 10000 \
  --random-seed 0 \
  --lp-solver gurobipy \
  --gurobi-license "/absolute/path/to/gurobi.lic" \
  --timeout 36000
```

`python` above is the activated environment's interpreter. Without a virtual
environment, use `PRISMATOID_PYTHON=python3` if that is your configured Python.
Without `PRISMATOID_PYTHON`, the shell launcher prefers Sage when available and
otherwise uses `python3`. The Python launcher bypasses this choice; replace
`PRISMATOID_PYTHON=python bash Code/run_prismatoid_batch.sh` with
`python Code/run_prismatoid_batch.py` to select ordinary Python directly.

For a license-free run, use `--lp-solver scipy-highs` and omit the license option.
Use `--limit 1` and a smaller flag/time budget for an initial check. The example
folder has no 20-vertex candidate, so applying `--vertex-count 20` to it selects
zero candidates. Always inspect `CANDIDATE_SELECTION.tsv`.

### Input format

Use a directory of candidate files. The original raw box format starts with
`dimension number_of_lateral_facets`, followed by one lateral facet per line.
The two omitted bases are recovered using the original label split: lower base
labels below 14 and upper base labels at least 14 (original ambient ranges
0–13 and 14–27). This is a dataset-specific convention. The runner restores the
bases, relabels vertices consecutively starting at zero, and records the mapping
in `prepared/*.meta.json`. Raw box preparation is built in, including when
`--prepare-mode external` is used.

For other data, provide complete prepared facets using `--prepare-mode prepared`:
one facet per line, with space-separated, consecutive zero-based vertex labels,
and both bases first for the independent prismatoid verifier. A Python-style
list of facet lists is also accepted. Do not add a raw-box header to a prepared
file. See `Code/examples/prepared/0213.txt` for a complete working input.

Numbered root files such as `0001` are preferred for the raw box; when these
exist, auxiliary copies in subfolders are excluded. Otherwise the runner searches
recursively for readable facet files. Keep unrelated numeric text files out of
the input directory. Use unique candidate filenames/stems.

```bash
python Code/run_prismatoid_batch.py validate-data --data Code/examples/prepared
python Code/run_prismatoid_batch.py run --help
```

`validate-data` checks discovered facet inputs; its candidate count must also be
checked because unrecognized files are not necessarily reported as invalid.
It does not prove that an arbitrary facet list describes a valid polytope sphere.

### Important options

| Option | Meaning |
| --- | --- |
| `--dimension` | Polytope dimension; default 5. |
| `--vertex-count N` | Select exactly N vertices; repeat for a union of counts. Filtering precedes slicing. |
| `--start`, `--stop`, `--limit` | Slice the naturally sorted, filtered candidates; start is zero-based and stop is exclusive. |
| `--n-factors` | Maximum factors per generator product; default 2. |
| `--max-degree` | Generator degree bound; default 2. With the extended variant, applied after positive-monomial/content simplification. It is not a total product degree bound. |
| `--search-variant` | `legacy` (default) or `all-variable-products-simplified`, which includes positive reduced variables and the constant generator before forming products. |
| `--flag-attempts` | Maximum attempts per candidate; default 20. Stops early after an exact certificate. |
| `--random-seed` | Reproducible flag sampling; default 0. Solver/library versions can still affect numerical results. |
| `--timeout` | Seconds **per solver invocation**, not per candidate or entire batch. |
| `--lp-solver` | `gurobipy`, `scipy-highs`, or `auto` (Gurobi with HiGHS fallback). |
| `--template-first` | Opt into template-based support restrictions before unrestricted searches; disabled by default. |
| `--keep-sandboxes` | Retain per-attempt working copies for debugging. |

With 10,000 flags and a 36,000-second timeout, a candidate may take far longer
than ten hours. Template-first searches may add more invocations. Flags must
pass the patched rank checks and include every nonsimplicial facet; the attempt
budget is not a promise that that many suitable flags exist.

Within each flag, generator stages use term caps `4,8,0` (0 means unrestricted)
and a product-count cap of 200,000. These can be set through
`PRISMATOID_GENERATOR_TERM_CAPS` and `PRISMATOID_MAX_PRODUCTS`. Oversized stages
can be skipped; unsuccessful bounded searches are inconclusive.

### Resume

Rerun the same command and output directory to resume. Completed unchanged
candidates, including `no_certificate`, are skipped; unfinished, error, and
timeout cases are retried. `--no-resume` forces reprocessing.

Use a **new output directory** when changing search settings, inputs, code, or
dependencies. `SEARCH_CONFIG.json` rejects changes to dimension, degree, factor
count, seed, flag budget, preparation mode, variant, and vertex filters, but it
does not lock every option (for example, environment caps and solver versions).
Do not run concurrent jobs against the same output directory.

## Included data and archived results

- **[`Prismatoid data/`](Prismatoid%20data/)** contains the 4,091 numbered raw
  prismatoid inputs (`0001` through `4091`). The raw files describe lateral facets;
  the runner restores the two bases as explained under Input format. The
  `frightful_four/` subfolder contains auxiliary copies and is not counted again
  when the numbered root files are present.
- **[`Results/`](Results/)** contains the outputs supplied from the original
  code runs on this collection, grouped by vertex count: `n14/` contains results
  for 14-vertex inputs, through `n28/` for 28-vertex inputs. Start with each
  folder's `SUMMARY.txt` and `summary.tsv`; use `certificates/` for individual
  reports and `exact_proofs/` for saved proof bundles. `SEARCH_CONFIG.json` and
  `RUN_INFO.txt` record that run's settings. These are archived runs, not outputs
  regenerated during the repository reorganization; recorded absolute paths may
  refer to the original machine; project release labels in archived metadata
  and path strings have been normalized to descriptive names. A result file is
  not automatically a successful
  certificate: use the status meanings below.

For example, check the archived 14-vertex proof bundles without rerunning the LPs:

```bash
mkdir -p runs
python Code/core/src/modules/verify_certificate.py Results/n14/exact_proofs \
  --report runs/n14-independent-verification.json
```

Use `runs/` for new searches and verification reports. Keep the archived
`Results/` folders intact when comparing experiments.

## Results and interpretation

All outputs are under the directory supplied to `--output`; input files are
left unchanged. Start with `SUMMARY.txt`, then inspect `summary.tsv` and the
individual candidate reports.

| Location | Contents |
| --- | --- |
| `SUMMARY.txt`, `summary.tsv` | Counts and per-candidate status, exact flag, template ID, and elapsed time. |
| `certificates/<id>.txt`, `.json` | Human-readable/machine-readable reports, flags tried, selected attempt, diagnostics, and witness metadata. |
| `exact_proofs/<id>.json` | Full geometric certificate bundle for successful patched-core searches. |
| `prepared/` | Prepared facets and, for raw box files, original-to-prepared label mappings. |
| `model_captures/` | LP coefficients and numerical solutions used for exact reconstruction. |
| `legacy_artifacts/` | Per-attempt core artifacts, matrices, and diagnostics. The historical name is retained. |
| `templates/final_templates.json`, `.txt`, `templates/individual/` | Discovered support templates and covered candidates. |
| `batch_state.sqlite3` | Resume state. |
| `SEARCH_CONFIG.json`, `RUN_INFO.txt` | Search settings and runtime details. |
| `CANDIDATE_SELECTION.tsv`, `VERTEX_COUNT_DISTRIBUTION.tsv`, `SELECTION_SUMMARY.txt` | Selected inputs, vertex distribution, and filtering details. |
| `CURRENT_CANDIDATE.txt`, `work/` | Progress marker and temporary work; the marker is removed on normal completion. |
| `LAUNCHER_INFO.txt`, `FATAL_ERROR.txt` | Shell-launcher information and startup errors when produced. |

Status meanings:

- **`certificate_exact`**: the captured LP witness passed exact rational
  checking. For the documented prismatoid workflow, also check the full proof
  with `verify_certificate.py` and require `verified_exact`.
- **`certificate_numerical_only`**: numerical evidence did not pass the exact
  checks; do not treat it as a proof.
- **`no_certificate`**: nothing was found within the attempted search. This
  does **not** prove realizability.
- **`error` / `timeout`**: execution failed or a time budget was exceeded;
  inspect the report and retry as appropriate.

Mathematically, a certificate is a nonempty positive rational combination of
products of polynomials that would be strictly positive in a realization, yet
whose sum is identically zero. This contradiction rules out a realization when
the geometric positivity assumptions have been verified. Proof bundles contain
facets, rank and facet-basis witnesses, scaling and orientation information,
generator provenance, and rational weights. The independent checker recomputes
determinants and identities with different polynomial arithmetic.

The standalone checker is specialized to the five-dimensional prismatoid class
described above. `exact_identity_verified` on another input type is narrower
than `verified_exact`: it does not establish that the independent geometric
checker covered that input. Template IDs describe reusable LP support patterns;
each covered candidate still needs its own exact witness. A batch exit code of
zero alone does not mean that every candidate has a certificate.

## Repository layout

```text
README.md                   Setup, usage, data, and results guide
LICENSE                     MIT software license
Prismatoid data/             4,091 numbered raw prismatoid inputs
Results/n14/ ... n28/        Archived original outputs grouped by vertex count
Code/
  core/src/                 Mathematical solver and exact verification modules
  prismatoid_batch/          Batch runner, LP adapters, reports, and templates
  preprocessing/            Historical aggregate-list preprocessing helpers
  examples/prepared/        Small complete test input
  tests/                    Regression and integration tests
  docs/                     Cleanup audit, source map, and validation record
  run_prismatoid_batch.py    Python launcher
  run_prismatoid_batch.sh    Bash/Sage-aware launcher
  requirements*.txt         Runtime, Gurobi, and test dependencies
  pytest.ini                Test configuration
runs/                       New local outputs (created when running; Git-ignored)
```

Keep `--project Code/core` so per-attempt sandboxes copy only the solver. Batch adapter
code is added automatically. Use the batch launcher for the documented workflow;
the core file retains older direct-call options whose defaults do not match
this workflow. The historical `doctor` subcommand still expects Sage and can
report failure in a working Python-only installation; use the quick example
and independent verifier as the installation check.

## Tests and maintenance

```bash
python -m pip install -r Code/requirements-dev.txt
python -m pytest -q Code/tests
```

Tests include a real HiGHS search, independent proof verification, deliberately
corrupted certificates, flag checks, template handling, and resume. Sage-specific
tests skip when Sage is unavailable; POSIX launcher tests skip on native Windows.
See [the cleanup audit](Code/docs/CLEANUP.md) for removed files and retained dependencies.

## License and attribution

The software is distributed under the [MIT License](LICENSE), copyright
2026 Yiwen Chen. A Gurobi license is separate and is not included. Any upstream
dataset attribution or redistribution terms should accompany the data; the
software license does not by itself establish the licensing of third-party data.
