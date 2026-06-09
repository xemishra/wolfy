import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import IS_PRODUCTION
from app.core.database import ensure_indexes
from app.core.paths import ASSETS_DIR, STATIC_DIR
from app.services.attachments import ensure_upload_dir

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    application = FastAPI(
        title="Wolfy",
        version="1.0.0",
        docs_url=None if IS_PRODUCTION else "/docs",
        redoc_url=None if IS_PRODUCTION else "/redoc",
    )

    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
    application.include_router(api_router)

    @application.on_event("startup")
    async def startup():
        await ensure_indexes()
        ensure_upload_dir()
        if IS_PRODUCTION:
            logger.warning(
                "[Startup] Matchmaking/WebSocket state is in-memory. "
                "Run a single uvicorn worker or add Redis for multi-instance deploys."
            )

    return application


app = create_app()
