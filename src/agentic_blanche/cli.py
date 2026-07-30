"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentic_blanche.msolve import MSolve
from agentic_blanche.plantri import Plantri
from agentic_blanche.workflow import (
    JSONLCheckpoint,
    PresentationChoice,
    SearchConfig,
    SearchWorkflow,
    SieveMode,
    descending_primes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-blanche",
        description="Search rooted polyhedral graphs for rational Mondrian points.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="run the staged search")
    search.add_argument("--edges", type=int, required=True)
    search.add_argument("--limit", type=int)
    search.add_argument(
        "--output",
        type=Path,
        help="JSONL checkpoint path (default: results/E<edges>.jsonl)",
    )
    search.add_argument("--plantri", default="plantri")
    search.add_argument("--msolve", default="msolve")
    search.add_argument("--include-duals", action="store_true")
    search.add_argument(
        "--sieve-mode",
        choices=[mode.value for mode in SieveMode],
        default=SieveMode.REPORT.value,
    )
    search.add_argument("--prime-count", type=int, default=9)
    search.add_argument("--prime-start", type=int, default=65_521)
    search.add_argument(
        "--presentation",
        choices=[choice.value for choice in PresentationChoice],
        default=PresentationChoice.AUTO.value,
    )
    search.add_argument("--no-pilot", action="store_true")
    search.add_argument("--exact-threads", type=int, default=8)
    search.add_argument("--timeout", type=float)

    enumerate_parser = subparsers.add_parser(
        "enumerate", help="count streamed graph/root tasks"
    )
    enumerate_parser.add_argument("--edges", type=int, required=True)
    enumerate_parser.add_argument("--limit", type=int)
    enumerate_parser.add_argument("--plantri", default="plantri")
    enumerate_parser.add_argument("--include-duals", action="store_true")
    return parser


def _search(args: argparse.Namespace) -> int:
    output = args.output or Path(f"results/E{args.edges}.jsonl")
    plantri = Plantri(args.plantri)
    solver = MSolve(
        executable=args.msolve,
        threads=args.exact_threads,
        timeout=args.timeout,
    )
    config = SearchConfig(
        primes=descending_primes(args.prime_count, args.prime_start),
        sieve_mode=SieveMode(args.sieve_mode),
        presentation=PresentationChoice(args.presentation),
        pilot_presentations=not args.no_pilot,
        exact_threads=args.exact_threads,
    )
    workflow = SearchWorkflow(solver, config)
    checkpoint = JSONLCheckpoint(output)
    rooted_graphs = plantri.rooted_graphs(
        args.edges,
        quotient_duality=not args.include_duals,
    )

    processed = pruned = rational = candidates = 0
    for result in workflow.run(
        rooted_graphs,
        checkpoint=checkpoint,
        limit=args.limit,
    ):
        processed += 1
        pruned += int(result.pruned)
        rational += len(result.rational_solutions)
        candidates += len(result.mondrian_candidates)
        print(json.dumps(result.to_dict(), sort_keys=True), flush=True)
    print(
        json.dumps(
            {
                "processed": processed,
                "pruned": pruned,
                "rational_points": rational,
                "mondrian_candidates": candidates,
                "checkpoint": str(output),
            }
        )
    )
    return 0


def _enumerate(args: argparse.Namespace) -> int:
    plantri = Plantri(args.plantri)
    count = 0
    for rooted in plantri.rooted_graphs(
        args.edges,
        quotient_duality=not args.include_duals,
    ):
        count += 1
        print(
            json.dumps(
                {
                    "index": count,
                    "vertices": rooted.graph.vertex_count,
                    "faces": rooted.graph.face_count,
                    "root": rooted.root,
                }
            )
        )
        if args.limit is not None and count >= args.limit:
            break
    print(json.dumps({"rooted_graphs": count}))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "search":
            return _search(args)
        if args.command == "enumerate":
            return _enumerate(args)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    raise AssertionError("unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
