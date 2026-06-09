import logging
import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.database import db
from app.dependencies.session import current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/profile/edit", response_class=HTMLResponse)
async def profile_edit(
    request: Request, display_name: str = Form(...), bio: str = Form("")
):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    name = display_name.strip()[:30]
    if not name:
        return RedirectResponse("/home", status_code=302)
    await db.users.update_one(
        {"uid": user["uid"]},
        {"$set": {"display_name": name, "bio": bio.strip()[:150]}},
    )
    return RedirectResponse("/home", status_code=302)


@router.post("/profile/photo")
async def profile_photo(request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not logged in"}, status_code=401)
    try:
        body = await request.json()
        data_url = body.get("data_url", "")
        if not re.match(r"^data:image/(jpeg|png|gif|webp);base64,", data_url):
            return {"ok": False, "error": "Invalid image format"}
        if len(data_url) > 2_800_000:
            return {"ok": False, "error": "Image too large (max ~2MB)"}
        await db.users.update_one(
            {"uid": user["uid"]}, {"$set": {"photo_url": data_url}}
        )
        return {"ok": True, "photo_url": data_url}
    except Exception as e:
        logger.warning(f"[Photo] Upload error: {e}")
        return {"ok": False, "error": "Upload failed"}


@router.post("/profile/photo/remove")
async def profile_photo_remove(request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not logged in"}, status_code=401)
    await db.users.update_one({"uid": user["uid"]}, {"$set": {"photo_url": ""}})
    return {"ok": True}


@router.post("/contacts/keep")
async def keep_contact_http(request: Request, peer_uid: str = Form("")):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    return JSONResponse(
        {
            "ok": False,
            "error": "Use the Keep button during a random chat to add contacts.",
        },
        status_code=403,
    )
