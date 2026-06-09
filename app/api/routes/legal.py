from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies.templates import templates

router = APIRouter()


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})
