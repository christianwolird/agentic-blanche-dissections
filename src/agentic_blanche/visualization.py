"""Exact classification and SVG rendering of solutions from stored tasks."""

from __future__ import annotations

import colorsys
import html
import json
import math
import sqlite3
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import sympy

from agentic_blanche.graph import Edge, PlaneGraph, RootedPlaneGraph, canonical_edge
from agentic_blanche.msolve import ExactRUR, MSolve
from agentic_blanche.presentations import (
    KirchhoffPresentation,
    PresentationKind,
    build_bilinear_presentation,
    build_cycle_presentation,
    build_edge_current_presentation,
)

UNIQUE_FILL = "#fdf6e3"
CONGRUENCE_COLORS = (
    "#268bd2",  # Solarized blue
    "#dc322f",  # Solarized red
    "#859900",  # Solarized green
    "#6c71c4",  # Solarized violet
    "#2aa198",  # Solarized cyan
    "#d33682",  # Solarized magenta
    "#cb4b16",  # Solarized orange
    "#b58900",  # Solarized yellow
)


@dataclass(frozen=True)
class TaskEntry:
    """One rooted-graph task loaded from a search SQLite database."""

    database: Path
    sequence: int
    task_id: str
    rooted: RootedPlaneGraph
    status: str
    stored_presentation: str | None


@dataclass(frozen=True)
class RectangleGeometry:
    """One rectangle in unit-square display coordinates."""

    rectangle_id: int
    edge: Edge
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class AlgebraicTiling:
    """One real RUR branch, with exact classes and approximate geometry."""

    algebraic_degree: int
    parameter_approximation: str
    factor: sympy.Poly
    congruence_classes: tuple[tuple[int, ...], ...]
    partition_label: str
    rectangles: tuple[RectangleGeometry, ...]


def load_task_entry(database: Path, selector: str | int) -> TaskEntry:
    """Load a task by numeric sequence or canonical task ID."""
    database = Path(database)
    if not database.is_file():
        raise FileNotFoundError(f"task database does not exist: {database}")

    if isinstance(selector, int) or str(selector).isdigit():
        predicate = "sequence = ?"
        value: object = int(selector)
    else:
        predicate = "task_id = ?"
        value = str(selector)

    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            f"""
            SELECT sequence, task_id, payload, status, result
            FROM tasks
            WHERE {predicate}
            """,
            (value,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"no task matching {selector!r} in {database}")

    payload = json.loads(str(row["payload"]))
    graph = PlaneGraph(
        tuple(
            tuple(int(neighbor) for neighbor in neighbors)
            for neighbors in payload["rotations"]
        )
    )
    rooted = RootedPlaneGraph(
        graph,
        tuple(int(vertex) for vertex in payload["root"]),
    )
    result = json.loads(str(row["result"])) if row["result"] else {}
    return TaskEntry(
        database=database,
        sequence=int(row["sequence"]),
        task_id=str(row["task_id"]),
        rooted=rooted,
        status=str(row["status"]),
        stored_presentation=result.get("presentation"),
    )


def build_task_presentation(
    entry: TaskEntry,
    requested: str = "stored",
) -> KirchhoffPresentation:
    """Rebuild the exact presentation used by a task, or an explicit override."""
    kind = entry.stored_presentation if requested == "stored" else requested
    kind = kind or PresentationKind.BILINEAR.value
    if kind == PresentationKind.BILINEAR.value:
        return build_bilinear_presentation(entry.rooted)
    if kind == PresentationKind.EDGE_CURRENT.value:
        return build_edge_current_presentation(entry.rooted)
    if kind == PresentationKind.CYCLE_PRIMAL.value:
        return build_cycle_presentation(entry.rooted, dual=False)
    if kind == PresentationKind.CYCLE_DUAL.value:
        return build_cycle_presentation(entry.rooted, dual=True)
    raise ValueError(f"unknown presentation: {kind}")


def _polynomial_expression(coefficients: tuple[int, ...], parameter: sympy.Symbol):
    return sum(
        coefficient * parameter**degree
        for degree, coefficient in enumerate(coefficients)
    )


