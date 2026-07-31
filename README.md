# Agentic Blanche Dissections

This repository searches for perfect Mondrian dissections using rooted
polyhedral graphs and the normalized Kirchhoff algebra.

The codebase was designed around the workflow that emerged from experiments
in [`blanche-dissections`](https://github.com/christianwolird/blanche-dissections):

1. stream unrooted polyhedral graphs from plantri;
2. quotient by planar duality and root only at edge-orbit representatives;
3. solve the sparse current-potential bilinear presentation by default;
4. recover finite-field points and apply the Mondrian noncongruence test
   before escalating to another prime;
5. coordinate process workers through a resumable SQLite/WAL task database;
6. solve survivors over the rationals and verify the original KCL and KVL
   equations independently of the solver presentation.

The library's conservative `report` mode treats the modular stage as
evidence, not as a proof. The human-facing search command defaults to the
experimentally effective `heuristic-prune` mode for large searches and labels
that limitation in its final report.

## Mathematical normalization

For a rooted polyhedral graph \(G\) with \(n+1\) edges, delete the root edge
and assign a signed current \(x_e\) to each of the remaining \(n\) edges. The
corresponding voltage is \(1/x_e\), so every modeled rectangle has area one.

The source current is normalized to \(n\). Hence the geometry is an
\(n\times1\) rectangle tiled by \(n\) unit-area rectangles. Rational side
lengths scale to integer side lengths, and an affine stretch gives the
equivalent square-dissection formulation.

The Kirchhoff algebra imposes:

- KCL at vertices;
- KVL around non-root faces;
- source current \(n\);
- \(x_e\ne0\) for every rectangle.

Two final rectangles are congruent exactly when either

\[
x_e^2=x_f^2
\qquad\text{or}\qquad
x_e^2x_f^2=n^2.
\]

The computational system solves the smaller Kirchhoff algebra and applies
these congruence tests to its rational points. It does not build the much
larger dummy-variable Mondrian ideal.

## Presentations

### Current-potential bilinear presentation

This is the default. Fix source potential one and sink potential zero. For
each non-root edge \(e=(u,v)\), introduce its current \(x_e\) and impose

\[
x_e(h_u-h_v)=1.
\]

Together with KCL at the \(V-2\) internal vertices this gives a square system
of \(n+V-2\) equations. Every equation is linear or bilinear, every
unit-area equation has three terms, and nonzero currents are automatic. The
larger variable count is decisively outweighed by the absence of cleared
products in the tested range.

### Edge-current presentation

This presentation retains the \(n\) edge currents. KCL is linear and every
face equation remains local. Its saturation equation is a single monomial,
so it can outperform lower-dimensional presentations when \(V\) and \(F\)
are balanced.

### Adaptive fundamental-cycle presentation

After choosing a particular normalized flow and a fundamental-cycle matrix
\(C\), write

\[
x=x^{(0)}+Cz.
\]

This eliminates KCL and leaves \(F-2=E-V\) free current coordinates. Applying
the same construction to \(G^*\) leaves \(V-2\) free voltage coordinates.
The implementation chooses the smaller side and tries BFS/DFS spanning trees
from every vertex, minimizing cycle-support statistics.

All polynomial expansion uses an internal sparse integer representation.
This is important: generic symbolic expansion made construction slower than
the solve in the original prototype.

## Requirements

- Python 3.11 or later
- [plantri](https://users.cecs.anu.edu.au/~bdm/plantri/)
- [msolve](https://msolve.lip6.fr/)

The two external executables must be on `PATH`, or their paths can be given
on the command line.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Contributors can install the test and lint tools with
`pip install -e '.[dev]'`.

## Usage

The normal command takes the first and last graph-edge counts. Both endpoints
are included, so this searches 7, 8, 9, 10, and 11 edges:

```bash
agentic-blanche search 7 11
```

The command-line defaults are chosen for the heuristic search workflow:

- bilinear current-potential presentation;
- nine finite-field probes, with one second allowed per probe;
- heuristic modular pruning followed by exact solving of survivors;
- 30 seconds allowed per exact solve;
- up to eight worker processes, bounded by the machine's CPU count;
- a progress line every 30 seconds during long edge layers.

Each edge count has its own database and reproducibility manifest, for example
`results/E11.sqlite` and `results/E11.manifest.json`. Repeating the same
command resumes from those databases. At the end, the CLI checkpoints the WAL,
runs a SQLite integrity check, and prints a table of shelved tasks, exact
solves, timeouts, failures, rational points, and Mondrian candidates.

To search one edge count, repeat it:

```bash
agentic-blanche search 17 17
```

Use the conservative non-pruning workflow when heuristic rejection is not
acceptable. Modular probes are still recorded, but every task proceeds to an
exact solve:

```bash
agentic-blanche search 7 11 --sieve-mode report
```

If the executables are not on `PATH`, give their locations once on the same
command:

```bash
agentic-blanche search 7 11 \
  --plantri /path/to/plantri \
  --msolve /path/to/msolve
```

Count rooted graph/orbit tasks without solving:

```bash
agentic-blanche enumerate 18
agentic-blanche enumerate 18 --limit 10 --verbose
```

The built-in help shows defaults and examples:

```bash
agentic-blanche --help
agentic-blanche search --help
```

Useful options:

```text
--results-dir DIRECTORY
--presentation bilinear|auto|edge|cycle
--sieve-mode heuristic-prune|report|off|certified-prune
--no-pilot
--include-duals
--plantri /path/to/plantri
--msolve /path/to/msolve
--workers PROCESSES
--modular-timeout SECONDS
--exact-timeout SECONDS
--progress-interval SECONDS
--requeue completed|shelved|timed-out|failed
--limit TASKS
```

For example, revisit the shelved queue without modular pruning:

```bash
agentic-blanche search 21 21 \
  --sieve-mode off \
  --requeue shelved \
  --exact-timeout 600 \
  --workers 4
```

## Exactness boundary

For each finite-field RUR, the implementation computes
\(\gcd(f(t),t^p-t)\), recovers the associated coordinates, verifies the
defining equations, recovers the original currents, and applies the
noncongruence tests in \(\mathbf F_p\). Finding no modular Mondrian point is
strong evidence against a rational point, but is not automatically a proof:
a rational point may have bad reduction or escape to infinity.

The library represents this distinction explicitly:

- `report`: collect modular evidence and still solve exactly;
- `heuristic-prune`: permit an uncertified modular rejection;
- `certified-prune`: prune only when a `GoodReductionOracle` confirms both
  the expected degree and that the prime is good.

The default `NoGoodReductionCertificate` never certifies a prime. The main
theoretical extension point is therefore a theorem-backed implementation of
`GoodReductionOracle`.

## Measured performance

The preflight benchmark uses 50 deterministic roots, stratified by vertex
count at 12, 15, 18, and 21 graph edges. Each modular solve gets one second.
Times below are aggregate wall times; success counts are in parentheses.

| Edges | Edge current | Adaptive cycle | Bilinear |
|---:|---:|---:|---:|
| 12 | 0.134 s (10/10) | 0.097 s (10/10) | 0.103 s (10/10) |
| 15 | 0.347 s (10/10) | 0.247 s (10/10) | 0.211 s (10/10) |
| 18 | 6.711 s (15/15) | 3.859 s (15/15) | 1.717 s (15/15) |
| 21 | 15.067 s (0/15) | 13.545 s (5/15) | 6.837 s (15/15) |

On one representative 18-edge exact solve, bilinear took 0.061 s, versus
5.224 s for adaptive cycle and 18.353 s for edge current. The staged
nine-prime heuristic shelved all 50 sampled roots in 111 probes without a
modular timeout. On the 15 sampled 21-edge tasks, the SQLite runner took
12.615 s with one process and 4.022 s with four, a 3.14× speedup.

These are search-engineering measurements, not a good-reduction theorem.
See [`docs/benchmark-report.md`](docs/benchmark-report.md) for the method,
raw-data location, and limitations.

## Development

```bash
ruff format .
ruff check .
pytest
```

See [`docs/model.md`](docs/model.md) for the algebra and
[`docs/architecture.md`](docs/architecture.md) for the software boundaries.
