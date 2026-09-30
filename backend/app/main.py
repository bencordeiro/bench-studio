"""FastAPI application factory and lifespan wiring."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import benchmarks, endpoints, health, leaderboards, runs
from app.core.config import APP_NAME, APP_VERSION, get_settings
from app.core.security import configure_logging
from app.db.session import session_scope
from app.jobs.engine import mark_interrupted_active_runs
from app.jobs.runner import runner
from app.seed.suites_loader import seed_bundled_suites
from app.services.scoring_repair import repair_saved_run_scores

log = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("%s %s starting", APP_NAME, APP_VERSION)
    settings = get_settings()
    # Apply migrations on startup (idempotent).
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    command.upgrade(cfg, "head")
    log.info("Database migrations applied")

    with session_scope() as session:
        interrupted = mark_interrupted_active_runs(session)
        if interrupted:
            log.warning("Marked %d active run(s) as interrupted", interrupted)
        # Seed curated suites unless disabled.
        if os.environ.get("LOCALBENCH_NO_SEED") != "1":
            bundled = seed_bundled_suites(session)
            if bundled:
                log.info("Seeded %d bundled suite(s)", bundled)

    repaired = repair_saved_run_scores()
    if repaired:
        log.info("Recalculated %d saved run(s) with failed attempts counted as zero", repaired)
    runner.start()
    log.info("Startup complete. Listening on http://%s:%s", settings.host, settings.port)
    yield
    log.info("Shutting down")
    runner.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Permissive CORS for dev (Vite on another port). Production serves SPA.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(endpoints.router)
    app.include_router(benchmarks.router)
    app.include_router(runs.router)
    app.include_router(leaderboards.router)

    # Serve compiled frontend if present.
    if FRONTEND_DIR.exists():
        assets_dir = FRONTEND_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(FRONTEND_DIR / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Don't shadow API routes (already mounted under /api).
            if full_path.startswith("api"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = FRONTEND_DIR / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
