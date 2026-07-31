"""Crash-safe SQLite task storage for long graph searches."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph
from agentic_blanche.symmetry import rooted_graph_id
from agentic_blanche.workflow import SearchResult


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SHELVED = "shelved"
    TIMED_OUT = "timed-out"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rooted_payload(rooted: RootedPlaneGraph) -> str:
    return json.dumps(
        {
            "rotations": rooted.graph.rotations,
            "root": rooted.root,
        },
        separators=(",", ":"),
    )


def _decode_rooted(payload: str) -> RootedPlaneGraph:
    data = json.loads(payload)
    graph = PlaneGraph(
        tuple(tuple(int(neighbor) for neighbor in row) for row in data["rotations"])
    )
    return RootedPlaneGraph(graph, tuple(int(vertex) for vertex in data["root"]))


@dataclass(frozen=True)
class StoredTask:
    sequence: int
    task_id: str
    rooted: RootedPlaneGraph
    attempts: int


@dataclass
class SQLiteTaskStore:
    """A small leasing queue backed by SQLite in WAL mode."""

    path: Path
    _initialized: bool = field(default=False, init=False, repr=False)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=30000")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT,
                    lease_expires TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_status_sequence
                    ON tasks(status, sequence);
                CREATE TABLE IF NOT EXISTS manifests (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        self._initialized = True

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def enqueue(self, rooted: RootedPlaneGraph) -> bool:
        self._ensure_initialized()
        task_id = rooted_graph_id(rooted.graph, rooted.root)
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO tasks
                    (task_id, payload, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    _rooted_payload(rooted),
                    TaskStatus.PENDING.value,
                    timestamp,
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def enqueue_many(self, rooted_graphs: Iterable[RootedPlaneGraph]) -> int:
        self._ensure_initialized()
        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for rooted in rooted_graphs:
                    task_id = rooted_graph_id(rooted.graph, rooted.root)
                    timestamp = _now()
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO tasks
                            (task_id, payload, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            _rooted_payload(rooted),
                            TaskStatus.PENDING.value,
                            timestamp,
                            timestamp,
                        ),
                    )
                    inserted += int(cursor.rowcount == 1)
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        return inserted

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 3600,
    ) -> StoredTask | None:
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        self._ensure_initialized()
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, worker_id = NULL, lease_expires = NULL,
                        updated_at = ?
                    WHERE status = ? AND lease_expires < ?
                    """,
                    (
                        TaskStatus.PENDING.value,
                        now.isoformat(),
                        TaskStatus.RUNNING.value,
                        now.isoformat(),
                    ),
                )
                row = connection.execute(
                    """
                    SELECT sequence, task_id, payload, attempts
                    FROM tasks
                    WHERE status = ?
                    ORDER BY sequence
                    LIMIT 1
                    """,
                    (TaskStatus.PENDING.value,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, attempts = attempts + 1, worker_id = ?,
                        lease_expires = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        TaskStatus.RUNNING.value,
                        worker_id,
                        expires.isoformat(),
                        now.isoformat(),
                        row["task_id"],
                    ),
                )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        return StoredTask(
            sequence=int(row["sequence"]),
            task_id=str(row["task_id"]),
            rooted=_decode_rooted(str(row["payload"])),
            attempts=int(row["attempts"]) + 1,
        )

    def finish(self, result: SearchResult) -> None:
        if result.pruned:
            status = TaskStatus.SHELVED
        elif result.exact_timed_out:
            status = TaskStatus.TIMED_OUT
        else:
            status = TaskStatus.COMPLETED
        self._transition(
            result.task_id,
            status,
            result=json.dumps(result.to_dict(), sort_keys=True),
        )

    def fail(self, task_id: str, error: str) -> None:
        self._transition(task_id, TaskStatus.FAILED, error=error)

    def requeue(self, statuses: Iterable[TaskStatus]) -> int:
        """Return selected terminal states to the pending queue."""
        values = tuple(dict.fromkeys(status.value for status in statuses))
        if not values:
            return 0
        forbidden = {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
        if forbidden.intersection(values):
            raise ValueError("only terminal task states can be requeued")
        self._ensure_initialized()
        placeholders = ",".join("?" for _ in values)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE tasks
                SET status = ?, worker_id = NULL, lease_expires = NULL,
                    result = NULL, error = NULL, updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (TaskStatus.PENDING.value, _now(), *values),
            )
            return cursor.rowcount

    def _transition(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        self._ensure_initialized()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = ?, result = ?, error = ?, worker_id = NULL,
                    lease_expires = NULL, updated_at = ?
                WHERE task_id = ? AND status = ?
                """,
                (
                    status.value,
                    result,
                    error,
                    _now(),
                    task_id,
                    TaskStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"task {task_id} is not held by a worker")

    def record_manifest(self, run_id: str, manifest: Mapping[str, object]) -> None:
        self._ensure_initialized()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO manifests(run_id, payload, created_at)
                VALUES (?, ?, ?)
                """,
                (run_id, json.dumps(manifest, sort_keys=True), _now()),
            )

    def counts(self) -> dict[str, int]:
        self._ensure_initialized()
        counts = {status.value: 0 for status in TaskStatus}
        with self._connect() as connection:
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ):
                counts[str(row["status"])] = int(row["count"])
        return counts

    def results(self) -> Iterator[dict[str, object]]:
        self._ensure_initialized()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result FROM tasks
                WHERE result IS NOT NULL
                ORDER BY sequence
                """
            )
            for row in rows:
                yield json.loads(str(row["result"]))

    def checkpoint_and_check(self) -> None:
        """Checkpoint the WAL and fail if the standalone database is damaged."""
        self._ensure_initialized()
        with self._connect() as connection:
            busy, _, _ = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if busy:
                raise RuntimeError("could not checkpoint SQLite WAL: database is busy")
            errors = [
                str(row[0]) for row in connection.execute("PRAGMA integrity_check")
            ]
        if errors != ["ok"]:
            detail = "\n".join(errors[:5])
            raise RuntimeError(f"SQLite integrity check failed:\n{detail}")
