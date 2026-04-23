"""sioncronaich -- wrap a command, capture its output, and POST the result."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
from datetime import UTC, datetime

import click
import requests

from sioncronaich.models import JobResultCreate


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _run_command(command: tuple[str, ...]) -> tuple[str, str, int, datetime, datetime]:
    """Execute *command* via the system shell, capture output and return
    (stdout, stderr, exit_code, started_at, finished_at).

    Running via the shell allows shell built-ins (cd, export, …) and
    operators (&&, ||, ;, pipes) to work as expected.
    """
    started_at = _now()
    # shlex.join() produces POSIX quoting for sh; Windows cmd.exe needs plain joining
    shell_cmd = " ".join(command) if sys.platform == "win32" else shlex.join(command)
    result = subprocess.run(
        shell_cmd,
        shell=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    finished_at = _now()
    return result.stdout, result.stderr, result.returncode, started_at, finished_at


def _post_result(endpoint: str, payload: JobResultCreate, timeout: int) -> None:
    """POST the job result to the sioncronaich web app.

    Failures are printed to stderr but never raise -- the wrapped job's exit
    code should not be affected by a reporting error.
    """
    try:
        response = requests.post(
            endpoint,
            data=payload.model_dump_json(),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        click.echo(f"sioncronaich: failed to post result to {endpoint!r}: {exc}", err=True)


@click.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    help=(
        "Wrap COMMAND, capture its stdout/stderr/exit-code and POST the result "
        "to a sioncronaich web app.  All arguments after -- are treated as the "
        "command to run.\n\n"
        "Example (crontab):\n\n"
        "  0 3 * * *  sioncronaich --name daily-backup --endpoint http://mon:8716/jobs -- /usr/local/bin/backup.sh"
    ),
)
@click.option(
    "--name",
    required=True,
    help="Human-readable label for this job (e.g. 'daily-backup').",
)
@click.option(
    "--endpoint",
    default=lambda: os.environ.get("SIONCRONAICH_ENDPOINT", "http://127.0.0.1:8716/jobs"),
    show_default=True,
    help="URL of the sioncronaich POST /jobs endpoint. Overrides SIONCRONAICH_ENDPOINT env var.",
)
@click.option(
    "--timeout",
    default=10,
    show_default=True,
    help="HTTP request timeout in seconds when posting the result.",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
def main(
    name: str,
    endpoint: str,
    timeout: int,
    command: tuple[str, ...],
) -> None:
    stdout, stderr, exit_code, started_at, finished_at = _run_command(command)

    payload = JobResultCreate(
        job_name=name,
        hostname=socket.gethostname(),
        command=" ".join(command),
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=finished_at,
    )

    _post_result(endpoint, payload, timeout)

    sys.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()
