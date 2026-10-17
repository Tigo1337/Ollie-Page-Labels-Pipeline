"""FastAPI app: the JSON API under /api plus the built React frontend."""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from engine.art import ArtError
from engine.orders import OrderError
from engine.render import RenderError
from engine.text import FontError, GlyphError

from .db import make_session_factory
from .engine_service import EngineService
from .repo import NotFound, Repo
from .settings import Settings, load_settings
from .storage import BlobNotFound, make_store

log = logging.getLogger("labels")
AUTH_COOKIE = "labels_auth"
OPEN_PATHS = {"/api/health", "/api/auth", "/api/login", "/api/logout"}


def auth_token(secret: str) -> str:
    return hmac.new(secret.encode(), b"label-pipeline-session", hashlib.sha256).hexdigest()


def create_app(settings: Settings | None = None, start_font_download: bool = True) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = make_store(settings.storage, settings.data_dir)
    repo = Repo(make_session_factory(settings.database_url), store)
    if repo.seed(settings.config_dir):
        log.info("Seeded the database from %s", settings.config_dir)
    repo.ensure_defaults()
    svc = EngineService(repo, store, settings.cache_dir, settings.config_dir)

    app = FastAPI(title="Label Pipeline", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.repo = repo
    app.state.svc = svc
    app.state.store = store
    app.state.font_job = {"running": False, "report": []}

    # -- auth: one shared secret (Replit Secret LABELS_API_SECRET) -------------
    @app.middleware("http")
    async def require_secret(request: Request, call_next):
        path = request.url.path
        if settings.api_secret and path.startswith("/api/") and path not in OPEN_PATHS:
            token = auth_token(settings.api_secret)
            cookie = request.cookies.get(AUTH_COOKIE, "")
            header = request.headers.get("x-api-key", "")
            if not (hmac.compare_digest(cookie, token) or
                    (header and hmac.compare_digest(header, settings.api_secret))):
                return JSONResponse({"detail": "Please log in."}, status_code=401)
        return await call_next(request)

    # -- plain-language errors, never a stack trace -------------------------
    def _err(status: int):
        async def handler(_request: Request, exc: Exception):
            return JSONResponse({"detail": str(exc), "kind": type(exc).__name__}, status_code=status)
        return handler

    for exc_type in (ArtError, OrderError, RenderError, FontError, GlyphError, ValueError):
        app.add_exception_handler(exc_type, _err(400))
    for exc_type in (NotFound, BlobNotFound):
        app.add_exception_handler(exc_type, _err(404))

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception):
        log.exception("Unexpected error")
        return JSONResponse({"detail": f"Something went wrong ({type(exc).__name__}). "
                                       "The details are in the server log.", "kind": "internal"},
                            status_code=500)

    from .api import router
    app.include_router(router, prefix="/api")

    # -- frontend -----------------------------------------------------------
    dist = settings.frontend_dist

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            return FileResponse(f)
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"},
                            status_code=503)

    if start_font_download:
        def _fonts():
            try:
                missing = [f for f in svc.font_status() if not f["installed"]]
                if missing:
                    app.state.font_job["running"] = True
                    app.state.font_job["report"] = svc.download_fonts()
            except Exception:
                log.exception("Automatic font download failed")
            finally:
                app.state.font_job["running"] = False
        threading.Thread(target=_fonts, daemon=True).start()

    return app


def _app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()


app = None  # created by uvicorn via --factory app.main:_app_factory

if __name__ == "__main__":  # pragma: no cover
    import os

    import uvicorn
    uvicorn.run("app.main:_app_factory", factory=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
