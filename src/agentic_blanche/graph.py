"""Embedded planar graphs and rooted planar duality."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cached_property

Edge = tuple[int, int]
Dart = tuple[int, int]


def canonical_edge(edge: Edge) -> Edge:
    """Return an undirected edge with its smaller endpoint first."""
    u, v = edge
    if u == v:
        raise ValueError("loops are not allowed")
    return (u, v) if u < v else (v, u)


@dataclass(frozen=True)
class PlaneGraph:
    """A simple graph with a fixed rotation system.

    ``rotations[v]`` lists the neighbors of vertex ``v`` clockwise. Vertices
    must be labeled consecutively from zero.
    """

    rotations: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        vertex_count = len(self.rotations)
        for vertex, neighbors in enumerate(self.rotations):
            if len(neighbors) != len(set(neighbors)):
                raise ValueError(f"duplicate neighbor at vertex {vertex}")
            for neighbor in neighbors:
                if not 0 <= neighbor < vertex_count:
                    raise ValueError("vertices must be labeled 0 through V-1")
                if neighbor == vertex:
                    raise ValueError("loops are not allowed")
                if vertex not in self.rotations[neighbor]:
                    raise ValueError("adjacency must be symmetric")

    @classmethod
    def from_adjacency(cls, adjacency: dict[int, Iterable[int]]) -> PlaneGraph:
        vertices = sorted(adjacency)
        if vertices != list(range(len(vertices))):
            raise ValueError("vertices must be labeled consecutively from zero")
        return cls(tuple(tuple(adjacency[v]) for v in vertices))

    @property
    def vertex_count(self) -> int:
        return len(self.rotations)

    @cached_property
    def edges(self) -> tuple[Edge, ...]:
        return tuple(
            sorted(
                {
                    canonical_edge((u, v))
                    for u, neighbors in enumerate(self.rotations)
                    for v in neighbors
                }
            )
        )

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @cached_property
    def faces_and_boundary(
        self,
    ) -> tuple[tuple[tuple[Dart, ...], ...], dict[Dart, int]]:
        """Trace all faces and map each directed edge to its left face."""
        neighbor_index = tuple(
            {neighbor: index for index, neighbor in enumerate(neighbors)}
            for neighbors in self.rotations
        )
        boundary: dict[Dart, int] = {}
        faces: list[tuple[Dart, ...]] = []

        def next_dart(dart: Dart) -> Dart:
            u, v = dart
            neighbors = self.rotations[v]
            index = neighbor_index[v][u]
            return (v, neighbors[(index - 1) % len(neighbors)])

        for start in self.darts():
            if start in boundary:
                continue
            face_id = len(faces)
            face: list[Dart] = []
            dart = start
            while dart not in boundary:
                boundary[dart] = face_id
                face.append(dart)
                dart = next_dart(dart)
            if dart != start:
                raise ValueError("rotation system is not a cellular embedding")
            faces.append(tuple(face))
        return tuple(faces), boundary

    @property
    def faces(self) -> tuple[tuple[Dart, ...], ...]:
        return self.faces_and_boundary[0]

    @property
    def face_count(self) -> int:
        return len(self.faces)

    def darts(self) -> Iterator[Dart]:
        for u, neighbors in enumerate(self.rotations):
            for v in neighbors:
                yield (u, v)

    def dual_with_correspondence(
        self,
    ) -> tuple[PlaneGraph, dict[Edge, tuple[Edge, int]]]:
        """Return the planar dual and the oriented primal-to-dual edge map.

        The integer sign records whether the canonical dual orientation agrees
        with the direction from the left face of the canonical primal dart to
        its right face.
        """
        faces, boundary = self.faces_and_boundary
        dual_rotations: list[list[int]] = [[] for _ in faces]
        for face_id, face in enumerate(faces):
            for u, v in face:
                dual_rotations[face_id].append(boundary[(v, u)])

        dual = PlaneGraph(tuple(tuple(row) for row in dual_rotations))
        correspondence: dict[Edge, tuple[Edge, int]] = {}
        for edge in self.edges:
            u, v = edge
            left = boundary[(u, v)]
            right = boundary[(v, u)]
            dual_edge = canonical_edge((left, right))
            sign = 1 if dual_edge == (left, right) else -1
            correspondence[edge] = (dual_edge, sign)
        return dual, correspondence

    def dual(self) -> PlaneGraph:
        return self.dual_with_correspondence()[0]

    def rooted_dual(
        self, root: Edge
    ) -> tuple[RootedPlaneGraph, dict[Edge, tuple[Edge, int]]]:
        source, sink = root
        edge = canonical_edge(root)
        if edge not in self.edges:
            raise ValueError("root edge is not in the graph")
        _, boundary = self.faces_and_boundary
        dual, correspondence = self.dual_with_correspondence()
        dual_root = (boundary[(source, sink)], boundary[(sink, source)])
        return RootedPlaneGraph(dual, dual_root), correspondence

    def as_adjacency(self) -> dict[int, list[int]]:
        return {
            vertex: list(neighbors) for vertex, neighbors in enumerate(self.rotations)
        }


@dataclass(frozen=True)
class RootedPlaneGraph:
    """A plane graph with an oriented distinguished edge."""

    graph: PlaneGraph
    root: Edge

    def __post_init__(self) -> None:
        if canonical_edge(self.root) not in self.graph.edges:
            raise ValueError("root edge is not in the graph")

    @property
    def source(self) -> int:
        return self.root[0]

    @property
    def sink(self) -> int:
        return self.root[1]

    @property
    def rectangle_count(self) -> int:
        return self.graph.edge_count - 1

    @property
    def nonroot_edges(self) -> tuple[Edge, ...]:
        root = canonical_edge(self.root)
        return tuple(edge for edge in self.graph.edges if edge != root)
