from dataclasses import dataclass

from agentic_blanche.graph import RootedPlaneGraph
from agentic_blanche.msolve import (
    ExactSolve,
    FiniteRUR,
    FiniteSolve,
    SolveTiming,
)
from agentic_blanche.workflow import (
    PresentationChoice,
    SearchConfig,
    SearchWorkflow,
    SieveDisposition,
    SieveMode,
)


@dataclass
class FakeSolver:
    exact_calls: int = 0

    def finite(self, system, prime, *, timeout=None):
        return FiniteSolve(
            FiniteRUR(
                prime=prime,
                variables=system.variables,
                linear_form=(0,) * len(system.variables),
                degree=2,
                polynomial=(1, 0, 1),
                denominator=(1,),
                parametrizations=(),
                factor_degrees=(),
                unfactored_degree=2,
                squarefree=True,
                linear_roots=(),
            ),
            SolveTiming(0.01),
        )

    def exact(self, system, *, threads=None, timeout=None):
        self.exact_calls += 1
        return ExactSolve(None, SolveTiming(0.1))


def test_report_mode_never_prunes(rooted_tetrahedron: RootedPlaneGraph):
    solver = FakeSolver()
    workflow = SearchWorkflow(
        solver,
        SearchConfig(
            primes=(101,),
            sieve_mode=SieveMode.REPORT,
            presentation=PresentationChoice.EDGE,
            exact_threads=1,
        ),
    )
    result = workflow.process(rooted_tetrahedron)
    assert result.sieve_disposition == SieveDisposition.HEURISTIC_REJECTION
    assert not result.pruned
    assert solver.exact_calls == 1
    assert not result.rational_solutions


def test_heuristic_mode_prunes(rooted_tetrahedron: RootedPlaneGraph):
    solver = FakeSolver()
    workflow = SearchWorkflow(
        solver,
        SearchConfig(
            primes=(101,),
            sieve_mode=SieveMode.HEURISTIC_PRUNE,
            presentation=PresentationChoice.EDGE,
            exact_threads=1,
        ),
    )
    result = workflow.process(rooted_tetrahedron)
    assert result.pruned
    assert solver.exact_calls == 0


def test_certified_mode_does_not_trust_uncertified_prime(
    rooted_tetrahedron: RootedPlaneGraph,
):
    solver = FakeSolver()
    workflow = SearchWorkflow(
        solver,
        SearchConfig(
            primes=(101,),
            sieve_mode=SieveMode.CERTIFIED_PRUNE,
            presentation=PresentationChoice.EDGE,
            exact_threads=1,
        ),
    )
    result = workflow.process(rooted_tetrahedron)
    assert not result.pruned
    assert solver.exact_calls == 1
