import sqlite3

from agentic_blanche.presentations import PresentationKind
from agentic_blanche.storage import SQLiteTaskStore, TaskStatus
from agentic_blanche.symmetry import rooted_graph_id
from agentic_blanche.workflow import SearchResult, SieveDisposition


def test_sqlite_store_uses_wal_and_deduplicates(tmp_path, rooted_tetrahedron):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    assert store.enqueue(rooted_tetrahedron)
    assert not store.enqueue(rooted_tetrahedron)
    task = store.claim("worker-1")
    assert task is not None
    assert task.task_id == rooted_graph_id(
        rooted_tetrahedron.graph,
        rooted_tetrahedron.root,
    )
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_finished_task_is_not_reclaimed(tmp_path, rooted_tetrahedron):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    store.enqueue(rooted_tetrahedron)
    task = store.claim("worker-1")
    assert task is not None
    result = SearchResult(
        task_id=task.task_id,
        rooted=rooted_tetrahedron,
        presentation=PresentationKind.BILINEAR,
        probes=(),
        sieve_disposition=SieveDisposition.NOT_RUN,
        pruned=False,
        exact_seconds=0.01,
        exact_degree=0,
        rational_solutions=(),
    )
    store.finish(result)
    assert store.claim("worker-2") is None
    assert store.counts()["completed"] == 1
    assert tuple(store.results())[0]["task_id"] == task.task_id
    assert store.requeue((TaskStatus.COMPLETED,)) == 1
    assert store.claim("worker-2") is not None
