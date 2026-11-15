"""FastAPI application for the Boekhouding XAF explorer."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from boekhouding.audit_routes import AUDIT_FILE_ENV, create_audit_router
from boekhouding.frontend import STATIC_APP_DIR, app_shell_html

HOST_ENV = "BIND_HOST"
PORT_ENV = "BIND_PORT"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def resolve_host(host: str | None) -> str:
    """Resolve the web server host from an argument, environment, or default."""
    return host or os.getenv(HOST_ENV) or DEFAULT_HOST


def resolve_port(port: int | None) -> int:
    """Resolve the web server port from an argument, environment, or default."""
    value = port if port is not None else os.getenv(PORT_ENV)
    if value in (None, ""):
        return DEFAULT_PORT
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV} must be an integer") from exc


def create_app(*, audit_file: str | Path | None = None) -> FastAPI:
    """Create the XAF explorer application."""
    app = FastAPI(title="Boekhouding", version="0.1.0")
    if audit_file is not None:
        app.state.audit_file = str(audit_file)

    if STATIC_APP_DIR.exists():
        app.mount("/static/app", StaticFiles(directory=STATIC_APP_DIR), name="app-static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def frontpage() -> HTMLResponse:
        return HTMLResponse(app_shell_html())

    app.include_router(create_audit_router())
    return app


app = create_app()


def serve(
    host: str | None = None,
    port: int | None = None,
    audit_file: str | None = None,
    reload: bool = False,
) -> None:
    """Run the local XAF explorer."""
    import uvicorn

    if audit_file:
        os.environ[AUDIT_FILE_ENV] = audit_file
    uvicorn.run(
        "boekhouding.app:app",
        host=resolve_host(host),
        port=resolve_port(port),
        reload=reload,
    )
