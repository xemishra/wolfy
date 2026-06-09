from __future__ import annotations

from app.core.database import db
from app.services.attachments import message_preview
from app.utils.validators import is_valid_uid


def unread_map(user: dict) -> dict[str, int]:
    raw = user.get("unread") or {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        if not is_valid_uid(k):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[k] = n
    return out


def total_unread(user: dict) -> int:
    return sum(unread_map(user).values())


async def increment_unread(recipient_uid: str, sender_uid: str) -> int:
    if not is_valid_uid(recipient_uid) or not is_valid_uid(sender_uid):
        return 0
    key = f"unread.{sender_uid}"
    await db.users.update_one(
        {"uid": recipient_uid},
        {"$inc": {key: 1}},
    )
    doc = await db.users.find_one({"uid": recipient_uid}, {"unread": 1}) or {}
    return int((doc.get("unread") or {}).get(sender_uid, 0))


async def mark_read(user_uid: str, peer_uid: str) -> None:
    if not is_valid_uid(user_uid) or not is_valid_uid(peer_uid):
        return
    await db.users.update_one(
        {"uid": user_uid},
        {"$unset": {f"unread.{peer_uid}": ""}},
    )


async def get_last_previews(user_uid: str, contact_uids: list[str]) -> dict[str, dict]:
    contact_uids = [u for u in contact_uids if is_valid_uid(u)]
    if not contact_uids:
        return {}

    pipeline = [
        {
            "$match": {
                "$or": [
                    {"from_uid": user_uid, "to_uid": {"$in": contact_uids}},
                    {"from_uid": {"$in": contact_uids}, "to_uid": user_uid},
                ]
            }
        },
        {
            "$addFields": {
                "peer": {
                    "$cond": [
                        {"$eq": ["$from_uid", user_uid]},
                        "$to_uid",
                        "$from_uid",
                    ]
                }
            }
        },
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": "$peer",
                "text": {"$first": "$text"},
                "msg_type": {"$first": {"$ifNull": ["$msg_type", "text"]}},
                "attachment": {"$first": "$attachment"},
                "timestamp": {"$first": "$timestamp"},
                "from_uid": {"$first": "$from_uid"},
            }
        },
        {"$limit": max(len(contact_uids), 1)},
    ]

    previews: dict[str, dict] = {}
    async for row in db.messages.aggregate(pipeline):
        peer = row.get("_id")
        if not peer or peer in previews:
            continue
        msg_type = row.get("msg_type") or "text"
        previews[peer] = {
            "text": message_preview(
                msg_type, row.get("attachment"), row.get("text") or ""
            ),
            "timestamp": row.get("timestamp") or "",
            "is_me": row.get("from_uid") == user_uid,
        }
    return previews


async def build_contacts(
    user: dict,
    online_fn,
    *,
    active_peer_uid: str | None = None,
) -> list[dict]:
    contact_uids = [u for u in (user.get("contacts") or []) if is_valid_uid(u)]
    if not contact_uids:
        return []

    users_by_uid: dict[str, dict] = {}
    async for u in db.users.find({"uid": {"$in": contact_uids}}):
        users_by_uid[u["uid"]] = u

    unread = unread_map(user)
    previews = await get_last_previews(user["uid"], contact_uids)

    online_set = (
        online_fn.online_among(contact_uids)
        if hasattr(online_fn, "online_among")
        else {u for u in contact_uids if online_fn(u)}
    )

    rows: list[dict] = []
    for uid in contact_uids:
        u = users_by_uid.get(uid)
        if not u:
            continue
        prev = previews.get(uid, {})
        preview_text = prev.get("text", "")
        if preview_text and prev.get("is_me"):
            preview_text = f"You: {preview_text}"
        display_name = (u.get("display_name") or u.get("username") or "User").strip()
        rows.append(
            {
                "uid": uid,
                "username": u["username"],
                "display_name": display_name,
                "photo_url": u.get("photo_url", ""),
                "online": uid in online_set,
                "unread": unread.get(uid, 0),
                "last_message": (
                    preview_text[:80] if preview_text else f"@{u['username']}"
                ),
                "last_ts": prev.get("timestamp", ""),
                "active": uid == active_peer_uid,
            }
        )

    rows.sort(key=lambda c: (c["unread"], c["last_ts"] or ""), reverse=True)
    return rows


async def can_send_message(
    sender: dict, to_uid: str, *, random_peer: str | None
) -> bool:
    if not is_valid_uid(to_uid):
        return False
    if to_uid in (sender.get("contacts") or []):
        return True
    if random_peer and random_peer == to_uid:
        return True
    return False
