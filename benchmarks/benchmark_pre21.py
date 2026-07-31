"""Deterministic preflight benchmark for a search through 21 edges."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter

from agentic_blanche.graph import RootedPlaneGraph
from agentic_blanche.msolve import MSolve, SolveTimeout
from agentic_blanche.parallel import run_parallel
from agentic_blanche.plantri import Plantri
from agentic_blanche.presentations import (
    KirchhoffPresentation,
    build_adaptive_cycle_presentation,
    build_bilinear_presentation,
    build_edge_current_presentation,
)
from agentic_blanche.storage import SQLiteTaskStore
from agentic_blanche.workflow import (
    PresentationChoice,
    SearchConfig,
    SearchWorkflow,
    SieveMode,
    descending_primes,
)

SAMPLE_SIZES = {12: 10, 15: 10, 18: 15, 21: 15}


def stratified_roots(
    plantri: Plantri,
    edges: int,
    count: int,
) -> tuple[RootedPlaneGraph, ...]:
    """Take equal deterministic prefixes from each generated V/F stratum."""
    buckets: dict[int, list[RootedPlaneGraph]] = defaultdict(list)
    vertex_strata = tuple(
        range(
            (edges + 8) // 3,
            (edges + 2) // 2 + 1,
        )
    )
    base, remainder = divmod(count, len(vertex_strata))
    quotas = {
        vertices: base + int(index < remainder)
        for index, vertices in enumerate(vertex_strata)
    }
    for rooted in plantri.rooted_graphs(edges, quotient_duality=True):
        vertices = rooted.graph.vertex_count
        if len(buckets[vertices]) < quotas.get(vertices, 0):
            buckets[vertices].append(rooted)
        if all(len(buckets[v]) >= quotas[v] for v in vertex_strata):
            break
    roots = tuple(rooted for vertices in vertex_strata for rooted in buckets[vertices])
    if len(roots) != count:
        raise RuntimeError(f"only found {len(roots)} of {count} roots at E={edges}")
    return roots


def presentations(rooted: RootedPlaneGraph) -> tuple[KirchhoffPresentation, ...]:
    return (
        build_edge_current_presentation(rooted),
        build_adaptive_cycle_presentation(rooted),
        build_bilinear_presentation(rooted),
    )


def modular_benchmark(
    solver: MSolve,
    roots: Iterable[RootedPlaneGraph],
    *,
    prime: int,
    timeout: float,
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for rooted in roots:
        for presentation in presentations(rooted):
            key = presentation.kind.value
            row = rows.setdefault(
                key,
                {
                    "tasks": 0,
                    "solved": 0,
                    "timed_out": 0,
                    "seconds": 0.0,
                    "variables": [],
                    "terms": [],
                },
            )
            row["tasks"] = int(row["tasks"]) + 1
            started = perf_counter()
            try:
                solver.finite(
                    presentation.system,
                    prime,
                    timeout=timeout,
                )
            except SolveTimeout:
                row["timed_out"] = int(row["timed_out"]) + 1
            else:
                row["solved"] = int(row["solved"]) + 1
            row["seconds"] = float(row["seconds"]) + (perf_counter() - started)
            row["variables"].append(len(presentation.system.variables))
            row["terms"].append(presentation.system.term_count)
    for row in rows.values():
        variables = row.pop("variables")
        terms = row.pop("terms")
        row["mean_variables"] = sum(variables) / len(variables)
        row["mean_terms"] = sum(terms) / len(terms)
        row["seconds"] = round(float(row["seconds"]), 6)
    return rows


def staged_sieve_benchmark(
    solver: MSolve,
    roots: Iterable[RootedPlaneGraph],
    *,
    primes: tuple[int, ...],
    timeout: float,
) -> dict[str, object]:
    config = SearchConfig(
        primes=primes,
        sieve_mode=SieveMode.HEURISTIC_PRUNE,
        presentation=PresentationChoice.BILINEAR,
        modular_timeout=timeout,
        exact_timeout=timeout,
    )
    workflow = SearchWorkflow(solver, config)
    tasks = shelved = survivors = timeouts = probes = 0
    seconds = 0.0
    by_edges: dict[int, dict[str, int]] = {}
    for rooted in roots:
        tasks += 1
        presentation = build_bilinear_presentation(rooted)
        expected_degree = workflow.good_reduction.expected_degree(rooted)
        rejected = False
        edge_row = by_edges.setdefault(
            rooted.graph.edge_count,
            {"tasks": 0, "shelved": 0, "survived": 0},
        )
        edge_row["tasks"] += 1
        for prime in primes:
            probe = workflow._probe(presentation, prime, expected_degree)
            probes += 1
            seconds += probe.seconds
            timeouts += int(probe.timed_out)
            if not probe.timed_out and probe.squarefree and probe.has_no_mondrian_point:
                rejected = True
                break
        if rejected:
            shelved += 1
            edge_row["shelved"] += 1
        else:
            survivors += 1
            edge_row["survived"] += 1
    return {
        "tasks": tasks,
        "shelved": shelved,
        "survivors": survivors,
        "probes": probes,
        "timeouts": timeouts,
        "seconds": round(seconds, 6),
        "by_edges": by_edges,
    }


def exact_benchmark(
    solver: MSolve,
    rooted: RootedPlaneGraph,
    *,
    timeout: float,
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for presentation in presentations(rooted):
        started = perf_counter()
        try:
            solve = solver.exact(presentation.system, timeout=timeout)
        except SolveTimeout:
            rows[presentation.kind.value] = {
                "solved": False,
                "timed_out": True,
                "seconds": round(perf_counter() - started, 6),
            }
        else:
            rows[presentation.kind.value] = {
                "solved": True,
                "timed_out": False,
                "seconds": round(solve.timing.seconds, 6),
                "degree": solve.rur.degree if solve.rur else 0,
                "rational_points": (
                    len(solve.rur.rational_points()) if solve.rur else 0
                ),
            }
    return rows


def parallel_benchmark(
    roots: tuple[RootedPlaneGraph, ...],
    *,
    msolve: str,
    primes: tuple[int, ...],
    timeout: float,
    parallel_workers: int,
) -> dict[str, object]:
    config = SearchConfig(
        primes=primes,
        sieve_mode=SieveMode.HEURISTIC_PRUNE,
        presentation=PresentationChoice.BILINEAR,
        exact_threads=1,
        modular_timeout=timeout,
        exact_timeout=timeout,
    )
    rows: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="agentic-blanche-benchmark-") as temp:
        for workers in (1, parallel_workers):
            store = SQLiteTaskStore(Path(temp) / f"workers-{workers}.sqlite")
            store.enqueue_many(roots)
            started = perf_counter()
            summaries = run_parallel(
                store,
                msolve=msolve,
                config=config,
                workers=workers,
            )
            elapsed = perf_counter() - started
            rows[str(workers)] = {
                "seconds": round(elapsed, 6),
                "counts": store.counts(),
                "worker_completed": [summary.completed for summary in summaries],
                "worker_failed": [summary.failed for summary in summaries],
            }
    serial = rows["1"]["seconds"]
    parallel = rows[str(parallel_workers)]["seconds"]
    return {
        "runs": rows,
        "speedup": round(serial / parallel, 6),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--plantri", default="plantri")
    result.add_argument("--msolve", default="msolve")
    result.add_argument("--prime", type=int, default=65_521)
    result.add_argument("--prime-count", type=int, default=9)
    result.add_argument("--modular-timeout", type=float, default=1.0)
    result.add_argument("--exact-timeout", type=float, default=30.0)
    result.add_argument("--parallel-workers", type=int, default=4)
    result.add_argument("--output", type=Path)
    return result


def main() -> None:
    args = parser().parse_args()
    plantri = Plantri(args.plantri)
    solver = MSolve(args.msolve)
    samples = {
        edges: stratified_roots(plantri, edges, count)
        for edges, count in SAMPLE_SIZES.items()
    }
    result = {
        "configuration": {
            "sample_sizes": SAMPLE_SIZES,
            "prime": args.prime,
            "prime_count": args.prime_count,
            "modular_timeout": args.modular_timeout,
            "exact_timeout": args.exact_timeout,
        },
        "modular": {
            edges: modular_benchmark(
                solver,
                roots,
                prime=args.prime,
                timeout=args.modular_timeout,
            )
            for edges, roots in samples.items()
        },
        "staged_sieve": staged_sieve_benchmark(
            solver,
            (rooted for roots in samples.values() for rooted in roots),
            primes=descending_primes(args.prime_count, args.prime),
            timeout=args.modular_timeout,
        ),
        "exact_18": exact_benchmark(
            solver,
            samples[18][0],
            timeout=args.exact_timeout,
        ),
        "parallel_21": parallel_benchmark(
            samples[21],
            msolve=args.msolve,
            primes=descending_primes(args.prime_count, args.prime),
            timeout=args.modular_timeout,
            parallel_workers=args.parallel_workers,
        ),
    }
    serialized = json.dumps(result, indent=2, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
