"""Frontend shell helpers for the Boekhouding explorer."""

from pathlib import Path

STATIC_APP_DIR = Path(__file__).with_name("static") / "app"


def app_shell_html() -> str:
    """Return the built client shell or a helpful build message."""
    index_path = STATIC_APP_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="nl">
<head><meta charset="utf-8"><title>Boekhouding</title></head>
<body>
  <h1>Boekhouding</h1>
  <p>De lokale frontend is nog niet gebouwd.</p>
  <p>Voer <code>npm ci</code> en <code>npm run build</code> uit en herstart de app.</p>
</body>
</html>"""
