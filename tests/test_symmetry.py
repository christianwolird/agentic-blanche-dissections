from agentic_blanche.graph import PlaneGraph
from agentic_blanche.symmetry import rooted_graph_id


def _relabel(graph, root, permutation):
    rotations = [()] * graph.vertex_count
    for vertex, neighbors in enumerate(graph.rotations):
        rotations[permutation[vertex]] = tuple(permutation[n] for n in neighbors)
    return PlaneGraph(tuple(rotations)), tuple(permutation[v] for v in root)


def _wheel5():
    return PlaneGraph.from_adjacency(
        {
            0: [1, 2, 3, 4],
            1: [0, 2, 4],
            2: [0, 3, 1],
            3: [0, 4, 2],
            4: [0, 1, 3],
        }
    )


def test_rooted_id_is_independent_of_vertex_labels():
    graph = _wheel5()
    relabeled, root = _relabel(graph, (0, 1), (3, 1, 4, 0, 2))
    assert rooted_graph_id(graph, (0, 1)) == rooted_graph_id(relabeled, root)


def test_rooted_id_distinguishes_edge_orbits():
    graph = _wheel5()
    assert rooted_graph_id(graph, (0, 1)) != rooted_graph_id(graph, (1, 2))
