from fractions import Fraction

from agentic_blanche.graph import RootedPlaneGraph
from agentic_blanche.presentations import (
    PresentationKind,
    build_adaptive_cycle_presentation,
    build_cycle_presentation,
    build_edge_current_presentation,
    congruence_violations,
)


def _divergence(rooted, currents, vertex):
    total = 0
    for edge, value in currents.items():
        if vertex == edge[0]:
            total += value
        elif vertex == edge[1]:
            total -= value
    return total


def test_edge_current_system_size(rooted_tetrahedron: RootedPlaneGraph):
    presentation = build_edge_current_presentation(rooted_tetrahedron)
    assert presentation.kind == PresentationKind.EDGE_CURRENT
    assert presentation.coordinate_count == 6
    assert len(presentation.system.polynomials) == 6


def test_cycle_coordinates_eliminate_kcl(rooted_tetrahedron: RootedPlaneGraph):
    presentation = build_cycle_presentation(rooted_tetrahedron)
    assert presentation.coordinate_count == 3
    point = {
        name: Fraction(index + 2)
        for index, name in enumerate(presentation.system.variables)
    }
    currents = presentation.recover_currents(point)
    assert _divergence(rooted_tetrahedron, currents, 2) == 0
    assert _divergence(rooted_tetrahedron, currents, 3) == 0
    assert (
        _divergence(rooted_tetrahedron, currents, rooted_tetrahedron.source)
        == rooted_tetrahedron.rectangle_count
    )


def test_adaptive_cycle_uses_expected_dimension(
    rooted_tetrahedron: RootedPlaneGraph,
):
    presentation = build_adaptive_cycle_presentation(rooted_tetrahedron)
    expected = min(
        rooted_tetrahedron.graph.vertex_count - 2,
        rooted_tetrahedron.graph.face_count - 2,
    )
    assert presentation.coordinate_count == expected + 1


def test_dual_cycle_recovery_is_rational(
    rooted_tetrahedron: RootedPlaneGraph,
):
    presentation = build_cycle_presentation(rooted_tetrahedron, dual=True)
    point = {
        name: Fraction(index + 2)
        for index, name in enumerate(presentation.system.variables)
    }
    currents = presentation.recover_currents(point)
    assert set(currents) == set(rooted_tetrahedron.nonroot_edges)
    assert all(isinstance(value, Fraction) for value in currents.values())


def test_congruence_filter():
    currents = {
        (0, 1): Fraction(2),
        (0, 2): Fraction(-2),
        (1, 2): Fraction(5, 2),
    }
    violations = congruence_violations(currents, 5)
    assert ((0, 1), (0, 2), "parallel") in violations
    assert ((0, 1), (1, 2), "rotated") in violations
