"""Human-friendly command-line interface."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
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

DEFAULT_WORKERS = min(8, os.cpu_count() or 1)


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    pass


@dataclass(frozen=True)
class EdgeSummary:
    edges: int
    tasks: int
    queued: int
    requeued: int
    counts: dict[str, int]
    rational_points: int
    candidates: int
    seconds: float
    database: Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-blanche",
        description=(
            "Search rooted polyhedral graphs for rational perfect Mondrian dissections."
        ),
        epilog="""examples:
  agentic-blanche search 7 11
  agentic-blanche search 17 17 --workers 8
  agentic-blanche search 7 11 --sieve-mode report
  agentic-blanche enumerate 18

The search range is inclusive. Results are resumable and are written to
results/E<edges>.sqlite by default.""",
        formatter_class=_HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser(
        "search",
        help="search every edge count in an inclusive range",
        description=(
            "Search every edge count from MIN_EDGES through MAX_EDGES, inclusive. "
            "The defaults run the bilinear, heuristically pruned workflow."
        ),
        formatter_class=_HelpFormatter,
    )
    search.add_argument("min_edges", type=int, metavar="MIN_EDGES")
    search.add_argument("max_edges", type=int, metavar="MAX_EDGES")
    search.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="directory for one SQLite database and manifest per edge count",
    )
    search.add_argument("--plantri", default="plantri", help="plantri executable")
    search.add_argument("--msolve", default="msolve", help="msolve executable")
    search.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="parallel worker processes",
    )
    search.add_argument(
        "--sieve-mode",
        choices=[mode.value for mode in SieveMode],
        default=SieveMode.HEURISTIC_PRUNE.value,
        help="'heuristic-prune' is fast but not a proof; use 'report' for safety",
    )
    search.add_argument(
        "--presentation",
        choices=[choice.value for choice in PresentationChoice],
        default=PresentationChoice.BILINEAR.value,
        help="polynomial presentation sent to msolve",
    )
    search.add_argument(
        "--prime-count",
        type=int,
        default=9,
        help="maximum finite-field probes per task",
    )
    search.add_argument(
        "--prime-start",
        type=int,
        default=65_521,
        help="largest prime to consider",
    )
    search.add_argument(
        "--modular-timeout",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="timeout for each finite-field solve",
    )
    search.add_argument(
        "--exact-timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="timeout for each characteristic-zero solve",
    )
    search.add_argument(
        "--progress-interval",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="interval between progress lines during a long edge layer",
    )
    search.add_argument(
        "--exact-threads",
        type=int,
        default=1,
        help="msolve threads per worker",
    )
    search.add_argument(
        "--lease-seconds",
        type=float,
        default=3600,
        help=argparse.SUPPRESS,
    )
    search.add_argument(
        "--limit",
        type=int,
        metavar="TASKS",
        help="process at most this many rooted tasks per edge count",
    )
    search.add_argument(
        "--include-duals",
        action="store_true",
        help="do not quotient rooted tasks by planar duality",
    )
    search.add_argument(
        "--no-pilot",
        action="store_true",
        help="disable presentation pilot probes when using --presentation auto",
    )
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
        help="terminal task state to run again; may be repeated",
    )

    enumerate_parser = subparsers.add_parser(
        "enumerate",
        help="count rooted graph/orbit tasks without solving",
        formatter_class=_HelpFormatter,
    )
    enumerate_parser.add_argument("edges", type=int, metavar="EDGES")
    enumerate_parser.add_argument("--limit", type=int, metavar="TASKS")
    enumerate_parser.add_argument(
        "--plantri",
        default="plantri",
        help="plantri executable",
    )
    enumerate_parser.add_argument(
        "--include-duals",
        action="store_true",
        help="do not quotient rooted tasks by planar duality",
    )
    enumerate_parser.add_argument(
        "--verbose",
        action="store_true",
        help="print one JSON record per rooted task",
    )
    return parser


def _validate_search_args(args: argparse.Namespace) -> None:
    if args.min_edges < 6:
        raise ValueError("MIN_EDGES must be at least 6")
    if args.max_edges < args.min_edges:
        raise ValueError("MAX_EDGES must be greater than or equal to MIN_EDGES")
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    if args.progress_interval <= 0:
        raise ValueError("--progress-interval must be positive")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _solution_counts(store: SQLiteTaskStore) -> tuple[int, int]:
    rational_points = candidates = 0
    for result in store.results():
        solutions = result.get("rational_solutions", [])
        if not isinstance(solutions, list):
            continue
        rational_points += len(solutions)
        candidates += sum(
            isinstance(solution, dict)
            and bool(solution.get("mondrian_candidate", False))
            for solution in solutions
        )
    return rational_points, candidates


def _terminal_count(counts: dict[str, int]) -> int:
    return sum(
        counts[status.value]
        for status in (
            TaskStatus.COMPLETED,
            TaskStatus.SHELVED,
            TaskStatus.TIMED_OUT,
            TaskStatus.FAILED,
        )
    )


def _progress_line(edges: int, counts: dict[str, int], started: float) -> None:
    total = sum(counts.values())
    finished = _terminal_count(counts)
    percent = 100 * finished / total if total else 100
    print(
        f"  E{edges}: {finished:,}/{total:,} ({percent:5.1f}%) | "
        f"shelved {counts[TaskStatus.SHELVED.value]:,} | "
        f"exact {counts[TaskStatus.COMPLETED.value]:,} | "
        f"elapsed {_duration(time.monotonic() - started)}",
        flush=True,
    )


def _run_edge(args: argparse.Namespace, edges: int) -> EdgeSummary:
    started = time.monotonic()
    output = args.results_dir / f"E{edges}.sqlite"
    manifest_path = output.with_suffix(".manifest.json")
    config = SearchConfig(
        primes=descending_primes(args.prime_count, args.prime_start),
        sieve_mode=SieveMode(args.sieve_mode),
        presentation=PresentationChoice(args.presentation),
        pilot_presentations=not args.no_pilot,
        exact_threads=args.exact_threads,
        modular_timeout=args.modular_timeout,
        exact_timeout=args.exact_timeout,
    )
    print(f"\nE{edges}: enumerating rooted graph/orbit tasks...", flush=True)
    rooted_graphs = Plantri(args.plantri).rooted_graphs(
        edges,
        quotient_duality=not args.include_duals,
    )
    if args.limit is not None:
        rooted_graphs = itertools.islice(rooted_graphs, args.limit)

    store = SQLiteTaskStore(output)
    queued = store.enqueue_many(rooted_graphs)
    requeued = store.requeue(TaskStatus(status) for status in args.requeue)
    counts = store.counts()
    tasks = sum(counts.values())
    print(
        f"  {tasks:,} tasks in {output} ({queued:,} new, {requeued:,} requeued).",
        flush=True,
    )

    manifest = create_manifest(
        argv=sys.argv,
        config={
            "edge_range": [args.min_edges, args.max_edges],
            "edges": edges,
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

    if counts[TaskStatus.PENDING.value] or counts[TaskStatus.RUNNING.value]:
        print(
            f"  starting {args.workers} worker{'s' if args.workers != 1 else ''}...",
            flush=True,
        )
        run_parallel(
            store,
            msolve=args.msolve,
            config=config,
            workers=args.workers,
            lease_seconds=args.lease_seconds,
            progress=lambda current: _progress_line(edges, current, started),
            progress_interval=args.progress_interval,
        )
    else:
        print("  no unfinished tasks; verifying the existing database.", flush=True)

    store.checkpoint_and_check()
    counts = store.counts()
    rational_points, candidates = _solution_counts(store)
    seconds = time.monotonic() - started
    print(
        f"  finished E{edges} in {_duration(seconds)}: "
        f"{counts[TaskStatus.SHELVED.value]:,} shelved, "
        f"{counts[TaskStatus.COMPLETED.value]:,} exact-completed, "
        f"{candidates:,} candidate{'s' if candidates != 1 else ''}.",
        flush=True,
    )
    return EdgeSummary(
        edges=edges,
        tasks=sum(counts.values()),
        queued=queued,
        requeued=requeued,
        counts=counts,
        rational_points=rational_points,
        candidates=candidates,
        seconds=seconds,
        database=output,
    )


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def line(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.rjust(width) for value, width in zip(row, widths, strict=True)
        )

    separator = tuple("-" * width for width in widths)
    return "\n".join((line(headers), line(separator), *(line(row) for row in rows)))


def _print_summary(
    summaries: list[EdgeSummary],
    min_edges: int,
    max_edges: int,
) -> None:
    rows = [
        (
            str(summary.edges),
            f"{summary.tasks:,}",
            f"{summary.counts[TaskStatus.SHELVED.value]:,}",
            f"{summary.counts[TaskStatus.COMPLETED.value]:,}",
            f"{summary.counts[TaskStatus.TIMED_OUT.value]:,}",
            f"{summary.counts[TaskStatus.FAILED.value]:,}",
            f"{summary.rational_points:,}",
            f"{summary.candidates:,}",
            _duration(summary.seconds),
        )
        for summary in summaries
    ]
    print(f"\nSearch complete: inclusive edge range {min_edges}–{max_edges}")
    print(
        _table(
            (
                "Edges",
                "Tasks",
                "Shelved",
                "Exact",
                "Timeout",
                "Failed",
                "Q-points",
                "Candidates",
                "Time",
            ),
            rows,
        )
    )
    candidates = sum(summary.candidates for summary in summaries)
    if candidates:
        print(f"\nFound {candidates:,} rational Mondrian candidate(s).")
    else:
        print("\nNo rational Mondrian candidates were found.")
    print(
        "Heuristic shelving is evidence, not a proof of nonexistence; "
        "use --sieve-mode report for a non-pruning run."
    )


def _search(args: argparse.Namespace) -> int:
    _validate_search_args(args)
    summaries = [
        _run_edge(args, edges) for edges in range(args.min_edges, args.max_edges + 1)
    ]
    _print_summary(summaries, args.min_edges, args.max_edges)
    unfinished_or_failed = any(
        summary.counts[TaskStatus.PENDING.value]
        or summary.counts[TaskStatus.RUNNING.value]
        or summary.counts[TaskStatus.FAILED.value]
        for summary in summaries
    )
    return int(unfinished_or_failed)


def _enumerate(args: argparse.Namespace) -> int:
    if args.edges < 6:
        raise ValueError("EDGES must be at least 6")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    print(f"Enumerating rooted tasks with {args.edges} graph edges...", flush=True)
    count = 0
    for rooted in Plantri(args.plantri).rooted_graphs(
        args.edges,
        quotient_duality=not args.include_duals,
    ):
        count += 1
        if args.verbose:
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
    print(f"Found {count:,} rooted graph/orbit tasks.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "search":
            return _search(args)
        if args.command == "enumerate":
            return _enumerate(args)
    except (RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    raise AssertionError("unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
