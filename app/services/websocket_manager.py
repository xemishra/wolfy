import asyncio
import json
import logging

from fastapi import WebSocket

from app.core.database import db

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}
        self._conn_counts: dict[str, int] = {}
        self.random_pairs: dict[str, str] = {}
        self.viewing_chat: dict[str, str | None] = {}
        self._pending_keeps: dict[str, str] = {}
        self._keep_locks: dict[str, asyncio.Lock] = {}

    def connect(self, uid: str, ws: WebSocket) -> bool:
        was_online = self._conn_counts.get(uid, 0) > 0
        self._conn_counts[uid] = self._conn_counts.get(uid, 0) + 1
        self.active.setdefault(uid, []).append(ws)
        return not was_online

    def disconnect(self, uid: str, ws: WebSocket | None = None) -> bool:
        count = self._conn_counts.get(uid, 0)
        if count <= 0:
            return False
        self._conn_counts[uid] = count - 1
        going_offline = self._conn_counts[uid] <= 0
        if going_offline:
            self._conn_counts.pop(uid, None)

        if ws and uid in self.active:
            try:
                self.active[uid].remove(ws)
            except ValueError:
                pass
            if not self.active[uid]:
                del self.active[uid]
        elif going_offline:
            self.active.pop(uid, None)

        if going_offline:
            self.viewing_chat.pop(uid, None)
            self.clear_random_pair(uid)
            self._pending_keeps.pop(uid, None)
            self._keep_locks.pop(uid, None)
        return going_offline

    def online(self, uid: str) -> bool:
        return self._conn_counts.get(uid, 0) > 0

    def online_among(self, uids: list[str]) -> set[str]:
        return {u for u in uids if self.online(u)}

    def will_disconnect_fully(self, uid: str) -> bool:
        return self._conn_counts.get(uid, 0) <= 1

    async def broadcast_presence(self, uid: str, is_online: bool):
        user = await db.users.find_one({"uid": uid}, {"contacts": 1})
        if not user:
            return
        contact_uids = list(user.get("contacts") or [])
        if not contact_uids:
            return
        payload = {"type": "presence", "uid": uid, "online": is_online}
        for cuid in contact_uids:
            if self.online(cuid):
                await self.send(cuid, payload)

    def set_random_pair(self, a: str, b: str):
        for uid in (a, b):
            old_peer = self.random_pairs.get(uid)
            if old_peer and old_peer not in (a, b):
                self.random_pairs.pop(old_peer, None)
        self.random_pairs[a] = b
        self.random_pairs[b] = a

    def clear_random_pair(self, uid: str):
        peer = self.random_pairs.pop(uid, None)
        if peer:
            self.random_pairs.pop(peer, None)

    def random_peer(self, uid: str) -> str | None:
        return self.random_pairs.get(uid)

    def set_viewing(self, uid: str, peer_uid: str | None):
        self.viewing_chat[uid] = peer_uid

    def is_viewing(self, uid: str, peer_uid: str) -> bool:
        return self.viewing_chat.get(uid) == peer_uid

    def _pair_lock(self, uid_a: str, uid_b: str) -> asyncio.Lock:
        key = "|".join(sorted([uid_a, uid_b]))
        if key not in self._keep_locks:
            self._keep_locks[key] = asyncio.Lock()
        return self._keep_locks[key]

    async def handle_keep(self, uid: str, peer_uid: str) -> bool:
        lock = self._pair_lock(uid, peer_uid)
        async with lock:
            other_pending = self._pending_keeps.get(peer_uid)
            if other_pending == uid:
                del self._pending_keeps[peer_uid]
                self._pending_keeps.pop(uid, None)
                return True
            self._pending_keeps[uid] = peer_uid
            return False

    def cancel_keep(self, uid: str):
        self._pending_keeps.pop(uid, None)

    async def send(self, uid: str, data: dict):
        payload = json.dumps(data)
        for sock in list(self.active.get(uid, [])):
            try:
                await sock.send_text(payload)
            except Exception:
                self.disconnect(uid, sock)


manager = WSManager()
