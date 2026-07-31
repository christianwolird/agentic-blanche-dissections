# Architecture

The package is intentionally divided at mathematical boundaries.

| Module | Responsibility |
|---|---|
| `graph.py` | Rotation systems, faces, rooted planar duality, edge correspondence |
| `symmetry.py` | Canonical rooted certificates, automorphisms, edge orbits |
| `plantri.py` | Streaming graph generation and dual quotienting |
| `polynomial.py` | Sparse integer polynomial arithmetic and msolve serialization |
| `presentations.py` | Bilinear, edge-current, and primal/dual cycle presentations |
| `msolve.py` | Timed subprocesses and exact/finite RUR recovery |
| `workflow.py` | Modular Mondrian sieve, exact solve, independent verification |
| `storage.py` | SQLite/WAL task leasing and result persistence |
| `parallel.py` | Process-level worker scheduling |
| `manifest.py` | Reproducibility metadata |
| `cli.py` | Search and enumeration interface |

## Design decisions

### Streams rather than graph lists

Plantri output is consumed incrementally. The graph search can therefore run
at sizes where storing every graph would be wasteful.

### Linear-time dual filtering

Only buckets with \(V\le F\) are generated. At \(V=F\), nauty certificates of
accepted duals are stored in a hash set. This replaces pairwise dual
isomorphism testing.

### Presentations are data

A `KirchhoffPresentation` contains:

- its polynomial system;
- model-side affine current forms;
- a recovery map to the original rooted graph;
- presentation kind and tree statistics.

The workflow can benchmark presentations without knowing how they were
constructed.

### Modular safety is explicit

`heuristic-prune` and `certified-prune` are separate modes. A certified
rejection requires a `GoodReductionOracle`; the default oracle certifies
nothing.

### Task state is transactional

SQLite runs in WAL mode. Workers atomically lease pending tasks, and expired
leases return to the queue after an interrupted process. Rooted graph IDs are
nauty certificates of vertex-colored graphs, so resume keys are independent
of plantri's temporary labels. Results and run manifests are committed in the
same persistent database.

## Intended extensions

1. A theorem-backed degree and good-prime oracle for the Kirchhoff algebra.
2. Adaptive resource scheduling between single-threaded worker processes and
   threaded exact solves for hard survivors.
3. Better spanning-tree optimization using term-count prediction rather than
   cycle support alone.
4. Optional exact verification in a second computer-algebra system.
