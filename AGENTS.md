# Boekhouding

## Scope

XAF auditfile exploration and CAMT.053 conversion only. The project is independent of Liethorp, Manegeplan, Conscribo, and e-boekhouden. Treat input files as read-only.

## Structure

- `boekhouding/audit_parser.py`: XAF document parsing and account/transaction summaries.
- `boekhouding/audit_routes.py`: read-only FastAPI HTML and `/api/audit/*` routes, file discovery, and ETags.
- `boekhouding/auditfile_report.py`: account lines, matching, and CSV reports.
- `boekhouding/camt053.py`: CAMT.053 parsing and CSV writing.
- `boekhouding/cli.py`: one Typer CLI with `serve`, `auditfile-account-report`, `account-to-csv`, and `camt053-to-csv`.
- `boekhouding/app.py`: FastAPI app and server lifecycle.
- `frontend/app`: Vue/Bootstrap/Vite frontend; generated files in `boekhouding/static/app` are ignored.
- `tests`: local XAF/CAMT fixtures and FastAPI `TestClient`; no live services.

## Commands

```bash
uv sync --extra test
npm ci && npm run build
uv run pytest --cov
uv run boekhouding serve
uv run boekhouding auditfile-account-report data/auditlog-2025.xaf -a 1500 -o output
uv run boekhouding account-to-csv data/auditlog-2025.xaf 1500 -o output/account-1500.csv
uv run boekhouding camt053-to-csv data/statement.xml -o output/camt053.csv
```

XAF files may declare ISO-8859-1 while containing UTF-8. Reuse `load_auditfile_text` rather than adding another decoder. `AUDITLOG_XAF_PATH` accepts a file, directory, or glob. Use `BIND_HOST` and `BIND_PORT` for the server bind address.

## Rules

- Run the frontend build and complete test suite after changes.
- Keep web routes read-only and escape/validate file-derived values at trust boundaries.
- Never commit `.env`, credentials, real exports, generated static assets, logs, or output.
- Use Conventional Commits. Release Please publishes GitHub releases and GHCR containers, not Python packages.
- Commit all completed intended changes and leave a clean working tree.