def rur_coordinate_functions(
    rur: ExactRUR,
    parameter: sympy.Symbol,
) -> dict[str, sympy.Expr]:
    """Return every RUR coordinate as an exact rational function of ``t``."""
    denominator = _polynomial_expression(rur.denominator, parameter)
    coordinates = [
        sympy.cancel(
            -_polynomial_expression(coefficients, parameter) / (divisor * denominator)
        )
        for coefficients, divisor in rur.parametrizations
    ]
    if len(coordinates) == len(rur.variables) - 1:
        primitive_indices = [
            index for index, coefficient in enumerate(rur.linear_form) if coefficient
        ]
        if len(primitive_indices) != 1 or rur.linear_form[primitive_indices[0]] != 1:
            raise ValueError("RUR does not identify an omitted coordinate")
        coordinates.insert(primitive_indices[0], parameter)
    elif len(coordinates) != len(rur.variables):
        raise ValueError("unexpected number of RUR coordinate functions")
    return dict(zip(rur.variables, coordinates, strict=True))


def recover_current_functions(
    presentation: KirchhoffPresentation,
    coordinates: Mapping[str, sympy.Expr],
) -> dict[Edge, sympy.Expr]:
    """Compose presentation recovery with exact RUR coordinate functions."""
    ordered = tuple(coordinates[name] for name in presentation.system.variables)
    model_values = {
        edge: sympy.cancel(current.evaluate(ordered))
        for edge, current in presentation.model_currents.items()
    }
    recovered: dict[Edge, sympy.Expr] = {}
    for item in presentation.recovery:
        value = model_values[item.model_edge]
        if item.reciprocal_scale is not None:
            value = item.reciprocal_scale / value
        recovered[item.original_edge] = sympy.cancel(item.orientation_sign * value)
    return recovered


def _zero_mod_factor(
    expression: sympy.Expr,
    factor: sympy.Poly,
    parameter: sympy.Symbol,
) -> bool:
    numerator, denominator = sympy.cancel(expression).as_numer_denom()
    numerator_polynomial = sympy.Poly(numerator, parameter, domain=sympy.QQ)
    denominator_polynomial = sympy.Poly(denominator, parameter, domain=sympy.QQ)
    if not sympy.gcd(factor, denominator_polynomial).is_one:
        raise ValueError("a recovered rational function has a pole on an RUR branch")
    return numerator_polynomial.rem(factor).is_zero


