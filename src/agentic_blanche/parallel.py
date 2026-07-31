"""Process-level workers coordinated by the SQLite task store."""

from __future__ import annotations

import os
import socket
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from agentic_blanche.msolve import MSolve
from agentic_blanche.storage import SQLiteTaskStore
from agentic_blanche.workflow import SearchConfig, SearchWorkflow


@dataclass(frozen=True)
class WorkerSummary:
    worker_id: str
    completed: int
    failed: int


def _work(
    database: str,
    executable: str,
    config: SearchConfig,
    worker_index: int,
    lease_seconds: float,
) -> WorkerSummary:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{worker_index}"
    store = SQLiteTaskStore(Path(database))
    solver = MSolve(executable=executable, threads=config.exact_threads)
    workflow = SearchWorkflow(solver, config)
    completed = failed = 0
    while task := store.claim(worker_id, lease_seconds=lease_seconds):
        try:
            result = workflow.process(task.rooted)
            if result.task_id != task.task_id:
                raise ValueError("stored task ID does not match its graph")
            store.finish(result)
            completed += 1
        except Exception as error:
            store.fail(task.task_id, f"{type(error).__name__}: {error}")
            failed += 1
    return WorkerSummary(worker_id, completed, failed)


def run_parallel(
    store: SQLiteTaskStore,
    *,
    msolve: str,
    config: SearchConfig,
    workers: int,
    lease_seconds: float = 3600,
) -> tuple[WorkerSummary, ...]:
    if workers < 1:
        raise ValueError("worker count must be positive")
    store.initialize()
    if workers == 1:
        return (_work(str(store.path), msolve, config, 0, lease_seconds),)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _work,
                str(store.path),
                msolve,
                config,
                index,
                lease_seconds,
            )
            for index in range(workers)
        ]
        return tuple(future.result() for future in futures)
