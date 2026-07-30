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


def canonical_certificate(graph: PlaneGraph) -> bytes:
    return bytes(pynauty.certificate(_nauty_graph(graph)))


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
    base = graph_id(graph)
    edge = canonical_edge(root)
    return f"{base}:{edge[0]}-{edge[1]}:{root[0]}>{root[1]}"
