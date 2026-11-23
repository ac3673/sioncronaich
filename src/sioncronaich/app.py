"""FastAPI web application — job ingest endpoint and HTML dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from statistics import median

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sioncronaich import __version__
from sioncronaich.config import Settings, configure_logging, load_settings
from sioncronaich.db import (
    cleanup_old_jobs,
    get_all_job_names,
    get_job_by_id,
    get_jobs,
    get_run_history,
    init_db,
    insert_job,
    record_run,
)
from sioncronaich.email_alert import send_failure_alert, send_missing_job_alert
from sioncronaich.models import JobResult, JobResultCreate

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def _cleanup_loop(settings: Settings) -> None:
    """Run :func:`cleanup_old_jobs` once at startup and then nightly at UTC midnight."""
    try:
        deleted = cleanup_old_jobs(db_path=settings.db)
        logger.info("Startup cleanup: removed %s job(s) (successful >7d, failed >30d)", deleted)
    except Exception:
        logger.exception("Failed to clean up old jobs in db")
    while True:
        now = datetime.now(UTC)
        next_midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
        await asyncio.sleep((next_midnight - now).total_seconds())
        try:
            deleted = cleanup_old_jobs(db_path=settings.db)
            logger.info(
                "Midnight cleanup: removed %s job(s) (successful >7d, failed >30d)",
                deleted,
            )
        except Exception:
            logger.exception("Midnight cleanup encountered an error")


async def _missing_jobs_loop(settings: Settings) -> None:
    # Sleep first so an operator deploying a new instance isn't immediately
    # flooded with alerts for jobs that happen to be overdue at startup.
    await asyncio.sleep(3600)
    exclude = set(settings.missing_job_exclude)
    while True:
        now = datetime.now(UTC)
        try:
            job_names = get_all_job_names(db_path=settings.db)
        except Exception:
            logger.exception("_missing_jobs_loop: failed to fetch job names")
            await asyncio.sleep(3600)
            continue
        for job_name in job_names:
            if job_name in exclude:
                continue
            try:
                history = get_run_history(
                    job_name, limit=settings.missing_job_min_runs + 5, db_path=settings.db
                )
                if len(history) < settings.missing_job_min_runs:
                    continue
                intervals = [
                    (history[i] - history[i + 1]).total_seconds()
                    for i in range(len(history) - 1)
                    if (history[i] - history[i + 1]).total_seconds() > 0
                ]
                if not intervals:
                    logger.debug(
                        "_missing_jobs_loop: no positive intervals for %r; skipping",
                        job_name,
                    )
                    continue
                threshold = timedelta(
                    seconds=median(intervals) * settings.missing_job_multiplier
                )
                if now - history[0] > threshold:
                    send_missing_job_alert(job_name, history[0], settings)
            except Exception:
                logger.exception("_missing_jobs_loop: error while checking job %r", job_name)
        await asyncio.sleep(3600)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    resolved = init_db(app.state.settings.db)
    logger.info("Database ready at %s", resolved)
    cleanup_task = asyncio.create_task(_cleanup_loop(app.state.settings))
    missing_task = (
        asyncio.create_task(_missing_jobs_loop(app.state.settings))
        if app.state.settings.missing_job_alerts
        else None
    )
    try:
        yield
    finally:
        for task in (cleanup_task, missing_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    load_dotenv()
    settings = load_settings()

    app = FastAPI(
        title="sioncronaich",
        description="Cron job output capture and monitoring",
        version=__version__,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ---------------------------------------------------------------------
    # API routes
    # ---------------------------------------------------------------------

    @app.post("/jobs", response_model=JobResult, status_code=201)
    def create_job(job: JobResultCreate, request: Request) -> Response:
        """Persist a job result; when ``failures_only`` is set, drop successes with 204."""
        s = _get_settings(request)
        logger.info("Received job result: %s (exit_code=%s)", job.job_name, job.exit_code)
        record_run(job, db_path=s.db)
        if s.failures_only and job.exit_code == 0:
            logger.debug("Discarding successful job %r (failures_only mode)", job.job_name)
            return Response(status_code=204)
        result = insert_job(job, db_path=s.db)
        if result.exit_code != 0:
            send_failure_alert(result, s)
        return JSONResponse(result.model_dump(mode="json"), status_code=201)

    @app.get("/jobs", response_model=list[JobResult])
    def list_jobs(
        request: Request,
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
            db_path=_get_settings(request).db,
        )

    @app.get("/jobs/{job_id}/output")
    def job_output(job_id: int, request: Request) -> JSONResponse:
        """Return stdout and stderr for a single job — fetched lazily by the dashboard."""
        job = get_job_by_id(job_id, db_path=_get_settings(request).db)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse({"stdout": job.stdout, "stderr": job.stderr})

    @app.get("/jobs/{job_id}/output/{field}", response_class=HTMLResponse)
    def job_output_field(job_id: int, field: str, request: Request) -> HTMLResponse:
        """Return a single output field as an HTML-escaped fragment for htmx."""
        if field not in ("stdout", "stderr"):
            raise HTTPException(status_code=400, detail="field must be stdout or stderr")
        job = get_job_by_id(job_id, db_path=_get_settings(request).db)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return HTMLResponse(html.escape(getattr(job, field) or "(empty)"))

    # ---------------------------------------------------------------------
    # HTML dashboard
    # ---------------------------------------------------------------------

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
            db_path=_get_settings(request).db,
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
            exclude_output=False,
            db_path=_get_settings(request).db,
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

    return app


if __name__ == "__main__":  # pragma: no cover
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the sioncronaich web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8716, help="Bind port (default: 8716)")
    args = parser.parse_args()

    load_dotenv()
    settings = load_settings()
    uvicorn.run(
        "sioncronaich.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        root_path=settings.root_path,
    )
