"""FastAPI routes for the XML audit transaction explorer."""

from __future__ import annotations

import glob
import hashlib
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from boekhouding.audit_parser import parse_audit_file, year_from_path
from boekhouding.auditfile_report import AuditfileError
from boekhouding.frontend import app_shell_html

AUDIT_FILE_ENV = "AUDITLOG_XAF_PATH"
DEFAULT_AUDIT_FILE_PATTERN = "data/auditlog-*.xaf"
DEFAULT_AUDIT_YEAR = "2026"
LEGACY_AUDIT_FILE = "data/auditlog.xaf"
CACHE_CONTROL_NO_CACHE = "no-cache"


def load_app_dotenv() -> None:
    """Load .env from the current working directory when present."""

    load_dotenv(dotenv_path=".env")


def expand_audit_files(value: str) -> list[Path]:
    """Expand an audit path, directory, or glob into sorted XML audit paths."""

    path = Path(value)
    if any(character in value for character in "*?["):
        return sorted(Path(match) for match in glob.glob(value))
    if path.is_dir():
        return sorted(path.glob("auditlog-*.xaf"))
    return [path]


def resolve_audit_files(audit_path: str | None = None) -> list[Path]:
    """Resolve audit XML files from an explicit value, env, or default glob."""

    load_app_dotenv()
    configured = audit_path or os.getenv(AUDIT_FILE_ENV)
    if configured:
        return expand_audit_files(configured)

    discovered = expand_audit_files(DEFAULT_AUDIT_FILE_PATTERN)
    if discovered:
        return discovered
    return expand_audit_files(LEGACY_AUDIT_FILE)


def resolve_audit_file(audit_file: str | None = None) -> Path:
    """Resolve the first audit XML path for backwards-compatible callers."""

    files = resolve_audit_files(audit_file)
    return files[0]


def get_audit_files_from_app(request: Request) -> list[Path]:
    """Resolve audit files for a request."""

    configured = getattr(request.app.state, "audit_file", None)
    return resolve_audit_files(str(configured) if configured else None)


def existing_audit_files(request: Request) -> list[Path]:
    """Return configured audit files that exist and fail on explicit missing files."""

    audit_files = get_audit_files_from_app(request)
    if not audit_files:
        raise HTTPException(status_code=404, detail="No audit files found")

    existing: list[Path] = []
    for audit_file in audit_files:
        if audit_file.exists():
            existing.append(audit_file)
        elif len(audit_files) == 1:
            raise HTTPException(status_code=404, detail=f"Audit file not found: {audit_file}")
    if not existing:
        raise HTTPException(status_code=404, detail="No audit files found")
    return existing


def audit_year_options(request: Request) -> list[dict[str, str]]:
    """Return available audit years without parsing every audit file."""

    options: list[dict[str, str]] = []
    for audit_file in existing_audit_files(request):
        year = year_from_path(audit_file)
        if not year:
            try:
                year = str(parse_audit_file(audit_file)["metadata"].get("year") or "")
            except (ET.ParseError, ValueError):
                year = ""
        if year:
            options.append({"year": year, "filePath": str(audit_file), "fileName": audit_file.name})
    return sorted(options, key=lambda option: option["year"])


def default_year(options: list[dict[str, str]]) -> str:
    """Return the preferred initial audit year."""

    years = [option["year"] for option in options]
    if DEFAULT_AUDIT_YEAR in years:
        return DEFAULT_AUDIT_YEAR
    return years[0] if years else DEFAULT_AUDIT_YEAR


def audit_file_for_year(request: Request, year: str | None) -> Path:
    """Find the configured audit file for the requested year."""

    options = audit_year_options(request)
    selected_year = year or default_year(options)
    for option in options:
        if option["year"] == selected_year:
            return Path(option["filePath"])
    raise HTTPException(status_code=404, detail=f"Audit file for year {selected_year} not found")


