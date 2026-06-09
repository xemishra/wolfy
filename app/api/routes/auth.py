import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo.errors import DuplicateKeyError

from app.core.database import db
from app.dependencies.session import (
    clear_pending_cookie,
    clear_session_cookie,
    get_pending,
    set_pending_cookie,
    set_session,
    template_ctx,
)
from app.dependencies.templates import templates
from app.services.auth import verify_token
from app.services.email import send_welcome_email
from app.utils.validators import USERNAME_RE

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/session/set")
async def session_set(request: Request, id_token: str = Form(...)):
    decoded = await verify_token(id_token)
    if not decoded:
        return templates.TemplateResponse(
            "login.html",
            template_ctx(request, error="Invalid Google token. Please try again."),
            status_code=401,
        )

    user = await db.users.find_one({"firebase_uid": decoded["uid"]})
    if user:
        resp = RedirectResponse("/home", status_code=302)
        set_session(resp, user["uid"])
        return resp

    resp = RedirectResponse("/onboard", status_code=302)
    set_pending_cookie(
        resp,
        {
            "firebase_uid": decoded["uid"],
            "email": decoded.get("email", ""),
            "photo_url": decoded.get("picture", ""),
        },
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    resp = RedirectResponse("/", status_code=302)
    clear_session_cookie(resp)
    return resp


@router.get("/onboard", response_class=HTMLResponse)
async def onboard_page(request: Request):
    if not get_pending(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("onboard.html", template_ctx(request))


@router.get("/onboard/check-username")
async def check_username(request: Request, username: str = ""):
    if not get_pending(request):
        return {"available": False, "reason": "unauthorized"}
    username = username.lower().strip()
    if not USERNAME_RE.match(username):
        return {"available": False, "reason": "invalid"}
    exists = await db.users.find_one({"username": username})
    return {"available": exists is None}


@router.post("/onboard/register", response_class=HTMLResponse)
async def onboard_register(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    dob: str = Form(...),
):
    pending = get_pending(request)
    if not pending:
        return RedirectResponse("/", status_code=302)

    try:
        age = (datetime.utcnow() - datetime.fromisoformat(dob)).days / 365.25
    except ValueError:
        age = 0
    if age < 13:
        return templates.TemplateResponse(
            "onboard.html",
            template_ctx(request, error="You must be at least 13 years old."),
        )

    username = username.lower().strip()
    display_name = display_name.strip()[:30]
    if not USERNAME_RE.match(username):
        return templates.TemplateResponse(
            "onboard.html",
            template_ctx(
                request,
                error="Username must be 3–20 characters: letters, numbers, underscore.",
            ),
        )
    if not display_name:
        return templates.TemplateResponse(
            "onboard.html", template_ctx(request, error="Display name is required.")
        )
    if await db.users.find_one({"username": username}):
        return templates.TemplateResponse(
            "onboard.html",
            template_ctx(request, error=f'Username "@{username}" is already taken.'),
        )

    existing = await db.users.find_one({"firebase_uid": pending["firebase_uid"]})
    if existing:
        resp = RedirectResponse("/home", status_code=302)
        set_session(resp, existing["uid"])
        clear_pending_cookie(resp)
        return resp

    doc = {
        "uid": str(uuid.uuid4()),
        "firebase_uid": pending["firebase_uid"],
        "email": pending.get("email", ""),
        "username": username,
        "display_name": display_name,
        "dob": dob,
        "photo_url": pending.get("photo_url", ""),
        "bio": "",
        "contacts": [],
        "unread": {},
        "created_at": datetime.utcnow().isoformat(),
        "online": False,
    }
    try:
        await db.users.insert_one(doc)
    except DuplicateKeyError:
        return templates.TemplateResponse(
            "onboard.html",
            template_ctx(request, error=f'Username "@{username}" is already taken.'),
        )
    logger.info(f"[Register] new user @{username}")

    resp = RedirectResponse("/home", status_code=302)
    set_session(resp, doc["uid"])
    clear_pending_cookie(resp)
    send_welcome_email(doc["email"], doc["display_name"])
    return resp
