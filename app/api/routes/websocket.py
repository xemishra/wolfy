import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import db
from app.dependencies.session import user_for_ws
from app.services.chat import total_unread, unread_map
from app.services.matchmaker import matchmaker
from app.services.websocket_handlers import (end_random_disconnect,
                                             handle_ws_message)
from app.services.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = ""):
    user = await user_for_ws(token, ws.cookies)
    if not user:
        await ws.close(code=4001)
        return

    uid = user["uid"]
    await ws.accept()
    became_online = manager.connect(uid, ws)
    await db.users.update_one({"uid": uid}, {"$set": {"online": True}})
    logger.info(f"[WS] {user['username']} online")
    if became_online:
        await manager.broadcast_presence(uid, True)

    fresh = await db.users.find_one({"uid": uid}) or user
    await manager.send(
        uid,
        {
            "type": "unread_sync",
            "unread": unread_map(fresh),
            "total": total_unread(fresh),
        },
    )

    contact_uids = list(fresh.get("contacts") or [])
    if contact_uids:
        online_contacts = manager.online_among(contact_uids)
        for cuid in contact_uids:
            await manager.send(
                uid,
                {
                    "type": "presence",
                    "uid": cuid,
                    "online": cuid in online_contacts,
                },
            )

    try:
        while True:
            try:
                data = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await manager.send(
                    uid, {"type": "error", "message": "Invalid message format"}
                )
                continue
            user = await db.users.find_one({"uid": uid}) or user
            await handle_ws_message(uid, user, data)
    except WebSocketDisconnect:
        pass
    finally:
        if manager.will_disconnect_fully(uid):
            peer_uid = manager.random_peer(uid)
            if peer_uid:
                stale_sid = end_random_disconnect(uid, peer_uid)
                await manager.send(
                    peer_uid,
                    {
                        "type": "peer_disconnected",
                        "session_id": stale_sid,
                    },
                )
                peer_user = await db.users.find_one({"uid": peer_uid})
                if peer_user:
                    await matchmaker.enqueue(peer_uid, peer_user, manager)

        went_offline = manager.disconnect(uid, ws)
        matchmaker.cancel(uid)
        if went_offline:
            await db.users.update_one({"uid": uid}, {"$set": {"online": False}})
            await manager.broadcast_presence(uid, False)
        logger.info(f"[WS] {user['username']} offline")