def exact_congruence_classes(
    currents: Mapping[Edge, sympy.Expr],
    rectangle_count: int,
    factor: sympy.Poly,
    parameter: sympy.Symbol,
) -> tuple[tuple[int, ...], ...]:
    """Classify congruence exactly in ``QQ[t]/(factor)``.

    Rectangle IDs are the one-based positions of the sorted original edges.
    """
    edges = tuple(sorted(currents))
    parent = list(range(len(edges)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left_edge in enumerate(edges):
        left = currents[left_edge]
        for right_index in range(left_index + 1, len(edges)):
            right = currents[edges[right_index]]
            parallel = left**2 - right**2
            rotated = left**2 * right**2 - rectangle_count**2
            if _zero_mod_factor(parallel, factor, parameter) or _zero_mod_factor(
                rotated, factor, parameter
            ):
                union(left_index, right_index)

    groups: dict[int, list[int]] = {}
    for index in range(len(edges)):
        groups.setdefault(find(index), []).append(index + 1)
    return tuple(
        tuple(group) for group in sorted(groups.values(), key=lambda group: group[0])
    )


def _verify_exact_branch(
    rooted: RootedPlaneGraph,
    presentation: KirchhoffPresentation,
    coordinates: Mapping[str, sympy.Expr],
    currents: Mapping[Edge, sympy.Expr],
    factor: sympy.Poly,
    parameter: sympy.Symbol,
) -> None:
    ordered = tuple(coordinates[name] for name in presentation.system.variables)
    for equation in presentation.system.polynomials:
        if not _zero_mod_factor(equation.evaluate(ordered), factor, parameter):
            raise ValueError("an RUR branch lies outside the input variety")

    divergences: dict[int, sympy.Expr] = {
        vertex: sympy.Integer(0) for vertex in range(rooted.graph.vertex_count)
    }
    for (tail, head), current in currents.items():
        divergences[tail] += current
        divergences[head] -= current
    for vertex, divergence in divergences.items():
        expected = 0
        if vertex == rooted.source:
            expected = rooted.rectangle_count
        elif vertex == rooted.sink:
            expected = -rooted.rectangle_count
        if not _zero_mod_factor(divergence - expected, factor, parameter):
            raise ValueError("an RUR branch violates original KCL")

    faces, boundary = rooted.graph.faces_and_boundary
    root_faces = {
        boundary[(rooted.source, rooted.sink)],
        boundary[(rooted.sink, rooted.source)],
    }
    for face_id, face in enumerate(faces):
        if face_id in root_faces:
            continue
        voltage_sum = sympy.Integer(0)
        for dart in face:
            edge = canonical_edge(dart)
            sign = 1 if dart == edge else -1
            voltage_sum += sign / currents[edge]
        if not _zero_mod_factor(voltage_sum, factor, parameter):
            raise ValueError("an RUR branch violates original KVL")


def congruence_partition_label(
    rectangle_count: int,
    classes: tuple[tuple[int, ...], ...],
) -> str:
    """Format a compact integer partition, abbreviating three or more ones."""
    sizes = sorted((len(group) for group in classes), reverse=True)
    singleton_count = sizes.count(1)
    if singleton_count >= 3:
        parts = [str(size) for size in sizes if size > 1]
        parts.extend(("1", "..."))
    else:
        parts = [str(size) for size in sizes]
    return f"{rectangle_count}=" + "+".join(parts)


def _integrate_vertex_heights(
    rooted: RootedPlaneGraph,
    currents: Mapping[Edge, float],
    tolerance: float,
) -> dict[int, float]:
    heights = {rooted.source: 1.0}
    pending = deque([rooted.source])
    incident: dict[int, list[Edge]] = {
        vertex: [] for vertex in range(rooted.graph.vertex_count)
    }
    for edge in rooted.nonroot_edges:
        incident[edge[0]].append(edge)
        incident[edge[1]].append(edge)

    while pending:
        vertex = pending.popleft()
        for edge in incident[vertex]:
            tail, head = edge
            if vertex == tail:
                neighbor = head
                proposed = heights[vertex] - 1.0 / currents[edge]
            else:
                neighbor = tail
                proposed = heights[vertex] + 1.0 / currents[edge]
            if neighbor not in heights:
                heights[neighbor] = proposed
                pending.append(neighbor)
            elif not math.isclose(
                heights[neighbor], proposed, rel_tol=tolerance, abs_tol=tolerance
            ):
                raise ValueError("numerical currents do not define consistent heights")

    if len(heights) != rooted.graph.vertex_count:
        raise ValueError("root-deleted graph is disconnected")
    if not math.isclose(
        heights[rooted.sink], 0.0, rel_tol=tolerance, abs_tol=tolerance
    ):
        raise ValueError("numerical solution has the wrong terminal voltage")
    return heights


def _integrate_face_positions(
    rooted: RootedPlaneGraph,
    currents: Mapping[Edge, float],
    tolerance: float,
) -> tuple[dict[int, float], float, float]:
    faces, boundary = rooted.graph.faces_and_boundary
    first_boundary = boundary[rooted.root]
    second_boundary = boundary[(rooted.sink, rooted.source)]
    positions = {first_boundary: 0.0}
    pending = deque([first_boundary])
    dual_incident: dict[int, list[tuple[int, float]]] = {
        face: [] for face in range(len(faces))
    }
    for edge, current in currents.items():
        tail, head = edge
        left = boundary[(tail, head)]
        right = boundary[(head, tail)]
        # With the embedding convention in graph.py, X_left - X_right = current.
        dual_incident[left].append((right, -current))
        dual_incident[right].append((left, current))

    while pending:
        face = pending.popleft()
        for neighbor, difference in dual_incident[face]:
            proposed = positions[face] + difference
            if neighbor not in positions:
                positions[neighbor] = proposed
                pending.append(neighbor)
            elif not math.isclose(
                positions[neighbor], proposed, rel_tol=tolerance, abs_tol=tolerance
            ):
                raise ValueError("numerical currents do not define consistent widths")

    if len(positions) != len(faces):
        raise ValueError("root-deleted dual graph is disconnected")
    lower = min(positions[first_boundary], positions[second_boundary])
    upper = max(positions[first_boundary], positions[second_boundary])
    span = upper - lower
    if not math.isclose(
        span,
        rooted.rectangle_count,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        raise ValueError("numerical solution has the wrong total width")
    return positions, lower, upper


def rectangle_geometry(
    rooted: RootedPlaneGraph,
    currents: Mapping[Edge, float],
    *,
    tolerance: float = 1e-8,
) -> tuple[RectangleGeometry, ...]:
    """Recover unit-square rectangle coordinates from numerical currents."""
    if set(currents) != set(rooted.nonroot_edges):
        raise ValueError("current set does not match the rooted graph")
    if any(not math.isfinite(value) or value == 0 for value in currents.values()):
        raise ValueError("currents must be finite and nonzero")

    heights = _integrate_vertex_heights(rooted, currents, tolerance)
    positions, lower, upper = _integrate_face_positions(rooted, currents, tolerance)
    _, boundary = rooted.graph.faces_and_boundary
    span = upper - lower
    rectangles: list[RectangleGeometry] = []
    for rectangle_id, edge in enumerate(rooted.nonroot_edges, start=1):
        tail, head = edge
        left = positions[boundary[(tail, head)]]
        right = positions[boundary[(head, tail)]]
        x0 = (min(left, right) - lower) / span
        x1 = (max(left, right) - lower) / span
        y0 = min(heights[tail], heights[head])
        y1 = max(heights[tail], heights[head])
        values = (x0, x1, y0, y1)
        if any(value < -tolerance or value > 1 + tolerance for value in values):
            raise ValueError("a recovered rectangle lies outside the square")
        x0, x1, y0, y1 = (min(1.0, max(0.0, value)) for value in values)
        rectangle = RectangleGeometry(
            rectangle_id=rectangle_id,
            edge=edge,
            x=x0,
            y=y0,
            width=x1 - x0,
            height=y1 - y0,
        )
        expected_area = 1.0 / rooted.rectangle_count
        if not math.isclose(
            rectangle.width * rectangle.height,
            expected_area,
            rel_tol=5 * tolerance,
            abs_tol=5 * tolerance,
        ):
            raise ValueError("a recovered rectangle has the wrong area")
        rectangles.append(rectangle)

    if not math.isclose(
        sum(rectangle.width * rectangle.height for rectangle in rectangles),
        1.0,
        rel_tol=5 * tolerance,
        abs_tol=5 * tolerance,
    ):
        raise ValueError("recovered rectangles do not cover unit area")
    for left_index, left in enumerate(rectangles):
        for right in rectangles[left_index + 1 :]:
            overlap_width = max(
                0.0,
                min(left.x + left.width, right.x + right.width) - max(left.x, right.x),
            )
            overlap_height = max(
                0.0,
                min(left.y + left.height, right.y + right.height)
                - max(left.y, right.y),
            )
            if overlap_width * overlap_height > 10 * tolerance:
                raise ValueError("recovered rectangles overlap")
    return tuple(rectangles)


def algebraic_tilings(
    rooted: RootedPlaneGraph,
    presentation: KirchhoffPresentation,
    rur: ExactRUR,
    *,
    precision: int = 80,
) -> tuple[AlgebraicTiling, ...]:
    """Recover every real solution, retaining exact congruence information."""
    if precision < 20:
        raise ValueError("precision must be at least 20 decimal digits")
    parameter = sympy.Symbol("t")
    coordinates = rur_coordinate_functions(rur, parameter)
    if set(coordinates) != set(presentation.system.variables):
        raise ValueError("RUR variables do not match the selected presentation")
    currents = recover_current_functions(presentation, coordinates)
    polynomial = sympy.Poly(
        _polynomial_expression(rur.polynomial, parameter),
        parameter,
        domain=sympy.QQ,
    )

    branches: list[tuple[float, AlgebraicTiling]] = []
    for factor, _multiplicity in polynomial.factor_list()[1]:
        _verify_exact_branch(
            rooted,
            presentation,
            coordinates,
            currents,
            factor,
            parameter,
        )
        classes = exact_congruence_classes(
            currents,
            rooted.rectangle_count,
            factor,
            parameter,
        )
        partition = congruence_partition_label(rooted.rectangle_count, classes)
        for root in factor.real_roots(radicals=False):
            numerical_currents: dict[Edge, float] = {}
            for edge, expression in currents.items():
                approximation = sympy.N(expression.subs(parameter, root), precision)
                if approximation.is_real is not True:
                    raise ValueError("a real RUR root produced a non-real current")
                numerical_currents[edge] = float(approximation)
            geometry = rectangle_geometry(rooted, numerical_currents)
            approximation = sympy.N(root, precision)
            text = str(approximation)
            branches.append(
                (
                    float(approximation),
                    AlgebraicTiling(
                        algebraic_degree=factor.degree(),
                        parameter_approximation=text,
                        factor=factor,
                        congruence_classes=classes,
                        partition_label=partition,
                        rectangles=geometry,
                    ),
                )
            )
    branches.sort(key=lambda item: item[0])
    return tuple(branch for _, branch in branches)


def solve_task_tilings(
    entry: TaskEntry,
    *,
    msolve: str = "msolve",
    presentation: str = "stored",
    threads: int = 1,
    timeout: float | None = None,
    precision: int = 80,
) -> tuple[AlgebraicTiling, ...]:
    """Rerun the exact solve for one stored task and recover all real tilings."""
    selected = build_task_presentation(entry, presentation)
    solve = MSolve(executable=msolve, threads=threads).exact(
        selected.system,
        threads=threads,
        timeout=timeout,
    )
    if solve.rur is None:
        return ()
    return algebraic_tilings(
        entry.rooted,
        selected,
        solve.rur,
        precision=precision,
    )


def _class_colors(tiling: AlgebraicTiling) -> dict[int, str]:
    colors: dict[int, str] = {}
    non_singletons = [group for group in tiling.congruence_classes if len(group) > 1]
    for color_index, group in enumerate(non_singletons):
        if color_index < len(CONGRUENCE_COLORS):
            color = CONGRUENCE_COLORS[color_index]
        else:
            # Continue with separated saturated hues when a large tiling has
            # more non-singleton classes than the Solarized accent palette.
            hue = (0.17 + color_index * 0.61803398875) % 1.0
            red, green, blue = colorsys.hsv_to_rgb(hue, 0.72, 0.78)
            red_byte = round(red * 255)
            green_byte = round(green * 255)
            blue_byte = round(blue * 255)
            color = f"#{red_byte:02x}{green_byte:02x}{blue_byte:02x}"
        for rectangle_id in group:
            colors[rectangle_id] = color
    for group in tiling.congruence_classes:
        if len(group) == 1:
            colors[group[0]] = UNIQUE_FILL
    return colors


def _text_color(fill: str) -> str:
    red, green, blue = (int(fill[index : index + 2], 16) for index in (1, 3, 5))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#000000" if luminance >= 135 else "#ffffff"


def render_task_svg(
    entry: TaskEntry,
    tilings: tuple[AlgebraicTiling, ...],
    output: Path,
    *,
    columns: int = 2,
) -> Path:
    """Render all real solutions for one task into a single SVG image."""
    if not tilings:
        raise ValueError("the task has no real zero-dimensional solutions to render")
    if columns < 1:
        raise ValueError("columns must be positive")
    columns = min(columns, len(tilings))
    rows = math.ceil(len(tilings) / columns)
    square_size = 440
    cell_width = 500
    cell_height = 540
    top = 58
    width = 30 + columns * cell_width
    height = top + rows * cell_height + 22
    title = (
        f"Task {entry.task_id} · {entry.rooted.rectangle_count} rectangles · "
        f"{len(tilings)} real solution{'s' if len(tilings) != 1 else ''}"
    )
    metadata = {
        "database": entry.database.name,
        "sequence": entry.sequence,
        "task_id": entry.task_id,
        "rectangle_ids": {
            str(index): list(edge)
            for index, edge in enumerate(entry.rooted.nonroot_edges, start=1)
        },
        "solutions": [
            {
                "algebraic_degree": tiling.algebraic_degree,
                "parameter_approximation": tiling.parameter_approximation,
                "minimal_factor": str(tiling.factor.as_expr()),
                "congruence_classes": [
                    list(group) for group in tiling.congruence_classes
                ],
                "partition": tiling.partition_label,
            }
            for tiling in tilings
        ],
    }

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        f"<title>{html.escape(title)}</title>",
        "<desc>Equal-area square tilings. Rectangle numbers refer to the "
        "sorted non-root edges and remain fixed across solutions.</desc>",
        f"<metadata>{html.escape(json.dumps(metadata, sort_keys=True))}</metadata>",
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="30" y="34" font-family="DejaVu Sans, sans-serif" '
        f'font-size="20" font-weight="700" fill="#000000">'
        f"{html.escape(title)}</text>",
    ]

    for solution_index, tiling in enumerate(tilings, start=1):
        row, column = divmod(solution_index - 1, columns)
        cell_x = 30 + column * cell_width
        cell_y = top + row * cell_height
        square_x = cell_x + 20
        square_y = cell_y + 70
        colors = _class_colors(tiling)
        lines.extend(
            [
                f'<text x="{cell_x + 20}" y="{cell_y + 21}" '
                'font-family="DejaVu Sans, sans-serif" font-size="18" '
                f'font-weight="700" fill="#000000">Solution {solution_index}</text>',
                f'<text x="{cell_x + 20}" y="{cell_y + 43}" '
                'font-family="DejaVu Sans, sans-serif" font-size="15" '
                f'fill="#333333">Algebraic degree {tiling.algebraic_degree}</text>',
                f'<text x="{cell_x + 20}" y="{cell_y + 62}" '
                'font-family="DejaVu Sans, sans-serif" font-size="15" '
                f'fill="#333333">Congruency '
                f"{html.escape(tiling.partition_label)}</text>",
            ]
        )
        for rectangle in tiling.rectangles:
            x = square_x + rectangle.x * square_size
            y = square_y + (1.0 - rectangle.y - rectangle.height) * square_size
            rectangle_width = rectangle.width * square_size
            rectangle_height = rectangle.height * square_size
            fill = colors[rectangle.rectangle_id]
            font_size = min(
                24.0,
                max(10.0, min(rectangle_width, rectangle_height) * 0.34),
            )
            center_x = x + rectangle_width / 2
            center_y = y + rectangle_height / 2
            edge = f"{rectangle.edge[0]}-{rectangle.edge[1]}"
            lines.extend(
                [
                    f'<rect x="{x:.7f}" y="{y:.7f}" '
                    f'width="{rectangle_width:.7f}" height="{rectangle_height:.7f}" '
                    f'fill="{fill}" stroke="#000000" stroke-width="1.5">'
                    f"<title>Rectangle {rectangle.rectangle_id}; edge {edge}</title>"
                    "</rect>",
                    f'<text x="{center_x:.7f}" y="{center_y:.7f}" '
                    'text-anchor="middle" dominant-baseline="central" '
                    'font-family="DejaVu Sans, sans-serif" font-weight="700" '
                    f'font-size="{font_size:.2f}" fill="{_text_color(fill)}">'
                    f"{rectangle.rectangle_id}</text>",
                ]
            )
        lines.append(
            f'<rect x="{square_x}" y="{square_y}" width="{square_size}" '
            f'height="{square_size}" fill="none" stroke="#000000" stroke-width="2"/>'
        )
    lines.append("</svg>")

    output = Path(output)
    if output.suffix.lower() != ".svg":
        raise ValueError("the visualization output must have an .svg suffix")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
