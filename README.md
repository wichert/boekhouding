# Boekhouding

Read-only XAF (XML Auditfile Financieel) web explorer and command-line tools for account analysis, CSV export, and CAMT.053 bank statements. No Manegeplan database or external bookkeeping API is required.

## Setup

```bash
uv sync --extra test
npm ci && npm run build
```

## Web explorer

```bash
AUDITLOG_XAF_PATH='data/auditlog-*.xaf' uv run boekhouding serve
```

Open `http://127.0.0.1:8000`. The explorer provides:

- Balans and Winst & Verlies overviews for the selected audit file.
- General-ledger account overviews and chronological account details.
- Transaction lists, filters, and transaction detail modals.

`AUDITLOG_XAF_PATH` accepts one file, a directory, or a glob and defaults to `data/auditlog-*.xaf`. `BIND_HOST` and `BIND_PORT` default to `127.0.0.1` and `8000`. Use `--host`, `--port`, `--audit-file`, or `--reload` on `boekhouding serve` to override them.

## CLI

```bash
# All lines and unmatched postings for one general-ledger account
uv run boekhouding auditfile-account-report data/auditlog-2025.xaf -a 1500 -o output

# One account as CSV (date, description, debit, credit, factuur)
uv run boekhouding account-to-csv data/auditlog-2025.xaf 1500 -o output/account-1500.csv

# One CSV row per Ntry in a CAMT.053 bank statement
uv run boekhouding camt053-to-csv data/statement.xml -o output/camt053.csv
```

## Tests

```bash
npm ci && npm run build
uv run pytest --cov
```

The tests use local fixtures and a FastAPI `TestClient`; they need no database.

## Container

```bash
podman build --format docker -t boekhouding .
podman run --rm -p 8000:8000 \
  -e AUDITLOG_XAF_PATH='data/auditlog-*.xaf' \
  -v "$PWD/data:/app/data:ro" boekhouding
```

The image runs `boekhouding serve` as an unprivileged user. `BIND_HOST` defaults to `0.0.0.0` in the image. To run the same startup check used in CI:

```bash
scripts/test-container-startup.sh boekhouding
```

Release Please maintains release PRs. Merging one publishes a GitHub release and GHCR container image; no Python package is published.
