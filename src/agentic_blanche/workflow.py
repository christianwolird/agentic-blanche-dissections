"""Staged modular and exact search workflow."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import sympy

from agentic_blanche.graph import Edge, RootedPlaneGraph
from agentic_blanche.msolve import ExactSolve, FiniteSolve
from agentic_blanche.presentations import (
    KirchhoffPresentation,
    PresentationKind,
    build_adaptive_cycle_presentation,
    build_edge_current_presentation,
    congruence_violations,
)
from agentic_blanche.symmetry import rooted_graph_id


class SolverBackend(Protocol):
    def finite(self, system: object, prime: int) -> FiniteSolve: ...

    def exact(self, system: object, *, threads: int | None = None) -> ExactSolve: ...


class SieveMode(StrEnum):
    OFF = "off"
    REPORT = "report"
    HEURISTIC_PRUNE = "heuristic-prune"
    CERTIFIED_PRUNE = "certified-prune"


class PresentationChoice(StrEnum):
    AUTO = "auto"
    EDGE = "edge"
    CYCLE = "cycle"


class SieveDisposition(StrEnum):
    NOT_RUN = "not-run"
    SURVIVES = "survives"
    HEURISTIC_REJECTION = "heuristic-rejection"
    CERTIFIED_REJECTION = "certified-rejection"


class GoodReductionOracle(Protocol):
    """Supply the theorem-dependent part of a rigorous modular rejection."""

    def expected_degree(self, rooted: RootedPlaneGraph) -> int | None: ...

    def is_good_prime(
        self,
        rooted: RootedPlaneGraph,
        prime: int,
        degree: int,
    ) -> bool: ...


@dataclass(frozen=True)
class NoGoodReductionCertificate:
    def expected_degree(self, rooted: RootedPlaneGraph) -> int | None:
        return None

    def is_good_prime(
        self,
        rooted: RootedPlaneGraph,
        prime: int,
        degree: int,
    ) -> bool:
        return False


def descending_primes(count: int, start: int = 65_521) -> tuple[int, ...]:
    if count < 0:
        raise ValueError("prime count must be nonnegative")
    if count == 0:
        return ()
    primes = [int(sympy.prevprime(start + 1))]
    while len(primes) < count:
        primes.append(int(sympy.prevprime(primes[-1])))
    return tuple(primes)


@dataclass(frozen=True)
class SearchConfig:
    primes: tuple[int, ...] = field(default_factory=lambda: descending_primes(9))
    sieve_mode: SieveMode = SieveMode.REPORT
    presentation: PresentationChoice = PresentationChoice.AUTO
    pilot_presentations: bool = True
    exact_threads: int = 8

    def __post_init__(self) -> None:
        if self.exact_threads < 1:
            raise ValueError("exact_threads must be positive")
        if any(not sympy.isprime(prime) for prime in self.primes):
            raise ValueError("all modular characteristics must be prime")


@dataclass(frozen=True)
class ModularProbe:
    prime: int
    seconds: float
    degree: int
    factor_degrees: tuple[int, ...]
    squarefree: bool
    linear_factor_count: int
    expected_degree: int | None
    presentation: str

    @property
    def has_full_expected_degree(self) -> bool | None:
        if self.expected_degree is None:
            return None
        return self.degree == self.expected_degree

    @property
    def has_no_finite_field_point(self) -> bool:
        return self.linear_factor_count == 0


@dataclass(frozen=True)
class RationalSolution:
    coordinates: Mapping[str, Fraction]
    currents: Mapping[Edge, Fraction]
    violations: tuple[tuple[Edge, Edge, str], ...]

    @property
    def is_mondrian_candidate(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class SearchResult:
    task_id: str
    rooted: RootedPlaneGraph
    presentation: PresentationKind
    probes: tuple[ModularProbe, ...]
    sieve_disposition: SieveDisposition
    pruned: bool
    exact_seconds: float | None
    exact_degree: int | None
    rational_solutions: tuple[RationalSolution, ...]

    @property
    def mondrian_candidates(self) -> tuple[RationalSolution, ...]:
        return tuple(
            solution
            for solution in self.rational_solutions
            if solution.is_mondrian_candidate
        )

    def to_dict(self) -> dict[str, object]:
        def fraction(value: object) -> object:
            if isinstance(value, Fraction):
                return {"numerator": value.numerator, "denominator": value.denominator}
            return value

        return {
            "task_id": self.task_id,
            "graph": self.rooted.graph.as_adjacency(),
            "root": list(self.rooted.root),
            "edges": self.rooted.graph.edge_count,
            "vertices": self.rooted.graph.vertex_count,
            "faces": self.rooted.graph.face_count,
            "presentation": self.presentation.value,
            "probes": [
                {
                    "prime": probe.prime,
                    "seconds": probe.seconds,
                    "degree": probe.degree,
                    "factor_degrees": list(probe.factor_degrees),
                    "squarefree": probe.squarefree,
                    "linear_factor_count": probe.linear_factor_count,
                    "expected_degree": probe.expected_degree,
                }
                for probe in self.probes
            ],
            "sieve_disposition": self.sieve_disposition.value,
            "pruned": self.pruned,
            "exact_seconds": self.exact_seconds,
            "exact_degree": self.exact_degree,
            "rational_solutions": [
                {
                    "coordinates": {
                        name: fraction(value)
                        for name, value in solution.coordinates.items()
                    },
                    "currents": {
                        f"{edge[0]}-{edge[1]}": fraction(value)
                        for edge, value in solution.currents.items()
                    },
                    "violations": [
                        [list(left), list(right), kind]
                        for left, right, kind in solution.violations
                    ],
                    "mondrian_candidate": solution.is_mondrian_candidate,
                }
                for solution in self.rational_solutions
            ],
        }


@dataclass
class SearchWorkflow:
    solver: SolverBackend
    config: SearchConfig = field(default_factory=SearchConfig)
    good_reduction: GoodReductionOracle = field(
        default_factory=NoGoodReductionCertificate
    )

    def _presentations(
        self, rooted: RootedPlaneGraph
    ) -> tuple[KirchhoffPresentation, ...]:
        edge = build_edge_current_presentation(rooted)
        cycle = build_adaptive_cycle_presentation(rooted)
        if self.config.presentation == PresentationChoice.EDGE:
            return (edge,)
        if self.config.presentation == PresentationChoice.CYCLE:
            return (cycle,)
        return (edge, cycle)

    def _probe(
        self,
        presentation: KirchhoffPresentation,
        prime: int,
        expected_degree: int | None,
    ) -> ModularProbe:
        solve = self.solver.finite(presentation.system, prime)
        if solve.rur is None:
            degree = 0
            factors: tuple[int, ...] = ()
            squarefree = True
            linear_count = 0
        else:
            degree = solve.rur.degree
            factors = solve.rur.factor_degrees
            squarefree = solve.rur.squarefree
            linear_count = solve.rur.linear_factor_count
        return ModularProbe(
            prime=prime,
            seconds=solve.timing.seconds,
            degree=degree,
            factor_degrees=factors,
            squarefree=squarefree,
            linear_factor_count=linear_count,
            expected_degree=expected_degree,
            presentation=presentation.kind.value,
        )

    def _choose_presentation(
        self,
        presentations: tuple[KirchhoffPresentation, ...],
        expected_degree: int | None,
    ) -> tuple[KirchhoffPresentation, tuple[ModularProbe, ...]]:
        if (
            len(presentations) == 1
            or not self.config.pilot_presentations
            or not self.config.primes
            or self.config.sieve_mode == SieveMode.OFF
        ):
            if len(presentations) == 1:
                return presentations[0], ()
            cycle = presentations[1]
            edge = presentations[0]
            chosen = cycle if cycle.system.term_count < edge.system.term_count else edge
            return chosen, ()

        prime = self.config.primes[0]
        pilots = tuple(
            self._probe(presentation, prime, expected_degree)
            for presentation in presentations
        )
        fastest_index = min(range(len(pilots)), key=lambda index: pilots[index].seconds)
        return presentations[fastest_index], (pilots[fastest_index],)

    def _sieve(
        self,
        rooted: RootedPlaneGraph,
        presentation: KirchhoffPresentation,
        initial: tuple[ModularProbe, ...],
        expected_degree: int | None,
    ) -> tuple[
        tuple[ModularProbe, ...],
        SieveDisposition,
        bool,
    ]:
        if self.config.sieve_mode == SieveMode.OFF:
            return (), SieveDisposition.NOT_RUN, False

        probes = list(initial)
        used_primes = {probe.prime for probe in probes}
        remaining = (prime for prime in self.config.primes if prime not in used_primes)
        while True:
            if probes:
                probe = probes[-1]
                full_degree = probe.has_full_expected_degree
                potential_rejection = (
                    probe.squarefree
                    and probe.has_no_finite_field_point
                    and full_degree is not False
                )
                if potential_rejection:
                    certified = (
                        full_degree is True
                        and self.good_reduction.is_good_prime(
                            rooted, probe.prime, probe.degree
                        )
                    )
                    disposition = (
                        SieveDisposition.CERTIFIED_REJECTION
                        if certified
                        else SieveDisposition.HEURISTIC_REJECTION
                    )
                    pruned = self.config.sieve_mode == SieveMode.HEURISTIC_PRUNE or (
                        self.config.sieve_mode == SieveMode.CERTIFIED_PRUNE
                        and certified
                    )
                    return tuple(probes), disposition, pruned
            try:
                prime = next(remaining)
            except StopIteration:
                return tuple(probes), SieveDisposition.SURVIVES, False
            probes.append(self._probe(presentation, prime, expected_degree))

    def process(self, rooted: RootedPlaneGraph) -> SearchResult:
        expected_degree = self.good_reduction.expected_degree(rooted)
        presentations = self._presentations(rooted)
        presentation, pilot = self._choose_presentation(presentations, expected_degree)
        probes, disposition, pruned = self._sieve(
            rooted,
            presentation,
            pilot,
            expected_degree,
        )
        task_id = rooted_graph_id(rooted.graph, rooted.root)
        if pruned:
            return SearchResult(
                task_id=task_id,
                rooted=rooted,
                presentation=presentation.kind,
                probes=probes,
                sieve_disposition=disposition,
                pruned=True,
                exact_seconds=None,
                exact_degree=None,
                rational_solutions=(),
            )

        exact = self.solver.exact(
            presentation.system,
            threads=self.config.exact_threads,
        )
        if exact.rur is None:
            degree = 0
            points: tuple[Mapping[str, Fraction], ...] = ()
        else:
            degree = exact.rur.degree
            points = exact.rur.rational_points()

        solutions: list[RationalSolution] = []
        for point in points:
            currents = presentation.recover_currents(point)
            violations = congruence_violations(currents, rooted.rectangle_count)
            solutions.append(RationalSolution(point, currents, violations))
        return SearchResult(
            task_id=task_id,
            rooted=rooted,
            presentation=presentation.kind,
            probes=probes,
            sieve_disposition=disposition,
            pruned=False,
            exact_seconds=exact.timing.seconds,
            exact_degree=degree,
            rational_solutions=tuple(solutions),
        )

    def run(
        self,
        rooted_graphs: Iterable[RootedPlaneGraph],
        *,
        checkpoint: JSONLCheckpoint | None = None,
        limit: int | None = None,
    ) -> Iterator[SearchResult]:
        seen = checkpoint.seen_ids() if checkpoint else set()
        completed = 0
        for rooted in rooted_graphs:
            task_id = rooted_graph_id(rooted.graph, rooted.root)
            if task_id in seen:
                continue
            result = self.process(rooted)
            if checkpoint:
                checkpoint.append(result)
            yield result
            completed += 1
            if limit is not None and completed >= limit:
                break


@dataclass(frozen=True)
class JSONLCheckpoint:
    path: Path

    def seen_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        seen: set[str] = set()
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    seen.add(json.loads(line)["task_id"])
        return seen

    def append(self, result: SearchResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result.to_dict(), sort_keys=True))
            stream.write("\n")
