"""Serve the built web console from the API itself, for a one-container deployment.

Behind nginx (docker-compose.prod.yml) this is not used. A host that runs one container, such
as a free web service, has the API serve the console's files too: set ``MANDATE_STATIC_DIR`` to
the build (``ui/dist``). The console and the API then share an origin, so the session cookie
needs no proxy, and unknown paths load the single-page app, which routes them.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

# What nginx adds in the multi-container setup (ui/nginx.conf.template).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
API_PREFIXES = ("v1/", "v1")


def install_console(app: FastAPI, directory: Path) -> None:
    """Add the catch-all route. Call after every other route, so none of them is shadowed."""
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"MANDATE_STATIC_DIR has no index.html: {root}")

    @app.get("/{path:path}", include_in_schema=False)
    def console(path: str) -> Response:
        if path.startswith(API_PREFIXES):
            # An API path that does not exist is a 404 in the API's own format, not the app.
            return JSONResponse(
                {"error": {"code": "not_found", "message": "no such route"}}, status_code=404
            )
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            # Built assets carry a content hash in their name, so they never change.
            cache = (
                "public, max-age=2592000, immutable" if path.startswith("assets/") else "no-cache"
            )
            return FileResponse(target, headers={**SECURITY_HEADERS, "Cache-Control": cache})
        return FileResponse(index, headers={**SECURITY_HEADERS, "Cache-Control": "no-cache"})
