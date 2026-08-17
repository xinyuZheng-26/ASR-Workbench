import sqlite3

import pytest

from asr_workbench.domain import JobStatus, can_transition
from asr_workbench.store import InvalidTransition, JobStore


def test_state_machine_only_allows_real_lifecycle() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.COMPLETED)
    assert can_transition(JobStatus.RUNNING, JobStatus.FAILED)
    assert can_transition(JobStatus.FAILED, JobStatus.QUEUED)
    assert not can_transition(JobStatus.QUEUED, JobStatus.COMPLETED)
    assert not can_transition(JobStatus.COMPLETED, JobStatus.QUEUED)


def test_store_rejects_impossible_transition_and_permits_retry(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job("样本.wav", "sample.wav", tmp_path / "sample.wav")
    with pytest.raises(InvalidTransition):
        store.transition(job["id"], JobStatus.COMPLETED)
    store.transition(job["id"], JobStatus.RUNNING)
    store.transition(job["id"], JobStatus.FAILED, failure_reason="示例失败")
    retried = store.transition(job["id"], JobStatus.QUEUED)
    assert retried["status"] == "queued"
    store.close()


def test_enum_and_sqlite_constraint_reject_fake_progress_status(tmp_path) -> None:
    with pytest.raises(ValueError):
        JobStatus("processing-42%")
    store = JobStore(tmp_path / "jobs.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(  # noqa: SLF001 - verifies the database-level state type guard.
            "INSERT INTO jobs (id, original_name, stored_name, media_path, status, created_at, updated_at) "
            "VALUES ('x', 'x.wav', 'x.wav', '/tmp/x.wav', 'processing-42%', 'now', 'now')"
        )
    store.close()
