"""Command-line interface."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from agentic_blanche.manifest import create_manifest
from agentic_blanche.parallel import run_parallel
from agentic_blanche.plantri import Plantri
from agentic_blanche.storage import SQLiteTaskStore, TaskStatus
from agentic_blanche.workflow import (
    PresentationChoice,
    SearchConfig,
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
        help="SQLite task database (default: results/E<edges>.sqlite)",
    )
    search.add_argument("--manifest", type=Path)
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
        default=PresentationChoice.BILINEAR.value,
    )
    search.add_argument("--no-pilot", action="store_true")
    search.add_argument("--workers", type=int, default=1)
    search.add_argument("--exact-threads", type=int, default=1)
    search.add_argument("--modular-timeout", type=float, default=1.0)
    search.add_argument("--exact-timeout", type=float)
    search.add_argument("--lease-seconds", type=float, default=3600)
    search.add_argument(
        "--requeue",
        action="append",
        choices=[
            TaskStatus.COMPLETED.value,
            TaskStatus.SHELVED.value,
            TaskStatus.TIMED_OUT.value,
            TaskStatus.FAILED.value,
        ],
        default=[],
        help="terminal task state to return to pending; may be repeated",
    )

    enumerate_parser = subparsers.add_parser(
        "enumerate", help="count streamed graph/root tasks"
    )
    enumerate_parser.add_argument("--edges", type=int, required=True)
    enumerate_parser.add_argument("--limit", type=int)
    enumerate_parser.add_argument("--plantri", default="plantri")
    enumerate_parser.add_argument("--include-duals", action="store_true")
    return parser


def _search(args: argparse.Namespace) -> int:
    output = args.output or Path(f"results/E{args.edges}.sqlite")
    manifest_path = args.manifest or output.with_suffix(".manifest.json")
    plantri = Plantri(args.plantri)
    config = SearchConfig(
        primes=descending_primes(args.prime_count, args.prime_start),
        sieve_mode=SieveMode(args.sieve_mode),
        presentation=PresentationChoice(args.presentation),
        pilot_presentations=not args.no_pilot,
        exact_threads=args.exact_threads,
        modular_timeout=args.modular_timeout,
        exact_timeout=args.exact_timeout,
    )
    rooted_graphs = plantri.rooted_graphs(
        args.edges,
        quotient_duality=not args.include_duals,
    )
    if args.limit is not None:
        rooted_graphs = itertools.islice(rooted_graphs, args.limit)

    store = SQLiteTaskStore(output)
    queued = store.enqueue_many(rooted_graphs)
    requeued = store.requeue(TaskStatus(status) for status in args.requeue)
    manifest = create_manifest(
        argv=sys.argv,
        config={
            "edges": args.edges,
            "primes": list(config.primes),
            "sieve_mode": config.sieve_mode.value,
            "presentation": config.presentation.value,
            "pilot_presentations": config.pilot_presentations,
            "workers": args.workers,
            "exact_threads": config.exact_threads,
            "modular_timeout": config.modular_timeout,
            "exact_timeout": config.exact_timeout,
            "quotient_duality": not args.include_duals,
            "requeued_statuses": args.requeue,
        },
        repository=Path(__file__).resolve().parents[2],
        plantri=args.plantri,
        msolve=args.msolve,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    store.record_manifest(str(manifest["run_id"]), manifest)
    workers = run_parallel(
        store,
        msolve=args.msolve,
        config=config,
        workers=args.workers,
        lease_seconds=args.lease_seconds,
    )
    print(
        json.dumps(
            {
                "queued": queued,
                "requeued": requeued,
                "workers": [
                    {
                        "worker_id": worker.worker_id,
                        "completed": worker.completed,
                        "failed": worker.failed,
                    }
                    for worker in workers
                ],
                "counts": store.counts(),
                "database": str(output),
                "manifest": str(manifest_path),
            }
        ),
        flush=True,
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
