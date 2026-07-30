from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph


def test_tetrahedron_faces_and_dual(tetrahedron: PlaneGraph):
    assert tetrahedron.vertex_count == 4
    assert tetrahedron.edge_count == 6
    assert tetrahedron.face_count == 4
    dual = tetrahedron.dual()
    assert dual.vertex_count == 4
    assert dual.edge_count == 6
    assert dual.face_count == 4


def test_rooted_dual_preserves_rectangle_count(tetrahedron: PlaneGraph):
    rooted = RootedPlaneGraph(tetrahedron, (0, 1))
    dual, correspondence = tetrahedron.rooted_dual(rooted.root)
    assert dual.rectangle_count == rooted.rectangle_count
    assert set(correspondence) == set(tetrahedron.edges)
    assert len(set(item[0] for item in correspondence.values())) == 6


def test_rejects_non_symmetric_adjacency():
    try:
        PlaneGraph.from_adjacency({0: [1], 1: []})
    except ValueError as error:
        assert "symmetric" in str(error)
    else:
        raise AssertionError("invalid graph was accepted")
