from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

STATIC_DIR = Path("static")


@router.get("/robots.txt")
async def robots():
    return FileResponse(STATIC_DIR / "robots.txt")


@router.get("/sitemap.xml")
async def sitemap():
    return FileResponse(STATIC_DIR / "sitemap.xml")
