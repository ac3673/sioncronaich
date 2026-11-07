
<p align="center">
  <img width="350" height="150" src="https://raw.githubusercontent.com/ac3673/sioncronaich/refs/heads/main/img/sioncronaich.jpeg" alt='sioncronaich'>
</p>

<p align="center"><strong>sioncronaich</strong> <em>- A lightweight cron-job monitoring tool written in Python - from Gaelic "to synchronise, to chronicle"</em></p>

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3140/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-prek-blue?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Coverage](https://raw.githubusercontent.com/ac3673/sioncronaich/refs/heads/main/img/coverage-badge.svg)](https://github.com/ac3673/sioncronaich)


`sioncronaich` wraps any shell command, captures its **stdout**, **stderr** and **exit code**,
then POSTs the result to the sioncronaich web app, which stores everything in a local SQLite
database and renders it in a simple web dashboard.

---

## Quick start

### 1 — Start the web app

```bash
uv run uvicorn --factory sioncronaich.app:create_app --host 127.0.0.1 --port 8716
```

Pass `--host`, `--port`, and any other server options directly to uvicorn.
See `uvicorn --help` for the full list.

The app reads the following environment variables:

| Environment variable | Default | Purpose |
|---|---|---|
| `SIONCRONAICH_DB` | `~/.local/share/sioncronaich/jobs.db` | SQLite database path |
| `SIONCRONAICH_ROOT_PATH` | `/sioncronaich` | ASGI root path when mounted behind a reverse proxy |
| `SIONCRONAICH_FAILURES_ONLY` | *(unset)* | Set to `1`, `true`, or `yes` to discard successful job results without storing them |
| `SIONCRONAICH_ALERT_EMAIL` | *(unset — alerts disabled)* | Send a failure-alert email to this address whenever a job exits non-zero |
| `SIONCRONAICH_SMTP_HOST` | `localhost` | SMTP server hostname |
| `SIONCRONAICH_SMTP_PORT` | `25` | SMTP server port |
| `SIONCRONAICH_SMTP_FROM` | `sioncronaich@<hostname>` | Sender address |
| `SIONCRONAICH_SMTP_USERNAME` | *(unset)* | SMTP login username |
| `SIONCRONAICH_SMTP_PASSWORD` | *(unset)* | SMTP login password |
| `SIONCRONAICH_SMTP_STARTTLS` | *(unset)* | Set to `1`, `true`, or `yes` to issue STARTTLS after connecting |
| `SIONCRONAICH_SMTP_SSL` | *(unset)* | Set to `1`, `true`, or `yes` to connect with SMTP_SSL (implicit TLS) |
| `LOG_CONFIG` | *(unset — logs to stderr at INFO)* | Path to a YAML logging config file |

### 2 — Wrap a command

```bash
sioncronaich --name "daily-backup" -- /usr/local/bin/backup.sh --full
```

The wrapper exits with **the same exit code** as the wrapped command, so
existing cron alerting is unaffected. If posting to the web app fails, the
error is printed to stderr but the exit code is still that of the wrapped job.

```
Usage: sioncronaich [OPTIONS] COMMAND...

Options:
  --name TEXT       Human-readable label for this job  [required]
  --endpoint TEXT   URL of the POST /jobs endpoint
                    [default: http://127.0.0.1:8716/jobs]
  --timeout INT     HTTP request timeout in seconds  [default: 10]
  --failures-only   Only report the job if it exits with a non-zero code
```

The endpoint can also be set via the `SIONCRONAICH_ENDPOINT` environment
variable so you don't have to repeat it in every crontab entry. The
`--endpoint` flag takes precedence if both are set.

```bash
export SIONCRONAICH_ENDPOINT=http://mon.example.com/sioncronaich/jobs
```

`--failures-only` is useful for jobs that run very frequently where only
failures are worth keeping. It can also be enabled globally on the server
via `SIONCRONAICH_FAILURES_ONLY=1`, which will discard successful results
regardless of how the script was invoked.

### 3 — Add to crontab

```crontab
# m   h  dom mon dow  command
0     3  *   *   *    sioncronaich --name daily-backup -- /usr/local/bin/backup.sh
*/5   *  *   *   *    sioncronaich --name health-check -- /usr/local/bin/check.sh
```

### 4 — View the dashboard

Open **http://127.0.0.1:8716** in a browser for a colour-coded table of recent
job runs. stdout / stderr are available in collapsible panels.

The raw JSON API is also available:

| Method | Path | Description |
|---|---|---|
| `POST` | `/jobs` | Ingest a new job result (used by `sioncronaich`) |
| `GET` | `/jobs` | List job results as JSON (newest first) |
| `GET` | `/` | HTML dashboard |

Interactive API docs are served at **http://127.0.0.1:8716/docs**.

---

## Reverse proxy with Caddy

sioncronaich is designed to be mounted at a sub-path behind a reverse proxy.
The default sub-path is `/sioncronaich`; override it with
`SIONCRONAICH_ROOT_PATH`.

```caddy
example.com {
        reverse_proxy /sioncronaich/* 127.0.0.1:8716
        reverse_proxy /sioncronaich* 127.0.0.1:8716
}
```

Start the app with the matching root path:

```bash
SIONCRONAICH_ROOT_PATH=/sioncronaich \
  uv run uvicorn --factory sioncronaich.app:create_app --host 127.0.0.1 --port 8716
```

The dashboard is then available at **https://example.com/sioncronaich** and
the ingest endpoint at **https://example.com/sioncronaich/jobs**.

---

## Logging

By default the app logs to stderr at INFO level. To use a custom logging
configuration, point `LOG_CONFIG` at a YAML file in the standard
[`logging.config.dictConfig`](https://docs.python.org/3/library/logging.config.html#logging-config-dictschema)
format. A ready-to-use example is provided at `logging.yaml`:

```bash
LOG_CONFIG=logging.yaml uv run uvicorn --factory sioncronaich.app:create_app
```

---

## Development

```bash
uv sync --all-extras
uv run prek install
```
