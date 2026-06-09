import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)

SKIP_COOLDOWN_SECS = 20


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


class Matchmaker:
    def __init__(self):
        self.queue: list[tuple[str, dict]] = []
        self.searching: set[str] = set()
        self._lock = asyncio.Lock()
        self._skip_blocks: dict[str, float] = {}
        self._sessions: dict[str, set[str]] = {}
        self._uid_session: dict[str, str] = {}

    def new_session(self, uid_a: str, uid_b: str) -> str:
        for uid in (uid_a, uid_b):
            if uid in self._uid_session:
                self.invalidate_session(uid)

        sid = str(uuid.uuid4())
        self._sessions[sid] = {uid_a, uid_b}
        self._uid_session[uid_a] = sid
        self._uid_session[uid_b] = sid
        return sid

    def session_of(self, uid: str) -> str | None:
        return self._uid_session.get(uid)

    def session_valid(self, uid: str, session_id: str) -> bool:
        return self._uid_session.get(uid) == session_id

    def invalidate_session(self, uid: str):
        sid = self._uid_session.pop(uid, None)
        if sid:
            members = self._sessions.get(sid, set())
            members.discard(uid)
            if not members:
                self._sessions.pop(sid, None)

    def invalidate_session_pair(self, uid_a: str, uid_b: str):
        for uid in (uid_a, uid_b):
            self.invalidate_session(uid)

    def record_skip(self, uid_a: str, uid_b: str):
        self._skip_blocks[_pair_key(uid_a, uid_b)] = (
            time.monotonic() + SKIP_COOLDOWN_SECS
        )

    def _is_skip_blocked(self, uid_a: str, uid_b: str) -> bool:
        key = _pair_key(uid_a, uid_b)
        exp = self._skip_blocks.get(key)
        if exp is None:
            return False
        if time.monotonic() > exp:
            del self._skip_blocks[key]
            return False
        return True

    async def enqueue(self, uid: str, user: dict, manager) -> bool:
        async with self._lock:
            if manager.random_peer(uid):
                logger.debug(f"[Match] {uid} rejected enqueue, already paired")
                return False

            if uid in self.searching:
                return False
            self.searching.add(uid)

            existing_contacts: set[str] = set(user.get("contacts") or [])

            matched = False
            remaining = []
            for peer_uid, peer_user in self.queue:
                if matched:
                    remaining.append((peer_uid, peer_user))
                    continue

                if peer_uid not in self.searching:
                    continue

                if manager.random_peer(peer_uid):
                    remaining.append((peer_uid, peer_user))
                    continue

                peer_contacts: set[str] = set(peer_user.get("contacts") or [])
                if peer_uid in existing_contacts or uid in peer_contacts:
                    remaining.append((peer_uid, peer_user))
                    continue

                if self._is_skip_blocked(uid, peer_uid):
                    remaining.append((peer_uid, peer_user))
                    continue

                matched = True
                self.searching.discard(uid)
                self.searching.discard(peer_uid)

                manager.clear_random_pair(uid)
                manager.clear_random_pair(peer_uid)

                sid = self.new_session(uid, peer_uid)
                manager.set_random_pair(uid, peer_uid)
                logger.info(
                    f"[Match] {user['username']} <-> {peer_user['username']}  session={sid[:8]}"
                )

                peer_payload = {
                    "uid": peer_uid,
                    "username": peer_user["username"],
                    "display_name": peer_user["display_name"],
                    "photo_url": peer_user.get("photo_url", ""),
                    "session_id": sid,
                }
                my_payload = {
                    "uid": uid,
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "photo_url": user.get("photo_url", ""),
                    "session_id": sid,
                }
                await manager.send(uid, {"type": "match_found", "peer": peer_payload})
                await manager.send(
                    peer_uid, {"type": "match_found", "peer": my_payload}
                )

            self.queue = remaining
            if not matched:
                self.queue.append((uid, user))

            return matched

    def cancel(self, uid: str):
        self.searching.discard(uid)
        self.queue = [(u, d) for u, d in self.queue if u != uid]

    def end_session(self, uid: str, manager):
        manager.clear_random_pair(uid)
        self.invalidate_session(uid)


matchmaker = Matchmaker()
