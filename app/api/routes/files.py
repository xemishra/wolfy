import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core.database import db
from app.dependencies.session import current_user
from app.services.attachments import resolve_stored_path, save_chat_upload
from app.services.messages import deliver_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat/upload")
async def chat_upload(
    request: Request,
    to_uid: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008
    session_id: str = Form(""),
    caption: str = Form(""),
    reply_to_id: str = Form(""),
):
    user = await current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not logged in"}, status_code=401)

    uid = user["uid"]
    to_uid = (to_uid or "").strip()
    if not to_uid:
        return JSONResponse(
            {"ok": False, "error": "Missing recipient"}, status_code=400
        )

    sid = (session_id or "").strip() or None
    try:
        _fid, msg_type, attachment = await save_chat_upload(file)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.warning("[Upload] failed: %s", exc)
        return JSONResponse({"ok": False, "error": "Upload failed"}, status_code=500)

    rid = (reply_to_id or "").strip() or None
    result = await deliver_message(
        uid,
        user,
        to_uid,
        text=(caption or "").strip(),
        msg_type=msg_type,
        attachment=attachment,
        session_id=sid,
        reply_to_id=rid,
    )
    if not result.get("ok"):
        p = resolve_stored_path(attachment["file_id"], attachment.get("ext", ""))
        if p:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        return JSONResponse(
            result,
            status_code=403 if "only message" in result.get("error", "") else 400,
        )

    return {
        "ok": True,
        "msg_type": msg_type,
        "attachment": attachment,
        "timestamp": result["timestamp"],
        "message_id": result.get("message_id"),
        "reply_to": result.get("reply_to"),
    }


@router.get("/files/{file_id}")
async def get_chat_file(file_id: str, request: Request):
    user = await current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not logged in"}, status_code=401)

    uid = user["uid"]
    msg = await db.messages.find_one(
        {
            "attachment.file_id": file_id,
            "$or": [{"from_uid": uid}, {"to_uid": uid}],
        }
    )
    if not msg:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)

    att = msg.get("attachment") or {}
    path = resolve_stored_path(file_id, att.get("ext", ""))
    if not path:
        return JSONResponse({"ok": False, "error": "File missing"}, status_code=404)

    return FileResponse(
        path,
        media_type=att.get("mime") or "application/octet-stream",
        filename=att.get("filename") or "download",
    )
