from fastapi import APIRouter

from app.api.routes import (
    auth,
    chat,
    files,
    health,
    legal,
    pages,
    profile,
    seo,
    websocket,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(pages.router, tags=["pages"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(profile.router, tags=["profile"])
api_router.include_router(files.router, prefix="/api", tags=["files"])
api_router.include_router(legal.router, tags=["legal"])
api_router.include_router(websocket.router, tags=["websocket"])
api_router.include_router(seo.router, tags=["seo"])
