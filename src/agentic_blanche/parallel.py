"""Process-level workers coordinated by the SQLite task store."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, wait
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
    progress: Callable[[dict[str, int]], None] | None = None,
    progress_interval: float = 30,
) -> WorkerSummary:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{worker_index}"
    store = SQLiteTaskStore(Path(database))
    solver = MSolve(executable=executable, threads=config.exact_threads)
    workflow = SearchWorkflow(solver, config)
    completed = failed = 0
    last_progress = time.monotonic()
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
        if (
            progress is not None
            and time.monotonic() - last_progress >= progress_interval
        ):
            progress(store.counts())
            last_progress = time.monotonic()
    return WorkerSummary(worker_id, completed, failed)


def run_parallel(
    store: SQLiteTaskStore,
    *,
    msolve: str,
    config: SearchConfig,
    workers: int,
    lease_seconds: float = 3600,
    progress: Callable[[dict[str, int]], None] | None = None,
    progress_interval: float = 30,
) -> tuple[WorkerSummary, ...]:
    if workers < 1:
        raise ValueError("worker count must be positive")
    if progress_interval <= 0:
        raise ValueError("progress interval must be positive")
    store.initialize()
    if workers == 1:
        return (
            _work(
                str(store.path),
                msolve,
                config,
                0,
                lease_seconds,
                progress,
                progress_interval,
            ),
        )
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
        pending = set(futures)
        while pending:
            _, pending = wait(pending, timeout=progress_interval)
            if pending and progress is not None:
                progress(store.counts())
        return tuple(future.result() for future in futures)
