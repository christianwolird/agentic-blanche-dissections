#!/usr/bin/env python3
"""Render all real algebraic solutions associated with one stored task."""

from __future__ import annotations

import argparse
from pathlib import Path

from agentic_blanche.presentations import PresentationKind
from agentic_blanche.visualization import (
    load_task_entry,
    render_task_svg,
    solve_task_tilings,
)


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description=(
            "Rerun the exact solve for one rooted-graph task and draw every real "
            "rational or irrational solution as an annotated square tiling."
        ),
        epilog=(
            "Example: python tools/visualize_task.py results/E8.sqlite "
            "4e6514469bf044184dfd8049"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    argument_parser.add_argument(
        "database",
        type=Path,
        help="search database such as results/E15.sqlite",
    )
    argument_parser.add_argument(
        "task",
        help="task sequence number or canonical task ID",
    )
    argument_parser.add_argument(
        "--output",
        type=Path,
        help="output SVG (defaults under results/visualizations/)",
    )
    argument_parser.add_argument(
        "--msolve",
        default="msolve",
        help="msolve executable or path",
    )
    argument_parser.add_argument(
        "--presentation",
        choices=("stored", *(kind.value for kind in PresentationKind)),
        default="stored",
        help="presentation to solve; stored reuses the task result when available",
    )
    argument_parser.add_argument(
        "--precision",
        type=int,
        default=80,
        help="decimal digits used before converting coordinates for display",
    )
    argument_parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="msolve threads",
    )
    argument_parser.add_argument(
        "--timeout",
        type=float,
        help="optional exact-solve timeout in seconds",
    )
    argument_parser.add_argument(
        "--columns",
        type=int,
        default=2,
        help="solution panels per row",
    )
    return argument_parser


def main() -> int:
    arguments = parser().parse_args()
    entry = load_task_entry(arguments.database, arguments.task)
    print(
        f"Solving task {entry.task_id} (sequence {entry.sequence}, "
        f"{entry.rooted.rectangle_count} rectangles)...",
        flush=True,
    )
    tilings = solve_task_tilings(
        entry,
        msolve=arguments.msolve,
        presentation=arguments.presentation,
        threads=arguments.threads,
        timeout=arguments.timeout,
        precision=arguments.precision,
    )
    if not tilings:
        raise SystemExit("The task has no real zero-dimensional solutions.")
    output = arguments.output
    if output is None:
        output = (
            arguments.database.parent
            / "visualizations"
            / f"{arguments.database.stem}-task-{entry.sequence}.svg"
        )
    render_task_svg(entry, tilings, output, columns=arguments.columns)
    rational = sum(tiling.algebraic_degree == 1 for tiling in tilings)
    irrational = len(tilings) - rational
    print(
        f"Rendered {len(tilings)} real solutions "
        f"({rational} rational, {irrational} irrational) to {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
