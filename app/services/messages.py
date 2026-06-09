import uuid
from datetime import datetime

from bson import ObjectId

from app.config import MAX_MESSAGE_LEN
from app.core.database import db
from app.services.attachments import message_preview
from app.services.chat import can_send_message, increment_unread, total_unread
from app.services.matchmaker import matchmaker
from app.services.websocket_manager import manager
from app.utils.text import preview_snippet


def message_id_of(m: dict) -> str:
    if m.get("message_id"):
        return m["message_id"]
    oid = m.get("_id")
    return str(oid) if oid is not None else ""


def reply_display_text(msg_type: str, text: str, attachment: dict | None) -> str:
    if text and text.strip():
        return preview_snippet(text, 80)
    if msg_type == "image":
        return "Photo"
    if msg_type == "file" and attachment:
        return attachment.get("filename") or "File"
    return "Message"


def reply_for_viewer(
    reply_snap: dict, viewer_uid: str, peer_uid: str, peer_name: str
) -> dict:
    rt = dict(reply_snap)
    from_uid = rt.get("from_uid")
    if from_uid == viewer_uid:
        rt["sender_label"] = "You"
    elif from_uid == peer_uid:
        rt["sender_label"] = peer_name
    return rt


async def resolve_reply_snapshot(
    uid: str,
    to_uid: str,
    reply_to_id: str | None,
    *,
    peer_display_name: str = "User",
) -> tuple[dict | None, str | None]:
    if not reply_to_id:
        return None, None

    rid = (reply_to_id or "").strip()
    if not rid:
        return None, None

    original = await db.messages.find_one({"message_id": rid})
    if not original and ObjectId.is_valid(rid):
        original = await db.messages.find_one({"_id": ObjectId(rid)})

    if rid.startswith("local-"):
        return None, "Reply target not ready yet, wait a moment and try again"

    if not original:
        return None, "Original message not found"

    participants = {original["from_uid"], original["to_uid"]}
    if participants != {uid, to_uid}:
        return None, "Invalid reply reference"

    from_uid = original["from_uid"]
    sender_label = "You" if from_uid == uid else peer_display_name
    msg_type = original.get("msg_type") or "text"
    text = original.get("text") or ""
    attachment = original.get("attachment")

    snap: dict = {
        "message_id": message_id_of(original),
        "from_uid": from_uid,
        "sender_label": sender_label,
        "msg_type": msg_type,
        "text": reply_display_text(msg_type, text, attachment),
        "unavailable": False,
    }
    if msg_type in ("image", "file") and attachment:
        snap["attachment"] = {
            "file_id": attachment.get("file_id"),
            "filename": attachment.get("filename"),
        }
    return snap, None


async def hydrate_reply_snapshot(
    reply_snap: dict,
    viewer_uid: str,
    peer_uid: str,
    *,
    peer_name: str = "User",
) -> dict:
    rt = dict(reply_snap)
    rid = (rt.get("message_id") or "").strip()
    if not rid or rid.startswith("local-"):
        return rt

    original = await db.messages.find_one({"message_id": rid})
    if not original and ObjectId.is_valid(rid):
        original = await db.messages.find_one({"_id": ObjectId(rid)})

    if not original:
        return rt

    participants = {original["from_uid"], original["to_uid"]}
    if participants != {viewer_uid, peer_uid}:
        return rt

    from_uid = original["from_uid"]
    msg_type = original.get("msg_type") or "text"
    text = original.get("text") or ""
    attachment = original.get("attachment")

    fresh: dict = {
        "message_id": message_id_of(original),
        "from_uid": from_uid,
        "sender_label": "You" if from_uid == viewer_uid else peer_name,
        "msg_type": msg_type,
        "text": reply_display_text(msg_type, text, attachment),
        "unavailable": False,
    }
    if msg_type in ("image", "file") and attachment:
        fresh["attachment"] = {
            "file_id": attachment.get("file_id"),
            "filename": attachment.get("filename"),
        }
    return fresh


async def serialize_message(
    m: dict, viewer_uid: str, *, peer_name: str = "User"
) -> dict:
    att = m.get("attachment")
    msg_type = m.get("msg_type") or "text"
    peer_uid = m["to_uid"] if m["from_uid"] == viewer_uid else m["from_uid"]
    text = (m.get("text") or "").strip()
    out = {
        "message_id": message_id_of(m),
        "from_uid": m["from_uid"],
        "text": text,
        "timestamp": m["timestamp"],
        "is_me": m["from_uid"] == viewer_uid,
        "msg_type": msg_type,
        "attachment": att,
    }
    reply_to = m.get("reply_to")
    if reply_to:
        rt = await hydrate_reply_snapshot(
            reply_to, viewer_uid, peer_uid, peer_name=peer_name
        )
        if rt.get("from_uid") == viewer_uid:
            rt["sender_label"] = "You"
        elif not rt.get("sender_label"):
            rt["sender_label"] = peer_name
        out["reply_to"] = rt
    return out


