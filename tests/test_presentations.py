from fractions import Fraction

from agentic_blanche.graph import RootedPlaneGraph
from agentic_blanche.presentations import (
    PresentationKind,
    build_adaptive_cycle_presentation,
    build_bilinear_presentation,
    build_cycle_presentation,
    build_edge_current_presentation,
    congruence_violations,
    verifies_kirchhoff_currents,
    verifies_kirchhoff_currents_mod,
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
    modular_point = {"c0": 25, "c1": 20, "z_nonzero": 65}
    expected = {
        (0, 2): 25,
        (0, 3): 81,
        (1, 2): 20,
        (1, 3): 76,
        (2, 3): 45,
    }
    assert presentation.verifies(modular_point, modulus=101)
    assert presentation.recover_currents_mod(modular_point, 101) == expected


def test_congruence_filter():
    currents = {
        (0, 1): Fraction(2),
        (0, 2): Fraction(-2),
        (1, 2): Fraction(5, 2),
    }
    violations = congruence_violations(currents, 5)
    assert ((0, 1), (0, 2), "parallel") in violations
    assert ((0, 1), (1, 2), "rotated") in violations


def test_bilinear_presentation_is_square_sparse_quadratic(
    rooted_tetrahedron: RootedPlaneGraph,
):
    presentation = build_bilinear_presentation(rooted_tetrahedron)
    assert presentation.kind == PresentationKind.BILINEAR
    assert len(presentation.system.variables) == 7
    assert len(presentation.system.polynomials) == 7
    assert max(poly.degree for poly in presentation.system.polynomials) == 2
    assert presentation.system.maximum_term_count <= 3


def test_modular_congruence_filter(rooted_tetrahedron: RootedPlaneGraph):
    currents = {
        (0, 1): 2,
        (0, 2): 99,
        (1, 2): 48,
    }
    violations = congruence_violations(currents, 5, modulus=101)
    assert ((0, 1), (0, 2), "parallel") in violations
    assert ((0, 1), (1, 2), "rotated") in violations
    tetrahedron_currents = {
        (0, 2): 25,
        (0, 3): 81,
        (1, 2): 20,
        (1, 3): 76,
        (2, 3): 45,
    }
    assert verifies_kirchhoff_currents_mod(
        rooted_tetrahedron,
        tetrahedron_currents,
        101,
    )


def test_original_kirchhoff_verifier_rejects_arbitrary_currents(
    rooted_tetrahedron: RootedPlaneGraph,
):
    currents = {edge: Fraction(1) for edge in rooted_tetrahedron.nonroot_edges}
    assert not verifies_kirchhoff_currents(rooted_tetrahedron, currents)
