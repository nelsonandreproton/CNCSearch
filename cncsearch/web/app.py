"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import Config
from ..database.repository import Repository
from ..search.service import SearchService
from ..web.auth import hash_password
from .routes import auth, canticos, momentos, paroquia_pub, search, settings

logger = logging.getLogger(__name__)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config.from_env()

    # Apply log level from config to root logger
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    os.makedirs(os.path.dirname(os.path.abspath(config.database_path)), exist_ok=True)

    repo = Repository(config.database_path)

    # Hash and store initial password on first run
    initial_hash = ""
    if config.web_initial_password:
        initial_hash = hash_password(config.web_initial_password)
    repo.init_database(initial_password_hash=initial_hash)

    search_svc = SearchService(config, repo)

    app.state.config = config
    app.state.repo = repo
    app.state.search = search_svc

    logger.info("CNCSearch web started (db=%s)", config.database_path)
    yield
    logger.info("CNCSearch web stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="CNCSearch", lifespan=lifespan)
    app.add_middleware(_SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    app.include_router(auth.router)
    app.include_router(canticos.router)
    app.include_router(momentos.router)
    app.include_router(settings.router)
    app.include_router(search.router)
    app.include_router(paroquia_pub.router)  # public — no auth

    # Root redirect
    from fastapi.responses import RedirectResponse

    @app.get("/")
    async def root():
        return RedirectResponse("/canticos")

    return app


app = create_app()
