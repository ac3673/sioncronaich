"""SQLite persistence layer for job results."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sioncronaich.models import JobResult, JobResultCreate

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS job_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name     TEXT    NOT NULL,
    hostname     TEXT    NOT NULL,
    command      TEXT    NOT NULL,
    stdout       TEXT    NOT NULL,
    stderr       TEXT    NOT NULL,
    exit_code    INTEGER NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL
);
"""


def _default_db_path() -> Path:
    base = Path.home() / ".local" / "share" / "sioncronaich"
    base.mkdir(parents=True, exist_ok=True)
    return base / "jobs.db"


@contextmanager
def _connect(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:  # pragma: no cover
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    """Create the database schema if it does not already exist.

    Returns the resolved path to the database file.
    """
    resolved = db_path or _default_db_path()
    with _connect(resolved) as conn:
        conn.execute(_CREATE_TABLE)
    return resolved


def insert_job(job: JobResultCreate, db_path: Path | None = None) -> JobResult:
    """Persist a new job result and return it with its assigned *id*."""
    resolved = db_path or _default_db_path()
    with _connect(resolved) as conn:
        cursor = conn.execute(
            """
            INSERT INTO job_results
                (job_name, hostname, command, stdout, stderr, exit_code, started_at, finished_at)
            VALUES
                (:job_name, :hostname, :command, :stdout, :stderr, :exit_code, :started_at, :finished_at)
            """,
            {
                "job_name": job.job_name,
                "hostname": job.hostname,
                "command": job.command,
                "stdout": job.stdout,
                "stderr": job.stderr,
                "exit_code": job.exit_code,
                "started_at": job.started_at.isoformat(),
                "finished_at": job.finished_at.isoformat(),
            },
        )
        row_id: int = cursor.lastrowid  # type: ignore[assignment]

    return JobResult(
        id=row_id,
        job_name=job.job_name,
        hostname=job.hostname,
        command=job.command,
        stdout=job.stdout,
        stderr=job.stderr,
        exit_code=job.exit_code,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def get_jobs(
    *,
    limit: int = 200,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[JobResult]:
    """Return the most-recent *limit* job results, newest first."""
    resolved = db_path or _default_db_path()
    with _connect(resolved) as conn:
        rows = conn.execute(
            """
            SELECT id, job_name, hostname, command, stdout, stderr, exit_code, started_at, finished_at
            FROM   job_results
            ORDER  BY id DESC
            LIMIT  :limit OFFSET :offset
            """,
            {"limit": limit, "offset": offset},
        ).fetchall()

    return [
        JobResult(
            id=row["id"],
            job_name=row["job_name"],
            hostname=row["hostname"],
            command=row["command"],
            stdout=row["stdout"],
            stderr=row["stderr"],
            exit_code=row["exit_code"],
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
        )
        for row in rows
    ]
