"""SQLite persistence for a durable, single-consumer ASR queue."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .domain import JobStatus, can_transition


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvalidTransition(ValueError):
    pass


class JobStore:
    """A small synchronized SQLite repository. One application owns the database."""

    def __init__(self, database: Path) -> None:
        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    media_path TEXT NOT NULL,
                    result_path TEXT,
                    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                    duration_seconds REAL,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
                """
            )
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")

    def close(self) -> None:
        self._connection.close()

    def create_job(self, original_name: str, stored_name: str, media_path: Path) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO jobs (id, original_name, stored_name, media_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, original_name, stored_name, str(media_path), JobStatus.QUEUED.value, now, now),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_queued_ids(self) -> List[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at ASC"
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def recover_interrupted_jobs(self) -> List[str]:
        """A process killed mid-inference has no usable worker; return it to the queue."""

        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ?, started_at = NULL "
                "WHERE status = 'running'",
                (now,),
            )
        return self.list_queued_ids()

    def transition(
        self,
        job_id: str,
        target: JobStatus,
        *,
        failure_reason: Optional[str] = None,
        result_path: Optional[Path] = None,
        duration_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        current_job = self.get_job(job_id)
        if current_job is None:
            raise KeyError(job_id)
        current = JobStatus(current_job["status"])
        if not can_transition(current, target):
            raise InvalidTransition("%s cannot transition to %s" % (current.value, target.value))

        now = utc_now()
        updates: Dict[str, Any] = {"status": target.value, "updated_at": now}
        if target is JobStatus.RUNNING:
            updates["started_at"] = now
            updates["failure_reason"] = None
        if target is JobStatus.FAILED:
            updates["failure_reason"] = failure_reason or "转写失败，未提供详细原因。"
            updates["completed_at"] = now
        if target is JobStatus.COMPLETED:
            updates["result_path"] = str(result_path) if result_path else None
            updates["duration_seconds"] = duration_seconds
            updates["failure_reason"] = None
            updates["completed_at"] = now

        columns = ", ".join("%s = ?" % key for key in updates)
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE jobs SET %s WHERE id = ?" % columns, (*updates.values(), job_id)
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)
