"""Nauty-backed graph certificates and edge orbits."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pynauty

from agentic_blanche.graph import Edge, PlaneGraph, canonical_edge


def _nauty_graph(graph: PlaneGraph) -> pynauty.Graph:
    return pynauty.Graph(
        graph.vertex_count,
        adjacency_dict=graph.as_adjacency(),
    )


def _rooted_nauty_graph(graph: PlaneGraph, root: Edge) -> pynauty.Graph:
    source, sink = root
    if canonical_edge(root) not in graph.edges:
        raise ValueError("root edge is not in the graph")
    remaining = set(range(graph.vertex_count)) - {source, sink}
    return pynauty.Graph(
        graph.vertex_count,
        adjacency_dict=graph.as_adjacency(),
        vertex_coloring=[{source}, {sink}, remaining],
    )


def canonical_certificate(graph: PlaneGraph) -> bytes:
    return bytes(pynauty.certificate(_nauty_graph(graph)))


def rooted_certificate(graph: PlaneGraph, root: Edge) -> bytes:
    """Return a label-independent certificate for an oriented rooted graph."""
    return bytes(pynauty.certificate(_rooted_nauty_graph(graph, root)))


def graph_id(graph: PlaneGraph) -> str:
    return hashlib.sha256(canonical_certificate(graph)).hexdigest()[:20]


def automorphism_generators(graph: PlaneGraph) -> tuple[tuple[int, ...], ...]:
    generators = pynauty.autgrp(_nauty_graph(graph))[0]
    return tuple(tuple(permutation) for permutation in generators)


def edge_orbits(graph: PlaneGraph) -> Iterator[frozenset[Edge]]:
    generators = automorphism_generators(graph)
    visited: set[Edge] = set()
    for seed in graph.edges:
        if seed in visited:
            continue
        orbit: set[Edge] = {seed}
        stack = [seed]
        visited.add(seed)
        while stack:
            u, v = stack.pop()
            for permutation in generators:
                image = canonical_edge((permutation[u], permutation[v]))
                if image not in visited:
                    visited.add(image)
                    orbit.add(image)
                    stack.append(image)
        yield frozenset(orbit)


def edge_orbit_representatives(graph: PlaneGraph) -> tuple[Edge, ...]:
    return tuple(sorted(min(orbit) for orbit in edge_orbits(graph)))


def rooted_graph_id(graph: PlaneGraph, root: Edge) -> str:
    return hashlib.sha256(rooted_certificate(graph, root)).hexdigest()[:24]
