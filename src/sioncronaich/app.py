"""FastAPI web application — job ingest endpoint and HTML dashboard."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from sioncronaich import __version__
from sioncronaich.config import configure_logging, db_path, root_path
from sioncronaich.db import get_job_by_id, get_jobs, init_db, insert_job
from sioncronaich.models import JobResult, JobResultCreate

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Configure logging and ensure the database schema exists when the server starts."""
    configure_logging()
    resolved = init_db(db_path())
    logger.info("Database ready at %s", resolved)
    yield


app = FastAPI(
    title="sioncronaich",
    description="Cron job output capture and monitoring",
    version=__version__,
    lifespan=_lifespan,
    root_path=root_path(),
)

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.post("/jobs", response_model=JobResult, status_code=201)
def create_job(job: JobResultCreate) -> JobResult:
    """Receive and persist a single job result from the sioncronaich script."""
    logger.info("Received job result: %s (exit_code=%s)", job.job_name, job.exit_code)
    return insert_job(job, db_path=db_path())


@app.get("/jobs", response_model=list[JobResult])
def list_jobs(
    limit: int = 200,
    offset: int = 0,
    job_name: str | None = None,
    hostname: str | None = None,
    status: str | None = None,
    command: str | None = None,
) -> list[JobResult]:
    """Return job results as JSON (newest first)."""
    return get_jobs(
        limit=limit,
        offset=offset,
        job_name=job_name,
        hostname=hostname,
        status=status,
        command=command,
        db_path=db_path(),
    )


@app.get("/jobs/{job_id}/output")
def job_output(job_id: int) -> JSONResponse:
    """Return stdout and stderr for a single job — fetched lazily by the dashboard."""
    job = get_job_by_id(job_id, db_path=db_path())
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({"stdout": job.stdout, "stderr": job.stderr})


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@app.get("/table", response_class=HTMLResponse)
def table_partial(
    request: Request,
    limit: int = 200,
    offset: int = 0,
    job_name: str | None = None,
    hostname: str | None = None,
    status: str | None = None,
    command: str | None = None,
) -> Response:
    """Return just the table+pagination fragment for htmx partial updates."""
    jobs = get_jobs(
        limit=limit,
        offset=offset,
        job_name=job_name,
        hostname=hostname,
        status=status,
        command=command,
        exclude_output=True,
        db_path=db_path(),
    )
    return templates.TemplateResponse(
        request,
        "table_partial.html",
        {
            "jobs": jobs,
            "limit": limit,
            "offset": offset,
            "job_name": job_name or "",
            "hostname": hostname or "",
            "status": status or "",
            "command": command or "",
        },
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    limit: int = 200,
    offset: int = 0,
    job_name: str | None = None,
    hostname: str | None = None,
    status: str | None = None,
    command: str | None = None,
) -> Response:
    """Render an HTML table of recent job results."""
    jobs = get_jobs(
        limit=limit,
        offset=offset,
        job_name=job_name,
        hostname=hostname,
        status=status,
        command=command,
        exclude_output=True,
        db_path=db_path(),
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "jobs": jobs,
            "limit": limit,
            "offset": offset,
            "job_name": job_name or "",
            "hostname": hostname or "",
            "status": status or "",
            "command": command or "",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """App factory — used with ``uvicorn --factory sioncronaich.app:create_app``."""
    return app


if __name__ == "__main__":  # pragma: no cover
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the sioncronaich web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8716, help="Bind port (default: 8716)")
    args = parser.parse_args()

    uvicorn.run("sioncronaich.app:create_app", host=args.host, port=args.port, factory=True)
