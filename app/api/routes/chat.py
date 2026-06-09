from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.database import db
from app.dependencies.session import current_user, page_context, template_ctx
from app.dependencies.templates import templates
from app.services.chat import mark_read
from app.services.messages import serialize_message
from app.services.websocket_manager import manager
from app.utils.validators import is_valid_uid

router = APIRouter()


@router.get("/chat/{peer_uid}", response_class=HTMLResponse)
async def chat_page(peer_uid: str, request: Request):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    if not is_valid_uid(peer_uid):
        return RedirectResponse("/home", status_code=302)

    peer = await db.users.find_one({"uid": peer_uid})
    if not peer:
        return RedirectResponse("/home", status_code=302)

    if peer_uid not in (user.get("contacts") or []):
        return RedirectResponse("/home", status_code=302)

    await mark_read(user["uid"], peer_uid)
    user = await db.users.find_one({"uid": user["uid"]}) or user

    messages = []
    async for m in (
        db.messages.find(
            {
                "$or": [
                    {"from_uid": user["uid"], "to_uid": peer_uid},
                    {"from_uid": peer_uid, "to_uid": user["uid"]},
                ]
            }
        )
        .sort("timestamp", 1)
        .limit(200)
    ):
        messages.append(
            await serialize_message(m, user["uid"], peer_name=peer["display_name"])
        )

    pc = await page_context(request, user, active_peer_uid=peer_uid)
    return templates.TemplateResponse(
        "chat.html",
        template_ctx(
            request,
            peer=peer,
            messages=messages,
            peer_online=manager.online(peer_uid),
            **pc,
        ),
    )
