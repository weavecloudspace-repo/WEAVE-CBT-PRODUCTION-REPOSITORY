from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

WEB_ROOT = Path(os.getenv("WEAVE_WEB_ROOT", "/app/web")).resolve()


def register_frontend_routes(app: FastAPI) -> None:
    """Serve the built staff and student React applications."""

    staff_root = WEB_ROOT / "staff"
    student_root = WEB_ROOT / "student"

    # In normal development Vite serves the frontend,
    # so frontend/dist may not exist. Do nothing in that case.
    if staff_root.is_dir():
        _register_spa(app, "/staff", staff_root)

    if student_root.is_dir():
        _register_spa(app, "/student", student_root)


def _register_spa(
    app: FastAPI,
    prefix: str,
    root: Path,
) -> None:
    """Register one React SPA with deep-link fallback."""

    index_file = root / "index.html"

    @app.get(prefix, include_in_schema=False)
    @app.get(f"{prefix}/{{path:path}}", include_in_schema=False)
    async def serve_spa(path: str = ""):
        requested_file = (root / path).resolve()

        # Only serve files that actually belong inside this frontend directory.
        try:
            requested_file.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=404)

        # Real asset: JS, CSS, image, etc.
        if requested_file.is_file():
            return FileResponse(requested_file)

        # Otherwise let React Router handle the URL.
        if index_file.is_file():
            return FileResponse(index_file)

        raise HTTPException(status_code=404)
