# Agentic Blanche Dissections

This repository searches for perfect Mondrian dissections using rooted
polyhedral graphs and the normalized Kirchhoff algebra.

The codebase was designed around the workflow that emerged from experiments
in [`blanche-dissections`](https://github.com/christianwolird/blanche-dissections):

1. stream unrooted polyhedral graphs from plantri;
2. quotient by planar duality and root only at edge-orbit representatives;
3. construct both the sparse edge-current presentation and an adaptive
   fundamental-cycle presentation;
4. use a finite-field msolve pilot to choose the faster presentation;
5. probe several primes before attempting a characteristic-zero RUR;
6. recover rational currents exactly and filter rectangle congruences.

The safe default treats the modular stage as evidence, not as a proof. It
continues to characteristic zero unless heuristic pruning is explicitly
enabled or a good-reduction certificate is supplied.

## Mathematical normalization

For a rooted polyhedral graph \(G\) with \(n+1\) edges, delete the root edge
and assign a signed current \(x_e\) to each of the remaining \(n\) edges. The
corresponding voltage is \(1/x_e\), so every modeled rectangle has area one.

The source current is normalized to \(n\). Hence the geometry is an
\(n\times1\) rectangle tiled by \(n\) unit-area rectangles. Rational side
lengths scale to integer side lengths, and an affine stretch gives the
equivalent square-dissection formulation.

The saturated Kirchhoff algebra imposes:

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
pip install -e '.[dev]'
```

## Usage

Count or inspect rooted tasks without solving:

```bash
agentic-blanche enumerate --edges 18 --limit 10
```

Run the safe workflow. Modular results are recorded, but every task still
receives an exact solve:

```bash
agentic-blanche search \
  --edges 18 \
  --sieve-mode report \
  --prime-count 9 \
  --exact-threads 8
```

Use the experimentally effective, but not presently proof-producing,
modular pruning mode:

```bash
agentic-blanche search \
  --edges 18 \
  --sieve-mode heuristic-prune \
  --prime-count 9
```

Results are appended to `results/E18.jsonl`. Repeating the command resumes
from the existing task identifiers.

Useful options:

```text
--presentation auto|edge|cycle
--no-pilot
--include-duals
--plantri /path/to/plantri
--msolve /path/to/msolve
--timeout SECONDS
--limit TASKS
```

## Exactness boundary

Suppose a finite-field RUR is squarefree, has the expected degree, and its
univariate polynomial has no linear factor. This is strong evidence against
a rational point, but it is not automatically a proof: a rational point may
have bad reduction or escape to infinity.

The library represents this distinction explicitly:

- `report`: collect modular evidence and still solve exactly;
- `heuristic-prune`: permit an uncertified modular rejection;
- `certified-prune`: prune only when a `GoodReductionOracle` confirms both
  the expected degree and that the prime is good.

The default `NoGoodReductionCertificate` never certifies a prime. The main
theoretical extension point is therefore a theorem-backed implementation of
`GoodReductionOracle`.

## Measured performance

On a stratified sample of 40 rooted systems with 9, 12, or 15 edges:

- the adaptive cycle presentation won 29 cases;
- median exact speedup was 1.18×;
- aggregate exact speedup was 1.65×;
- at 15 edges, aggregate exact speedup was 1.69×.

For five representative 18-edge systems, the adaptive exact times were:

| \(V,F\) | Edge current | Adaptive cycle | Speedup |
|---|---:|---:|---:|
| \(8,12\) | 17.30 s | 3.58 s | 4.84× |
| \(9,11\) | 25.65 s | 9.27 s | 2.77× |
| \(10,10\) | 21.85 s | 19.51 s | 1.12× |
| \(11,9\) | 21.46 s | 19.50 s | 1.10× |
| \(12,8\) | 2.10 s | 0.89 s | 2.35× |

In the 40-system modular experiment, nine primes separated all 37 systems
without rational points from the three systems with rational points. Those
three rational points all failed the noncongruence test. Modular probing plus
exact solution of survivors was 5.27× faster than exact edge-current solving
of every system. This is benchmark evidence, not a good-reduction theorem.

## Development

```bash
ruff format .
ruff check .
pytest
```

See [`docs/model.md`](docs/model.md) for the algebra and
[`docs/architecture.md`](docs/architecture.md) for the software boundaries.

