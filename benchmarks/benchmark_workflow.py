"""Compare edge-current, adaptive-cycle, and modular msolve timings."""

from __future__ import annotations

import argparse
import json

from agentic_blanche.graph import RootedPlaneGraph
from agentic_blanche.msolve import MSolve
from agentic_blanche.plantri import Plantri
from agentic_blanche.presentations import (
    build_adaptive_cycle_presentation,
    build_bilinear_presentation,
    build_edge_current_presentation,
)
from agentic_blanche.symmetry import edge_orbit_representatives
from agentic_blanche.workflow import descending_primes


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--edges", type=int, required=True)
    result.add_argument("--vertices", type=int, required=True)
    result.add_argument("--graph-index", type=int, default=0)
    result.add_argument("--root-index", type=int, default=0)
    result.add_argument("--prime-count", type=int, default=5)
    result.add_argument("--plantri", default="plantri")
    result.add_argument("--msolve", default="msolve")
    result.add_argument("--threads", type=int, default=1)
    return result


def main() -> None:
    args = parser().parse_args()
    plantri = Plantri(args.plantri)
    graph = next(
        graph
        for index, graph in enumerate(plantri.graphs(args.vertices, args.edges))
        if index == args.graph_index
    )
    root = edge_orbit_representatives(graph)[args.root_index]
    rooted = RootedPlaneGraph(graph, root)
    solver = MSolve(args.msolve, threads=args.threads)

    presentations = (
        build_edge_current_presentation(rooted),
        build_adaptive_cycle_presentation(rooted),
        build_bilinear_presentation(rooted),
    )
    rows = []
    for presentation in presentations:
        exact = solver.exact(presentation.system)
        probes = [
            solver.finite(presentation.system, prime)
            for prime in descending_primes(args.prime_count)
        ]
        row = {
            "presentation": presentation.kind.value,
            "variables": len(presentation.system.variables),
            "terms": presentation.system.term_count,
            "max_equation_terms": presentation.system.maximum_term_count,
            "exact_seconds": exact.timing.seconds,
            "exact_degree": exact.rur.degree if exact.rur else 0,
            "rational_points": (len(exact.rur.rational_points()) if exact.rur else 0),
            "modular_seconds": sum(probe.timing.seconds for probe in probes),
            "factor_profiles": [
                list(probe.rur.factor_degrees) if probe.rur else [] for probe in probes
            ],
        }
        print(json.dumps(row), flush=True)
        rows.append(row)
    baseline = rows[0]
    print(
        json.dumps(
            {
                row["presentation"]: {
                    "exact_speedup_vs_edge": (
                        baseline["exact_seconds"] / row["exact_seconds"]
                    ),
                    "modular_speedup_vs_edge": (
                        baseline["modular_seconds"] / row["modular_seconds"]
                    ),
                }
                for row in rows[1:]
            }
        )
    )


if __name__ == "__main__":
    main()
