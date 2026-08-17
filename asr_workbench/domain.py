"""Domain objects and the deliberately small job state machine."""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


ALLOWED_TRANSITIONS: Dict[JobStatus, FrozenSet[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    JobStatus.RUNNING: frozenset({JobStatus.COMPLETED, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """Return whether a job can make this real processing-state transition."""

    return target in ALLOWED_TRANSITIONS[current]
