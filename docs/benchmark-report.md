# Pre-21-edge workflow benchmark

Date: 2026-07-30

## Purpose

This benchmark tests the engineering choices needed before searching every
rooted polyhedral graph with at most 21 edges. It is deliberately not a full
21-edge search. It compares polynomial presentations, exercises the staged
modular Mondrian filter, and measures the actual SQLite/process runner.

## Environment

- 9 Linux vCPUs, AMD EPYC 9V74
- Python 3.12
- plantri 5.5
- msolve 0.10.1, AMD x86-64 AVX512 build
- one msolve thread per worker

The benchmark is reproducible with:

```bash
python benchmarks/benchmark_pre21.py \
  --plantri /path/to/plantri \
  --msolve /path/to/msolve \
  --modular-timeout 1 \
  --prime-count 9 \
  --parallel-workers 4 \
  --output results/benchmark-pre21.json
```

## Sampling

The sample contains 50 rooted systems. Within each edge count, the script
takes an equal deterministic prefix from each generated vertex-count stratum:

| Graph edges | Vertex strata | Roots per stratum | Total |
|---:|---|---:|---:|
| 12 | 6, 7 | 5 | 10 |
| 15 | 7, 8 | 5 | 10 |
| 18 | 8, 9, 10 | 5 | 15 |
| 21 | 9, 10, 11 | 5 | 15 |

The primal/dual quotient is enabled. Each graph edge count \(E\) corresponds
to \(E-1\) rectangles because the root edge is the source.

## Presentation benchmark

Each system was solved over \(\mathbf F_{65521}\) with a one-second wall-clock
limit. Times are aggregate wall times. The adaptive-cycle column combines
the primal or dual presentation chosen from the graph dimensions.

| Edges | Edge current | Adaptive cycle | Bilinear |
|---:|---:|---:|---:|
| 12 | 0.134 s, 10/10 | 0.097 s, 10/10 | 0.103 s, 10/10 |
| 15 | 0.347 s, 10/10 | 0.247 s, 10/10 | 0.211 s, 10/10 |
| 18 | 6.711 s, 15/15 | 3.859 s, 15/15 | 1.717 s, 15/15 |
| 21 | 15.067 s, 0/15 | 13.545 s, 5/15 | 6.837 s, 15/15 |

At 21 edges, the bilinear presentation was the only presentation to finish
every sampled system. Its mean system had 28 variables and 89.4 terms. The
adaptive system had only 9 variables on average, but 6,941 terms after
clearing denominators; this is the decisive difference.

Adaptive cycle is slightly faster at 12 edges, where every method is already
cheap. Bilinear becomes the clear default by 15 edges and avoids the sharp
failure at 21 edges.

## Exact comparison

One representative 18-edge root was solved over \(\mathbf Q\):

| Presentation | Time | Degree | Rational points |
|---|---:|---:|---:|
| Edge current | 18.353 s | 32 | 0 |
| Adaptive cycle | 5.224 s | 32 | 0 |
| Bilinear | 0.061 s | 32 | 0 |

The matching degree is a useful regression check that the three
presentations describe the same zero-dimensional torus fiber in this case.
Bilinear was about 300× faster than edge current and 85× faster than adaptive
cycle on this representative.

## Staged modular Mondrian sieve

For each bilinear system, the sieve tried up to nine descending primes. At
each prime it:

1. computes the finite-field RUR;
2. obtains the split linear part with \(\gcd(f,t^p-t)\);
3. recovers and verifies every finite-field point;
4. recovers the original graph currents and verifies KCL and KVL;
5. applies both parallel and quarter-turn congruence tests modulo \(p\).

Results:

- 50/50 sampled roots were heuristically shelved;
- 15/15 sampled 21-edge roots were shelved;
- 111 total prime probes were needed;
- no modular probe reached the one-second timeout;
- cumulative msolve time was 6.062 seconds.

“Shelved” is intentional terminology. Without a good-reduction theorem this
is strong search evidence, not a proof that the rational variety has no
Mondrian point.

## SQLite and process parallelism

The 15 sampled 21-edge tasks were run through the same WAL database and
leasing code used by the CLI:

| Workers | Wall time | Final state | Failures |
|---:|---:|---|---:|
| 1 | 12.615 s | 15 shelved | 0 |
| 4 | 4.022 s | 15 shelved | 0 |

The measured speedup was 3.14×. Work distribution was 5, 5, 2, and 3 tasks;
the imbalance comes from variable per-root solve times, not queue contention.

## Recommendation

For the first complete pass through 21 edges:

1. use bilinear presentation directly, without presentation pilots;
2. use process-level parallelism with one single-threaded msolve per physical
   core, leaving one core free if the machine is also in use;
3. use nine modular primes with a one-second per-prime cap;
4. keep heuristic rejections as a persistent `shelved` queue;
5. send modular survivors and timeouts to a separate exact queue with a
   larger timeout;
6. retain manifests and the SQLite database so every decision can be audited
   and rerun.

Example:

```bash
agentic-blanche search \
  --edges 21 \
  --presentation bilinear \
  --sieve-mode heuristic-prune \
  --prime-count 9 \
  --modular-timeout 1 \
  --workers 8
```

The shelved tasks can later be promoted explicitly with `--requeue shelved`
and `--sieve-mode off`; they are not discarded.

## Limitations

- The sample is stratified but small; it is not a random or exhaustive sample.
- A one-second cap measures throughput policy as well as raw solver speed.
- The exact comparison uses one representative root.
- Modular shelving remains heuristic until the required good-reduction
  theorem is supplied.
- The benchmark does not estimate the total number of rooted tasks or the
  total wall time of the complete 21-edge enumeration.