def get_cached_audit_data(request: Request, year: str | None = None) -> dict[str, Any]:
    """Return parsed audit data for one year, reparsing when path or mtime changes."""

    audit_file = audit_file_for_year(request, year)
    # If stat() fails here, no ETag was emitted; fail open on the file itself
    # rather than returning a stale 304 keyed on an "unavailable" placeholder.
    try:
        stat = audit_file.stat()
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"Audit file not readable: {audit_file}") from exc

    resolved_path = str(audit_file.resolve())
    key = (resolved_path, stat.st_mtime_ns, stat.st_size)
    cache = getattr(request.app.state, "audit_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        request.app.state.audit_cache = cache

    cached_entry = cache.get(resolved_path)
    if isinstance(cached_entry, dict) and cached_entry.get("key") == key:
        return cached_entry["data"]

    try:
        data = parse_audit_file(audit_file)
    except ET.ParseError as exc:
        raise HTTPException(status_code=500, detail=f"Audit file is not valid XML: {exc}") from exc
    except (ValueError, AuditfileError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    parsed_year = str(data["metadata"].get("year") or year or "")
    file_metadata = dict(data["metadata"])
    data["metadata"]["years"] = [parsed_year] if parsed_year else []
    data["metadata"]["files"] = [file_metadata]
    year_option = {
        "year": parsed_year,
        "fileName": audit_file.name,
        "transactionCount": len(data["transactions"]),
        "numberEntries": int(data["metadata"].get("numberEntries") or 0),
        "totalDebit": data["metadata"].get("totalDebit", 0),
        "totalCredit": data["metadata"].get("totalCredit", 0),
    }
    data["metadata"]["yearOptions"] = [year_option]
    data["yearOptions"] = [year_option]

    cache[resolved_path] = {"key": key, "data": data}
    return data


def audit_file_etag(audit_file: Path, stat: os.StatResult | None = None) -> str | None:
    """Return an ETag derived from the file stat, or None when it cannot be stat'ed."""

    try:
        stat = stat or audit_file.stat()
    except OSError:
        return None
    return f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def years_etag(audit_files: list[Path]) -> str | None:
    """Return an ETag over the file list and stat signals, or None if any stat fails."""

    parts = []
    for audit_file in audit_files:
        try:
            stat = audit_file.stat()
        except OSError:
            return None
        parts.append(f"{audit_file}:{stat.st_mtime_ns:x}-{stat.st_size:x}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f'"{digest}"'


def apply_validation_headers(response: Response, etag: str | None) -> None:
    """Set no-cache validation headers, adding the ETag only when available."""

    response.headers["Cache-Control"] = CACHE_CONTROL_NO_CACHE
    if etag is not None:
        response.headers["ETag"] = etag


def not_modified_response(etag: str) -> Response:
    """Return an empty 304 response carrying the validation headers."""

    response = Response(status_code=304)
    apply_validation_headers(response, etag)
    return response


def transaction_etag(request: Request, year: str | None = None) -> str | None:
    """Return the ETag for the audit file backing one transactions response."""

    audit_file = audit_file_for_year(request, year)
    return audit_file_etag(audit_file)


def transaction_app_html() -> str:
    """Return the unified client-side explorer shell."""

    return app_shell_html()


def create_audit_router() -> APIRouter:
    """Create routes for the audit transaction explorer."""

    router = APIRouter()

    @router.get("/transactions", response_class=HTMLResponse)
    @router.get("/transactions/balance", response_class=HTMLResponse)
    @router.get("/transactions/accounts", response_class=HTMLResponse)
    @router.get("/transactions/bookings", response_class=HTMLResponse)
    @router.get("/transactions/accounts/{account_id}", response_class=HTMLResponse)
    def transactions_page(account_id: str | None = None) -> HTMLResponse:
        return HTMLResponse(transaction_app_html())

    @router.get("/api/audit/years")
    def audit_years(request: Request) -> Response:
        audit_files = existing_audit_files(request)
        etag = years_etag(audit_files)
        if etag is not None and request.headers.get("if-none-match") == etag:
            return not_modified_response(etag)
        options = audit_year_options(request)
        content = JSONResponse({"defaultYear": default_year(options), "years": options})
        apply_validation_headers(content, etag)
        return content

    @router.get("/api/audit/transactions/{year}")
    def audit_transactions_for_year(request: Request, year: str) -> Response:
        etag = transaction_etag(request, year)
        if etag is not None and request.headers.get("if-none-match") == etag:
            return not_modified_response(etag)
        data = get_cached_audit_data(request, year)
        content = JSONResponse(data)
        apply_validation_headers(content, etag)
        return content

    @router.get("/api/audit/transactions")
    def audit_transactions_default(request: Request) -> Response:
        etag = transaction_etag(request)
        if etag is not None and request.headers.get("if-none-match") == etag:
            return not_modified_response(etag)
        data = get_cached_audit_data(request)
        content = JSONResponse(data)
        apply_validation_headers(content, etag)
        return content

    return router
