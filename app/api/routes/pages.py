from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies.session import current_user, page_context, template_ctx
from app.dependencies.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await current_user(request)
    if user:
        return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse("login.html", template_ctx(request))


@router.get("/home", response_class=HTMLResponse)
async def home_page(request: Request):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    pc = await page_context(request, user)
    return templates.TemplateResponse("home.html", template_ctx(request, **pc))
