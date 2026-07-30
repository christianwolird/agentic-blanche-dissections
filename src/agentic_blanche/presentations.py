"""Polynomial presentations of the normalized Kirchhoff algebra."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from agentic_blanche.graph import (
    Edge,
    RootedPlaneGraph,
    canonical_edge,
)
from agentic_blanche.polynomial import (
    PolynomialSystem,
    SparsePolynomial,
    polynomial_product,
)


class PresentationKind(StrEnum):
    EDGE_CURRENT = "edge-current"
    CYCLE_PRIMAL = "cycle-primal"
    CYCLE_DUAL = "cycle-dual"


@dataclass(frozen=True)
class AffineCurrent:
    constant: int
    coefficients: tuple[int, ...]

    def evaluate(self, coordinates: tuple[object, ...]) -> object:
        if len(coordinates) < len(self.coefficients):
            raise ValueError("not enough coordinates")
        return self.constant + sum(
            coefficient * coordinates[index]
            for index, coefficient in enumerate(self.coefficients)
        )

    def polynomial(self, variable_count: int) -> SparsePolynomial:
        return SparsePolynomial.affine(
            self.constant,
            {
                index: coefficient
                for index, coefficient in enumerate(self.coefficients)
                if coefficient
            },
            variable_count,
        )


@dataclass(frozen=True)
class CurrentRecovery:
    """Recover an original current from a model-side affine current."""

    original_edge: Edge
    model_edge: Edge
    orientation_sign: int = 1
    reciprocal_scale: int | None = None


@dataclass(frozen=True)
class KirchhoffPresentation:
    rooted: RootedPlaneGraph
    kind: PresentationKind
    system: PolynomialSystem
    model_currents: Mapping[Edge, AffineCurrent]
    recovery: tuple[CurrentRecovery, ...]
    tree_score: tuple[int, int, int, int] | None = None

    @property
    def coordinate_count(self) -> int:
        return len(self.system.variables)

    def recover_currents(self, point: Mapping[str, object]) -> dict[Edge, object]:
        coordinates = tuple(point[name] for name in self.system.variables)
        model_values = {
            edge: current.evaluate(coordinates)
            for edge, current in self.model_currents.items()
        }
        recovered: dict[Edge, object] = {}
        for item in self.recovery:
            value = model_values[item.model_edge]
            if item.reciprocal_scale is not None:
                value = item.reciprocal_scale / value
            recovered[item.original_edge] = item.orientation_sign * value
        return recovered


def _incidence_sign(vertex: int, edge: Edge) -> int:
    tail, head = edge
    if vertex == tail:
        return 1
    if vertex == head:
        return -1
    raise ValueError("vertex is not incident to edge")


def _cleared_reciprocal_sum(
    signed_currents: tuple[tuple[int, SparsePolynomial], ...],
    variable_count: int,
) -> SparsePolynomial:
    currents = tuple(current for _, current in signed_currents)
    prefix = [SparsePolynomial.constant(1, variable_count)]
    for current in currents:
        prefix.append(prefix[-1] * current)
    suffix = [SparsePolynomial.constant(1, variable_count)] * (len(currents) + 1)
    for index in range(len(currents) - 1, -1, -1):
        suffix[index] = currents[index] * suffix[index + 1]

    result = SparsePolynomial.zero(variable_count)
    for index, (sign, _) in enumerate(signed_currents):
        result += (prefix[index] * suffix[index + 1]).scale(sign)
    return result


def _face_equations(
    rooted: RootedPlaneGraph,
    current_polynomials: Mapping[Edge, SparsePolynomial],
    variable_count: int,
) -> tuple[SparsePolynomial, ...]:
    graph = rooted.graph
    faces, boundary = graph.faces_and_boundary
    source, sink = rooted.root
    root_faces = {boundary[(source, sink)], boundary[(sink, source)]}
    equations: list[SparsePolynomial] = []
    for face_id, face in enumerate(faces):
        if face_id in root_faces:
            continue
        signed = tuple(
            (
                1 if dart == canonical_edge(dart) else -1,
                current_polynomials[canonical_edge(dart)],
            )
            for dart in face
        )
        equations.append(_cleared_reciprocal_sum(signed, variable_count))
    expected = rooted.graph.edge_count - rooted.graph.vertex_count
    if len(equations) != expected:
        raise ValueError("unexpected number of independent face equations")
    return tuple(equations)


def _saturation_equation(
    currents: Mapping[Edge, SparsePolynomial],
    saturation_index: int,
    variable_count: int,
) -> SparsePolynomial:
    product = polynomial_product(
        currents.values(),
        variable_count=variable_count,
    )
    saturation_variable = SparsePolynomial.variable(saturation_index, variable_count)
    return saturation_variable * product - SparsePolynomial.constant(1, variable_count)


def build_edge_current_presentation(
    rooted: RootedPlaneGraph,
) -> KirchhoffPresentation:
    """Use one current variable per non-root edge."""
    edges = rooted.nonroot_edges
    variable_names = tuple(f"x{index}" for index in range(len(edges)))
    saturation_index = len(edges)
    all_names = (*variable_names, "z_nonzero")
    variable_count = len(all_names)
    edge_index = {edge: index for index, edge in enumerate(edges)}
    current_polynomials = {
        edge: SparsePolynomial.variable(index, variable_count)
        for edge, index in edge_index.items()
    }
    current_forms = {
        edge: AffineCurrent(
            0,
            tuple(1 if index == edge_index[edge] else 0 for index in range(len(edges))),
        )
        for edge in edges
    }

    kcl: list[SparsePolynomial] = []
    for vertex in range(rooted.graph.vertex_count):
        if vertex in rooted.root:
            continue
        equation = SparsePolynomial.zero(variable_count)
        for edge in edges:
            if vertex in edge:
                equation += current_polynomials[edge].scale(
                    _incidence_sign(vertex, edge)
                )
        kcl.append(equation)

    normalization = SparsePolynomial.constant(-rooted.rectangle_count, variable_count)
    for edge in edges:
        if rooted.source in edge:
            normalization += current_polynomials[edge].scale(
                _incidence_sign(rooted.source, edge)
            )

    face_equations = _face_equations(rooted, current_polynomials, variable_count)
    saturation = _saturation_equation(
        current_polynomials, saturation_index, variable_count
    )
    recovery = tuple(CurrentRecovery(edge, edge) for edge in edges)
    return KirchhoffPresentation(
        rooted=rooted,
        kind=PresentationKind.EDGE_CURRENT,
        system=PolynomialSystem(
            all_names,
            (*kcl, *face_equations, normalization, saturation),
        ),
        model_currents=current_forms,
        recovery=recovery,
    )


def _tree_path(
    tree_adjacency: Mapping[int, tuple[int, ...]],
    source: int,
    target: int,
) -> tuple[int, ...]:
    parent: dict[int, int | None] = {source: None}
    queue = deque([source])
    while queue:
        vertex = queue.popleft()
        if vertex == target:
            break
        for neighbor in tree_adjacency[vertex]:
            if neighbor not in parent:
                parent[neighbor] = vertex
                queue.append(neighbor)
    if target not in parent:
        raise ValueError("tree does not connect the terminals")
    reversed_path: list[int] = []
    vertex: int | None = target
    while vertex is not None:
        reversed_path.append(vertex)
        vertex = parent[vertex]
    return tuple(reversed(reversed_path))


def _spanning_tree(
    rooted: RootedPlaneGraph,
    start: int,
    *,
    depth_first: bool,
    reverse: bool,
) -> tuple[frozenset[Edge], dict[int, tuple[int, ...]]]:
    graph = rooted.graph
    root_edge = canonical_edge(rooted.root)
    visited = {start}
    pending = deque([start])
    tree_edges: set[Edge] = set()
    adjacency: dict[int, list[int]] = {
        vertex: [] for vertex in range(graph.vertex_count)
    }
    while pending:
        vertex = pending.pop() if depth_first else pending.popleft()
        for neighbor in sorted(graph.rotations[vertex], reverse=reverse):
            edge = canonical_edge((vertex, neighbor))
            if edge == root_edge or neighbor in visited:
                continue
            visited.add(neighbor)
            pending.append(neighbor)
            tree_edges.add(edge)
            adjacency[vertex].append(neighbor)
            adjacency[neighbor].append(vertex)
    if len(visited) != graph.vertex_count:
        raise ValueError("root-deleted graph is disconnected")
    return frozenset(tree_edges), {
        vertex: tuple(neighbors) for vertex, neighbors in adjacency.items()
    }


def _cycle_columns(
    rooted: RootedPlaneGraph,
    tree_edges: frozenset[Edge],
    tree_adjacency: Mapping[int, tuple[int, ...]],
) -> tuple[tuple[dict[Edge, int], ...], tuple[int, int, int, int]]:
    chords = tuple(edge for edge in rooted.nonroot_edges if edge not in tree_edges)
    columns: list[dict[Edge, int]] = []
    supports: list[int] = []
    load = {edge: 0 for edge in rooted.nonroot_edges}
    for chord in chords:
        u, v = chord
        column = {chord: 1}
        path = _tree_path(tree_adjacency, v, u)
        for a, b in zip(path, path[1:], strict=False):
            edge = canonical_edge((a, b))
            column[edge] = 1 if edge == (a, b) else -1
        columns.append(column)
        supports.append(len(column))
        for edge in column:
            load[edge] += 1
    score = (
        sum(supports),
        max(supports, default=0),
        max(load.values(), default=0),
        sum(value * value for value in load.values()),
    )
    return tuple(columns), score


def _best_cycle_basis(
    rooted: RootedPlaneGraph,
) -> tuple[
    frozenset[Edge],
    Mapping[int, tuple[int, ...]],
    tuple[dict[Edge, int], ...],
    tuple[int, int, int, int],
]:
    candidates = []
    for start in range(rooted.graph.vertex_count):
        for depth_first in (False, True):
            for reverse in (False, True):
                tree_edges, adjacency = _spanning_tree(
                    rooted,
                    start,
                    depth_first=depth_first,
                    reverse=reverse,
                )
                columns, score = _cycle_columns(rooted, tree_edges, adjacency)
                candidates.append(
                    (score, start, depth_first, reverse, tree_edges, adjacency, columns)
                )
    score, _, _, _, tree_edges, adjacency, columns = min(
        candidates, key=lambda item: item[:4]
    )
    return tree_edges, adjacency, columns, score


def _build_cycle_on_model(
    original: RootedPlaneGraph,
    model: RootedPlaneGraph,
    *,
    kind: PresentationKind,
    correspondence: Mapping[Edge, tuple[Edge, int]] | None = None,
) -> KirchhoffPresentation:
    _, tree_adjacency, columns, score = _best_cycle_basis(model)
    cycle_count = len(columns)
    variable_names = tuple(f"c{index}" for index in range(cycle_count))
    saturation_index = cycle_count
    all_names = (*variable_names, "z_nonzero")
    variable_count = len(all_names)

    particular = {edge: 0 for edge in model.nonroot_edges}
    path = _tree_path(tree_adjacency, model.source, model.sink)
    for a, b in zip(path, path[1:], strict=False):
        edge = canonical_edge((a, b))
        particular[edge] = (
            model.rectangle_count if edge == (a, b) else -model.rectangle_count
        )

    forms: dict[Edge, AffineCurrent] = {}
    polynomials: dict[Edge, SparsePolynomial] = {}
    for edge in model.nonroot_edges:
        coefficients = tuple(column.get(edge, 0) for column in columns)
        form = AffineCurrent(particular[edge], coefficients)
        forms[edge] = form
        polynomials[edge] = form.polynomial(variable_count)

    face_equations = _face_equations(model, polynomials, variable_count)
    saturation = _saturation_equation(polynomials, saturation_index, variable_count)

    if correspondence is None:
        recovery = tuple(CurrentRecovery(edge, edge) for edge in original.nonroot_edges)
    else:
        recovery = tuple(
            CurrentRecovery(
                original_edge=edge,
                model_edge=correspondence[edge][0],
                orientation_sign=correspondence[edge][1],
                reciprocal_scale=original.rectangle_count,
            )
            for edge in original.nonroot_edges
        )

    return KirchhoffPresentation(
        rooted=original,
        kind=kind,
        system=PolynomialSystem(all_names, (*face_equations, saturation)),
        model_currents=forms,
        recovery=recovery,
        tree_score=score,
    )


def build_cycle_presentation(
    rooted: RootedPlaneGraph,
    *,
    dual: bool = False,
) -> KirchhoffPresentation:
    if not dual:
        return _build_cycle_on_model(
            rooted,
            rooted,
            kind=PresentationKind.CYCLE_PRIMAL,
        )
    dual_rooted, correspondence = rooted.graph.rooted_dual(rooted.root)
    return _build_cycle_on_model(
        rooted,
        dual_rooted,
        kind=PresentationKind.CYCLE_DUAL,
        correspondence=correspondence,
    )


def build_adaptive_cycle_presentation(
    rooted: RootedPlaneGraph,
) -> KirchhoffPresentation:
    """Use cycle coordinates on whichever of ``G`` and ``G*`` is smaller."""
    return build_cycle_presentation(
        rooted,
        dual=rooted.graph.vertex_count < rooted.graph.face_count,
    )


def congruence_violations(
    currents: Mapping[Edge, object],
    rectangle_count: int,
) -> tuple[tuple[Edge, Edge, str], ...]:
    """Return all pairs representing congruent rectangles after square scaling."""
    items = tuple(sorted(currents.items()))
    violations: list[tuple[Edge, Edge, str]] = []
    for left_index, (left_edge, left) in enumerate(items):
        for right_edge, right in items[left_index + 1 :]:
            if left**2 == right**2:
                violations.append((left_edge, right_edge, "parallel"))
            elif left**2 * right**2 == rectangle_count**2:
                violations.append((left_edge, right_edge, "rotated"))
    return tuple(violations)
