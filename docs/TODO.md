# TODO — Code Review Findings (v0.4.0)

Items identified during a full code review. Ordered by severity.

---

## 🔴 Bugs

### 1. `db.py` — `has_stdout` / `has_stderr` threshold is `> 1` (should be `> 0`)

**File:** `src/sioncronaich/db.py` — `get_jobs()`

```python
# current (wrong)
has_stdout=len(row["stdout"]) > 1,
has_stderr=len(row["stderr"]) > 1,
```

Any single-character output (e.g. `"\n"`, `"0"`) is treated as empty.
The "show stdout / show stderr" link never appears in the dashboard for
those rows. Fix: change `> 1` → `> 0` (or use `bool(row["stdout"])`).

---

## 🟡 Deprecations

### 2. `app.py` — `root_path` kwarg to `FastAPI()` is deprecated

**File:** `src/sioncronaich/app.py`

The installed FastAPI version emits `FastAPIDeprecationWarning` when
`root_path` is passed to the `FastAPI()` constructor. The recommended
approach is to set it at the ASGI server level instead, e.g.:

```
uvicorn sioncronaich.app:create_app --root-path /sioncronaich --factory
```

Action: remove the `root_path=root_path()` kwarg from the `FastAPI()`
call and update the `__main__` block / README to show the server-level
flag.

### 3. `httpx` → `httpx2` for `TestClient`

**File:** `tests/conftest.py` (transitively via `starlette.testclient`)

Starlette now emits `StarletteDeprecationWarning` recommending `httpx2`
over `httpx`. Track when `httpx2` stabilises and pin accordingly; also
add `httpx` (or `httpx2`) explicitly to dev dependencies (see item 10).

---

## 🟡 Reliability

### 4. `email_alert.py` — No SMTP timeout

**File:** `src/sioncronaich/email_alert.py`

```python
with smtplib.SMTP(host, port) as conn:   # no timeout
```

A hung SMTP server blocks the entire ingest request indefinitely.
Add a configurable timeout (default 10 s) via a new `smtp_timeout()`
helper in `config.py`, and pass it to both `smtplib.SMTP()` and
`smtplib.SMTP_SSL()`.

### 5. `email_alert.py` — Conflicting `smtp_ssl` + `smtp_starttls` silently ignored

**File:** `src/sioncronaich/email_alert.py`

When both `SIONCRONAICH_SMTP_SSL=1` and `SIONCRONAICH_SMTP_STARTTLS=1`
are set, SSL wins silently and STARTTLS is ignored with no indication to
the operator.

Action: add a `logger.warning(...)` when both are truthy so operators
know which setting is taking effect.

---

## 🟡 Style / Maintainability

### 6. `config.py` — `import socket` is out of order

**File:** `src/sioncronaich/config.py`

`socket` is a stdlib module but is imported after the blank line that
separates stdlib from third-party imports:

```python
import os
from pathlib import Path

import socket   # ← should be in the stdlib block above

import yaml
```

Move `import socket` up to sit with the other stdlib imports.

### 7. `app.py` — f-strings in logging calls

**File:** `src/sioncronaich/app.py`

```python
logger.info(f"Startup cleanup: removed {deleted} job(s) ...")
```

Python's logging module supports lazy `%`-style formatting which avoids
building the string when the log level is filtered out. All f-strings in
`logger.*()` calls should use `%s` style:

```python
logger.info("Startup cleanup: removed %s job(s) ...", deleted)
```

### 8. Templates — Pagination URLs are not URL-encoded

**Files:** `src/sioncronaich/templates/index.html`,
`src/sioncronaich/templates/table_partial.html`

```html
href="...&job_name={{ job_name }}&hostname={{ hostname }}..."
```

If a filter value contains `&`, `+`, `%`, or spaces the generated URL is
malformed and pagination silently breaks. Apply Jinja2's `urlencode`
filter (or pass values through `urllib.parse.quote_plus` in the route
handler before handing them to the template context).

### 9. Templates — Table HTML is fully duplicated

**Files:** `src/sioncronaich/templates/index.html`,
`src/sioncronaich/templates/table_partial.html`

The entire `<table>` block (thead, all td renderings, htmx attributes,
badges) is copy-pasted between the two templates. Any change must be
made twice and can easily drift.

Action: extract the shared block into a Jinja2 `{% include "table.html" %}`
partial or a `{% macro %}` to have a single source of truth.

---

## 🟡 Packaging

### 10. `pyproject.toml` — `httpx` missing from dev dependencies

**File:** `pyproject.toml`

`TestClient` requires `httpx`, but it is not listed in
`[dependency-groups] dev`. It is currently pulled in transitively by
`fastapi[standard]`, which is fragile.

Action: add `httpx>=0.27` (or `httpx2` when ready) explicitly to the
dev dependency group.

---

## 🟡 Clarity

### 11. `app.py` — `create_app()` is a singleton, not a true factory

**File:** `src/sioncronaich/app.py`

```python
def create_app() -> FastAPI:
    return app   # always returns the same module-level instance
```

The name implies a new instance is constructed on each call (the standard
app-factory pattern), but it always returns the same object. This is fine
for the current use case but is misleading.

Action: either add a docstring clarifying it returns the shared instance,
or refactor so it genuinely constructs a fresh `FastAPI` app (moving the
`lifespan` attachment inside `create_app()`).
