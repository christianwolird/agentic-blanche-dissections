# Architecture

The package is intentionally divided at mathematical boundaries.

| Module | Responsibility |
|---|---|
| `graph.py` | Rotation systems, faces, rooted planar duality, edge correspondence |
| `symmetry.py` | Nauty certificates, automorphisms, edge-orbit representatives |
| `plantri.py` | Streaming graph generation and dual quotienting |
| `polynomial.py` | Sparse integer polynomial arithmetic and msolve serialization |
| `presentations.py` | Edge-current and primal/dual cycle presentations |
| `msolve.py` | Subprocess execution and exact/finite RUR parsing |
| `workflow.py` | Presentation pilot, modular sieve, exact solve, congruence filter |
| `cli.py` | Resumable JSONL search interface |

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

### Checkpoints are append-only

Every completed rooted task is one JSON object. A restart reads only task
identifiers and skips completed work. Partial final lines are never written
because each result is serialized before opening the append.

## Intended extensions

1. A theorem-backed degree and good-prime oracle for the Kirchhoff algebra.
2. Process-level parallel scheduling: one msolve process per core for small
   systems, threaded msolve for hard survivors.
3. Better spanning-tree optimization using term-count prediction rather than
   cycle support alone.
4. Canonical rooted certificates independent of plantri vertex labels.
5. Optional exact verification in a second computer-algebra system.

