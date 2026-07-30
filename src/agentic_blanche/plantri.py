"""Streaming interface to plantri's polyhedral graph generator."""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph
from agentic_blanche.symmetry import (
    canonical_certificate,
    edge_orbit_representatives,
)


def parse_plantri_ascii(line: str) -> PlaneGraph:
    """Parse one graph from plantri's ``-a`` ASCII format."""
    vertex_text, rotations_text = line.split()
    vertex_count = int(vertex_text)
    rotations = tuple(
        tuple(ord(character) - ord("a") for character in neighborhood)
        for neighborhood in rotations_text.split(",")
    )
    if len(rotations) != vertex_count:
        raise ValueError("plantri line has the wrong number of vertices")
    return PlaneGraph(rotations)


@dataclass(frozen=True)
class Plantri:
    executable: str = "plantri"

    def _path(self) -> str:
        path = shutil.which(self.executable)
        if path is None:
            raise RuntimeError(f"{self.executable!r} is not installed")
        return path

    def graphs(self, vertices: int, edges: int | None = None) -> Iterator[PlaneGraph]:
        command = [self._path(), "-p", "-c3", "-a", str(vertices)]
        if edges is not None:
            command.append(f"-e{edges}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                line = line.strip()
                if line:
                    yield parse_plantri_ascii(line)
        finally:
            process.stdout.close()
        return_code = process.wait()
        if return_code:
            assert process.stderr is not None
            error = process.stderr.read()
            raise RuntimeError(f"plantri failed with exit code {return_code}:\n{error}")

    def graphs_with_edge_count(
        self,
        edges: int,
        *,
        quotient_duality: bool = True,
    ) -> Iterator[PlaneGraph]:
        """Stream polyhedral graphs with exactly ``edges`` edges.

        When ``quotient_duality`` is true, only the half with ``V <= F`` is
        generated. The self-dual midpoint bucket is filtered with nauty
        certificates in linear expected time.
        """
        minimum_vertices = math.ceil(edges / 3 + 2)
        maximum_vertices = math.floor(2 * edges / 3)
        midpoint = (edges + 2) / 2
        for vertices in range(minimum_vertices, maximum_vertices + 1):
            if quotient_duality and vertices > midpoint:
                continue
            if quotient_duality and vertices == midpoint:
                dual_certificates: set[bytes] = set()
                for graph in self.graphs(vertices, edges):
                    certificate = canonical_certificate(graph)
                    if certificate in dual_certificates:
                        continue
                    dual_certificates.add(canonical_certificate(graph.dual()))
                    yield graph
            else:
                yield from self.graphs(vertices, edges)

    def rooted_graphs(
        self,
        edges: int,
        *,
        quotient_duality: bool = True,
    ) -> Iterator[RootedPlaneGraph]:
        for graph in self.graphs_with_edge_count(
            edges, quotient_duality=quotient_duality
        ):
            for root in edge_orbit_representatives(graph):
                yield RootedPlaneGraph(graph, root)
