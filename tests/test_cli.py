from pathlib import Path

from agentic_blanche import cli
from agentic_blanche.storage import TaskStatus


def _empty_counts() -> dict[str, int]:
    return {status.value: 0 for status in TaskStatus}


def test_search_parser_has_practical_defaults():
    args = cli._parser().parse_args(["search", "7", "11"])

    assert (args.min_edges, args.max_edges) == (7, 11)
    assert args.sieve_mode == "heuristic-prune"
    assert args.presentation == "bilinear"
    assert args.prime_count == 9
    assert args.modular_timeout == 1
    assert args.exact_timeout == 30
    assert args.results_dir == Path("results")
    assert args.workers >= 1


def test_search_visits_inclusive_edge_range(monkeypatch, capsys):
    visited = []

    def fake_run_edge(args, edges):
        visited.append(edges)
        return cli.EdgeSummary(
            edges=edges,
            tasks=0,
            queued=0,
            requeued=0,
            counts=_empty_counts(),
            rational_points=0,
            candidates=0,
            seconds=0,
            database=Path(f"results/E{edges}.sqlite"),
        )

    monkeypatch.setattr(cli, "_run_edge", fake_run_edge)

    assert cli.main(["search", "7", "11"]) == 0
    assert visited == [7, 8, 9, 10, 11]
    output = capsys.readouterr().out
    assert "inclusive edge range 7–11" in output
    assert "No rational Mondrian candidates were found." in output


def test_search_rejects_reversed_range(capsys):
    assert cli.main(["search", "11", "7"]) == 2
    assert "MAX_EDGES must be greater than or equal" in capsys.readouterr().err


def test_empty_edge_layer_writes_and_checks_database(tmp_path, monkeypatch):
    class EmptyPlantri:
        def __init__(self, executable):
            self.executable = executable

        def rooted_graphs(self, edges, *, quotient_duality):
            assert edges == 7
            assert quotient_duality
            return iter(())

    monkeypatch.setattr(cli, "Plantri", EmptyPlantri)
    args = cli._parser().parse_args(
        ["search", "7", "7", "--results-dir", str(tmp_path)]
    )

    summary = cli._run_edge(args, 7)

    assert summary.tasks == 0
    assert summary.database == tmp_path / "E7.sqlite"
    assert summary.database.exists()
    assert (tmp_path / "E7.manifest.json").exists()
