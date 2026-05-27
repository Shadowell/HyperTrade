from typing import Any

from sqlalchemy import select

from hypertrade.db import Database, Job


class JobQueue:
    def __init__(self, db: Database) -> None:
        self.db = db

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None) -> str:
        with self.db.session() as session:
            job = Job(kind=kind, payload=payload or {}, status="pending")
            session.add(job)
            session.flush()
            return job.id

    def claim_next(self) -> Job | None:
        with self.db.session() as session:
            job = session.scalar(
                select(Job).where(Job.status == "pending").order_by(Job.created_at).limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            session.flush()
            session.expunge(job)
            return job

    def complete(self, job_id: str) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "completed"

    def fail(self, job_id: str, error: str) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.last_error = error
