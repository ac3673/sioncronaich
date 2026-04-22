"""Shared Pydantic models used by both the script and the web app."""

from datetime import datetime

from pydantic import BaseModel, computed_field


class JobResultCreate(BaseModel):
    """Payload posted by the sioncronaich script after a job finishes."""

    job_name: str
    hostname: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    started_at: datetime
    finished_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class JobResult(JobResultCreate):
    """A job result as stored in (and returned from) the database."""

    id: int

    @computed_field  # type: ignore[misc]
    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    model_config = {"from_attributes": True}
