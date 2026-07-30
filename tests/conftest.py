import pytest

from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph


@pytest.fixture
def tetrahedron() -> PlaneGraph:
    return PlaneGraph.from_adjacency(
        {
            0: [1, 2, 3],
            1: [0, 3, 2],
            2: [0, 1, 3],
            3: [0, 2, 1],
        }
    )


@pytest.fixture
def rooted_tetrahedron(tetrahedron: PlaneGraph) -> RootedPlaneGraph:
    return RootedPlaneGraph(tetrahedron, (0, 1))
