import logging

from app.config import MAX_MESSAGE_LEN
from app.core.database import db
from app.services.chat import (can_send_message, mark_read, total_unread,
                               unread_map)
from app.services.matchmaker import matchmaker
from app.services.messages import deliver_message
from app.services.websocket_manager import manager
from app.utils.validators import is_valid_uid

logger = logging.getLogger(__name__)


def end_random_disconnect(disconnecting_uid: str, peer_uid: str) -> str | None:
    stale_sid = matchmaker.session_of(disconnecting_uid) or matchmaker.session_of(
        peer_uid
    )
    matchmaker.invalidate_session_pair(disconnecting_uid, peer_uid)
    manager.cancel_keep(disconnecting_uid)
    manager.cancel_keep(peer_uid)
    manager.clear_random_pair(disconnecting_uid)
    return stale_sid


def fire_skip(skipper_uid: str, peer_uid: str):
    matchmaker.invalidate_session_pair(skipper_uid, peer_uid)
    matchmaker.record_skip(skipper_uid, peer_uid)
    manager.cancel_keep(skipper_uid)
    manager.cancel_keep(peer_uid)
    manager.clear_random_pair(skipper_uid)


async def handle_ws_message(uid: str, user: dict, msg: dict):
    t = msg.get("type")
    session_id = msg.get("session_id")

    if t == "message":
        to = msg.get("to_uid", "")
        txt = (msg.get("text") or "").strip()[:MAX_MESSAGE_LEN]
        if not to or not txt:
            return

        random_peer = manager.random_peer(uid)
        if random_peer and random_peer == to:
            if not session_id or not matchmaker.session_valid(uid, session_id):
                logger.debug(
                    f"[Stale] message from {uid} rejected (session {session_id[:8] if session_id else 'missing'})"
                )
                return
            if manager.random_peer(to) != uid:
                logger.debug(
                    f"[Stale] message from {uid} rejected (pair mismatch with {to})"
                )
                return

        reply_to_id = (msg.get("reply_to_id") or "").strip() or None
        result = await deliver_message(
            uid, user, to, text=txt, session_id=session_id, reply_to_id=reply_to_id
        )
        if not result.get("ok"):
            await manager.send(
                uid, {"type": "error", "message": result.get("error", "Send failed")}
            )

    elif t == "find_match":
        if manager.random_peer(uid):
            await manager.send(
                uid,
                {
                    "type": "error",
                    "message": "Already in a chat. Skip first to find someone new.",
                },
            )
            return
        await matchmaker.enqueue(uid, user, manager)

    elif t == "cancel_match":
        matchmaker.cancel(uid)

    elif t == "keep":
        peer_uid = msg.get("peer_uid", "")
        if not peer_uid:
            return

        if manager.random_peer(uid) != peer_uid:
            return

        if not session_id or not matchmaker.session_valid(uid, session_id):
            return

        both_kept = await manager.handle_keep(uid, peer_uid)

        if both_kept:
            logger.info(f"[Keep] Mutual: {uid} <-> {peer_uid} - saving contacts")

            await db.users.update_one(
                {"uid": uid}, {"$addToSet": {"contacts": peer_uid}}
            )
            await db.users.update_one(
                {"uid": peer_uid}, {"$addToSet": {"contacts": uid}}
            )

            matchmaker.invalidate_session_pair(uid, peer_uid)
            manager.clear_random_pair(uid)

            peer_doc = await db.users.find_one({"uid": peer_uid})
            await manager.send(
                uid,
                {
                    "type": "mutual_keep",
                    "peer_uid": peer_uid,
                    "display_name": peer_doc["display_name"] if peer_doc else peer_uid,
                },
            )
            await manager.send(
                peer_uid,
                {
                    "type": "mutual_keep",
                    "peer_uid": uid,
                    "display_name": user["display_name"],
                },
            )
        else:
            logger.info(
                f"[Keep] Pending: {uid} pressed Keep on {peer_uid}, waiting for peer"
            )
            await manager.send(uid, {"type": "keep_pending"})
            await manager.send(peer_uid, {"type": "peer_wants_keep", "by_uid": uid})

    elif t == "skip":
        peer_uid = msg.get("peer_uid", "")
        if not peer_uid:
            return

        if manager.random_peer(uid) != peer_uid:
            await manager.send(
                uid,
                {
                    "type": "error",
                    "message": "Session changed. Please try again.",
                },
            )
            return

        logger.info(f"[Skip] {uid} skipped {peer_uid}")

        stale_sid = matchmaker.session_of(uid)
        fire_skip(uid, peer_uid)

        await manager.send(uid, {"type": "skipped_ok"})
        await manager.send(
            peer_uid,
            {
                "type": "skipped_find_new",
                "session_id": stale_sid,
            },
        )

        peer_user = await db.users.find_one({"uid": peer_uid})
        if peer_user:
            await matchmaker.enqueue(peer_uid, peer_user, manager)

        await matchmaker.enqueue(uid, user, manager)

    elif t == "typing":
        to = msg.get("to_uid", "")
        if not to:
            return

        random_peer = manager.random_peer(uid)

        if random_peer and random_peer == to:
            if not session_id or not matchmaker.session_valid(uid, session_id):
                return
            if manager.random_peer(to) != uid:
                return

        if to and await can_send_message(user, to, random_peer=random_peer):
            typing_payload: dict = {"type": "typing", "from_uid": uid}
            if random_peer and random_peer == to:
                sid = matchmaker.session_of(uid)
                if sid:
                    typing_payload["session_id"] = sid
            await manager.send(to, typing_payload)

    elif t == "viewing_chat":
        peer = msg.get("peer_uid") or None
        if peer and not is_valid_uid(peer):
            peer = None
        if (
            peer
            and peer not in (user.get("contacts") or [])
            and manager.random_peer(uid) != peer
        ):
            peer = None
        manager.set_viewing(uid, peer)
        if peer:
            await mark_read(uid, peer)
        fresh = await db.users.find_one({"uid": uid}) or user
        await manager.send(
            uid,
            {
                "type": "unread_update",
                "from_uid": peer or "",
                "count": 0,
                "total": total_unread(fresh),
                "unread": unread_map(fresh),
            },
        )

    elif t == "mark_read":
        peer = (msg.get("peer_uid") or "").strip()
        if (
            peer
            and is_valid_uid(peer)
            and (
                peer in (user.get("contacts") or []) or manager.random_peer(uid) == peer
            )
        ):
            await mark_read(uid, peer)
        else:
            peer = ""
        fresh = await db.users.find_one({"uid": uid}) or user
        await manager.send(
            uid,
            {
                "type": "unread_update",
                "from_uid": peer,
                "count": 0,
                "total": total_unread(fresh),
                "unread": unread_map(fresh),
            },
        )
