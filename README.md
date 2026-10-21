# Prismatoid non-realizability certificates

This repository contains the 4,091 prismatoid inputs, their certificates, and
the code for reproducing searches. The prismatoid data comes from:

Francisco Criado and Francisco Santos, **Topological Prismatoids and Small
Simplicial Spheres of Large Diameter**, *Experimental Mathematics* **31**(2)
(2022), 461–473.
[DOI: 10.1080/10586458.2019.1641766](https://doi.org/10.1080/10586458.2019.1641766).

The certificate searches use the notation and method of:

João Gouveia, Antonio Macchia, and Amy Wiebe, **General non-realizability
certificates for spheres with linear programming**, *Journal of Symbolic
Computation* **114** (2023), 172–192.
[DOI: 10.1016/j.jsc.2022.04.013](https://doi.org/10.1016/j.jsc.2022.04.013).

## Where to start

- **[Prismatoid data](Prismatoid%20data/)**: the 4,091 raw inputs named `0001`
  through `4091`. 
- **[Results](Results/)**: archived certificates grouped by vertex count,
  `n14/` through `n28/`. See [the overall summary](Results/SUMMARY.txt) and each
  group's `SUMMARY.txt`. All 4,091 saved witnesses passed independent exact
  verification, including comparison with the corresponding raw input facets.
- **[Code](Code/)**: search code, the independent checker, examples, and tests.

For a concrete example, open [certificate 1039](Results/n14/certificates/1039.txt)
alongside its [reconstruction data](Results/n14/intermediate/1039/geometry.txt).
The [certificate guide](Code/docs/CERTIFICATES.md) explains every field and gives
a hand-verification procedure. No solver software is needed to read these files.

## Reading a certificate

Each candidate has one short certificate and four supporting text files:

| File within `Results/nN/` | What it contains |
| --- | --- |
| `certificates/ID.txt` | Successful ordered facet selection, seed, search bounds, products `P_k`, and exact positive weights `c_k`. |
| `intermediate/ID/geometry.txt` | All prepared facets; the reduced slack matrix `R`; variable labels; ordered facet bases; rank pivots; original vertex-label mapping. |
| `intermediate/ID/generators.txt` | Ordinary expanded polynomials `g_k`, together with the determinant, sign, and positive divisor producing each one. |
| `intermediate/ID/orientations.txt` | Sign anchors and propagation identities for the reconstructed columns. |
| `intermediate/ID/coefficient-check.txt` | The coefficient of every occurring monomial in every displayed product, followed by its weighted sum (zero). |

All vertex and facet indices start at **zero**. The symbol `x_i_j` means the
positive variable in row `i`, full prepared facet column `j`, of the reduced
matrix. The second subscript is **not** its position among the six selected
columns. Zeros represent incidences; ones are scaling normalizations.

In `geometry.txt`, the section **`[Reduced slack matrix R]`** is the matrix
used in the determinant formulas. **`[Ordered facet bases B_j]`** lists its
ordered basis-row indices: `B3 = 0 1 4 5 8` means B_3=(0,1,4,5,8). Thus
`D(3,3)` uses rows `v0, v1, v4, v5, v8, v3` of R, in that order, and all
six displayed columns.

The certificate uses local labels `g1, g2, ...` for its generators and
`P1, P2, ...` for their products. It displays

$$
\sum_k c_k P_k(x)=0,\qquad c_k>0,\qquad\sum_k c_k=1.
$$

These `c_k` correspond to the supported coefficients `c_β` in equation (3) of
the paper. To check the identity, multiply each column of the coefficient table
by its displayed rational weight and add. To check why its factors are positive,
use the matrix, determinant sources, divisors, and orientation checks in the
supporting files.

## Verify saved certificates with Python

The independent verifier needs **Python 3.11 or newer and only its standard
library**. It reads the same text files a person reads, reconstructs the
determinants, and checks ranks, normalization, signs, and exact rational weights.
Run these commands from the repository root:

```bash
python Code/human_certificate.py Results/n14/certificates/1039.txt
python Code/human_certificate.py Results/n14
python Code/human_certificate.py Results --data "Prismatoid data"
```

Success is reported as `VERIFIED EXACT`. A malformed or altered proof produces
a nonzero exit code. The checker also confirms that the printed coefficient
table agrees with the generator polynomials; it does not merely trust the
printed zero column. It is specialized to the five-dimensional prismatoids with
two nonsimplicial bases first. See [validation details](Code/docs/VALIDATION.md).
The optional `--data` argument also checks the facets and original vertex-label
mapping against the numbered raw input files.

## Install the search environment

For Linux/macOS/WSL, from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r Code/requirements.txt
```

The search needs NumPy, SciPy, and SymPy. SageMath is optional; ordinary Python
uses the exact sparse polynomial backend. On Windows, create the environment with
`python -m venv .venv` and use `.\.venv\Scripts\python.exe` for subsequent
commands. Multiline examples below use Bash syntax; use a single line in
PowerShell.

For Gurobi, additionally install `Code/requirements-gurobi.txt` and supply your
own license with `--gurobi-license`. No license credentials are included.
Alternatively use `--lp-solver scipy-highs`, which needs no license.

## Run a search

A short example:

```bash
python Code/run_prismatoid_batch.py run \
  --data Code/examples/prepared --output runs/example \
  --lp-solver scipy-highs --flag-attempts 2 --timeout 180
```

Search the 20-vertex prismatoids with Gurobi:

```bash
python Code/run_prismatoid_batch.py run \
  --data "Prismatoid data" --output runs/n20 \
  --vertex-count 20 --n-factors 2 --max-degree 3 \
  --search-variant all-variable-products-simplified \
  --flag-attempts 10000 --random-seed 0 \
  --lp-solver gurobipy --gurobi-license "/absolute/path/to/gurobi.lic" \
  --timeout 36000
```

The runner locates the core and entrypoint automatically and detects the raw
box format or complete prepared facets. The shell
launcher is an optional wrapper: use `PRISMATOID_PYTHON=python bash
Code/run_prismatoid_batch.sh run ...` with the same arguments.

To rerun the successful reduction of candidate 1039 directly:

```bash
python Code/run_prismatoid_batch.py run \
  --data "Prismatoid data" --candidate 1039 --output runs/1039 \
  --flag 0,1,19,65,73,90 --flag-attempts 1 --random-seed 0 \
  --n-factors 2 --max-degree 3 --lp-solver scipy-highs
```

An LP backend/version can find a different valid identity. To begin with the
archived generator term cap of 8, set `PRISMATOID_GENERATOR_TERM_CAPS=8,0` before
the command.

Useful options:

- `--candidate ID`: select one candidate (repeatable).
- `--vertex-count N`: select a vertex count (repeatable); `--limit N` limits
  the selected, naturally sorted inputs.
- `--flag-attempts`: default 20. Default selection first, then checked alternate
  facet sets; stop on exact success. An explicit `--flag` requires one attempt.
- `--timeout`: seconds **per flag invocation**, including construction and
  checking. It is not a total batch or candidate limit.
- `--n-factors`: maximum factors in a product (default 2).
- `--max-degree`: maximum normalized **generator** degree (default 3), not total
  product degree. The default extended variant includes reduced variables and 1.
- `--search-variant legacy`: keep determinant monomial factors instead of
  simplifying them; the documented runs use `all-variable-products-simplified`.

The default generator term caps are `4,8,0` (0 means all), with a 200,000-product
budget. Oversized stages may be skipped. See `run --help` for all supported
options. Large search budgets can take substantial time and memory.

## Search output and resume

Always write new experiments into `runs/`, preserving `Results/`. New successes
use the same five-file format as the archive. `RUN.txt` records search settings;
`SUMMARY.txt` lists the outcomes. A candidate with no successful certificate gets
one short file under `inconclusive/`. It is not a realizability certificate.
Errors/timeouts are reported as incomplete execution, and a successful batch
exit code alone does not mean every candidate has a certificate.

Repeating a command resumes verified successes after checking them against the
current input facets. Inconclusive cases are retried. Changed search settings
require a new output directory; use a new directory after changing code or
dependencies as well. `--no-resume` reprocesses existing candidates. Never run
two searches into the same output directory.

## Tests and license

```bash
python -m pip install -r Code/requirements-dev.txt
python -m pytest -q Code/tests
```

Software: [MIT License](LICENSE), copyright 2026 Yiwen Chen. The software license
is separate from Gurobi licensing and any upstream dataset terms.

## Contact

For questions, contact [yiwchen@student.ubc.ca](mailto:yiwchen@student.ubc.ca).