async def validate_outgoing(
    uid: str, user: dict, to_uid: str, session_id: str | None
) -> str | None:
    random_peer = manager.random_peer(uid)
    if random_peer and random_peer == to_uid:
        if not session_id or not matchmaker.session_valid(uid, session_id):
            return "__stale__"
        if manager.random_peer(to_uid) != uid:
            return "__stale__"
    if not await can_send_message(user, to_uid, random_peer=random_peer):
        return "__denied__"
    return random_peer


async def notify_unread(recipient_uid: str, sender_uid: str, count: int, total: int):
    from app.services.chat import unread_map

    recipient = await db.users.find_one({"uid": recipient_uid}, {"unread": 1}) or {}
    await manager.send(
        recipient_uid,
        {
            "type": "unread_update",
            "from_uid": sender_uid,
            "count": count,
            "total": total,
            "unread": unread_map(recipient),
        },
    )


async def deliver_message(
    uid: str,
    user: dict,
    to_uid: str,
    *,
    text: str = "",
    msg_type: str = "text",
    attachment: dict | None = None,
    session_id: str | None = None,
    reply_to_id: str | None = None,
    peer_display_name: str | None = None,
) -> dict:
    random_peer = await validate_outgoing(uid, user, to_uid, session_id)
    if random_peer == "__stale__":
        return {"ok": False, "error": "Session expired"}
    if random_peer == "__denied__":
        return {
            "ok": False,
            "error": "You can only message contacts or your current match.",
        }

    if peer_display_name is None:
        peer_doc = await db.users.find_one({"uid": to_uid}, {"display_name": 1})
        peer_display_name = (peer_doc or {}).get("display_name") or "User"

    reply_snap, reply_err = await resolve_reply_snapshot(
        uid, to_uid, reply_to_id, peer_display_name=peer_display_name
    )
    if reply_err:
        return {"ok": False, "error": reply_err}

    ts = datetime.utcnow().isoformat()
    preview = message_preview(msg_type, attachment, text)
    message_id = str(uuid.uuid4())

    doc = {
        "message_id": message_id,
        "from_uid": uid,
        "to_uid": to_uid,
        "timestamp": ts,
        "msg_type": msg_type,
        "text": (text or "").strip()[:MAX_MESSAGE_LEN],
        "attachment": attachment,
    }
    if reply_snap:
        doc["reply_to"] = reply_snap
    await db.messages.insert_one(doc)

    payload = {
        "type": "message",
        "message_id": message_id,
        "from_uid": uid,
        "to_uid": to_uid,
        "text": doc["text"],
        "timestamp": ts,
        "msg_type": msg_type,
        "attachment": attachment,
        "display_name": user["display_name"],
        "photo_url": user.get("photo_url", ""),
        "preview": preview,
    }
    if reply_snap:
        payload["reply_to"] = reply_for_viewer(
            reply_snap, to_uid, uid, user["display_name"]
        )
    if random_peer and random_peer == to_uid:
        sid = matchmaker.session_of(uid)
        if sid:
            payload["session_id"] = sid

    await manager.send(to_uid, payload)

    is_contact = to_uid in (user.get("contacts") or [])
    if is_contact and not manager.is_viewing(to_uid, uid):
        count = await increment_unread(to_uid, uid)
        recipient = await db.users.find_one({"uid": to_uid}, {"unread": 1}) or {}
        total = total_unread(recipient)
        await notify_unread(to_uid, uid, count, total)

    ack = {
        "type": "message_ack",
        "message_id": message_id,
        "to_uid": to_uid,
        "timestamp": ts,
        "preview": preview,
        "msg_type": msg_type,
        "attachment": attachment,
    }
    if reply_snap:
        ack["reply_to"] = reply_for_viewer(reply_snap, uid, to_uid, peer_display_name)
    await manager.send(uid, ack)
    result = {
        "ok": True,
        "message_id": message_id,
        "timestamp": ts,
        "msg_type": msg_type,
        "attachment": attachment,
    }
    if reply_snap:
        result["reply_to"] = reply_snap
    return result
