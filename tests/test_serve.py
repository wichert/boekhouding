from typer.testing import CliRunner

from boekhouding.app import resolve_host, resolve_port
from boekhouding.cli import app


def test_bind_environment_defaults_and_values(monkeypatch):
    monkeypatch.delenv("BIND_HOST", raising=False)
    monkeypatch.delenv("BIND_PORT", raising=False)
    assert resolve_host(None) == "127.0.0.1"
    assert resolve_port(None) == 8000
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("BIND_PORT", "9001")
    assert resolve_host(None) == "0.0.0.0"
    assert resolve_port(None) == 9001


def test_serve_command_passes_options(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "boekhouding.app.serve",
        lambda **kwargs: calls.append(kwargs),
    )
    result = CliRunner().invoke(
        app,
        ["serve", "--host", "0.0.0.0", "--port", "9002", "--audit-file", str(tmp_path / "audit.xaf")],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 9002
    assert calls[0]["audit_file"].endswith("audit.xaf")
