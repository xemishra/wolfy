from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import (COOKIE_SECURE, FIREBASE_API_KEY, FIREBASE_APP_ID,
                        FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID, SECRET_KEY)
from app.core.database import db
from app.services.auth import verify_token
from app.services.chat import build_contacts, total_unread

COOKIE = "wolfy_uid"
PENDING_COOKIE = "wolfy_pending"
_COOKIE_COMMON = dict(httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")

signer = URLSafeTimedSerializer(SECRET_KEY)

FIREBASE_CFG = dict(
    apiKey=FIREBASE_API_KEY,
    authDomain=FIREBASE_AUTH_DOMAIN,
    projectId=FIREBASE_PROJECT_ID,
    appId=FIREBASE_APP_ID,
)


def _load_signed_uid(raw: str | None, *, max_age: int) -> str | None:
    if not raw:
        return None
    try:
        return signer.loads(raw, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def get_session(request: Request) -> str | None:
    return _load_signed_uid(request.cookies.get(COOKIE), max_age=60 * 60 * 24 * 30)


def get_session_from_cookies(cookies: dict) -> str | None:
    return _load_signed_uid(cookies.get(COOKIE), max_age=60 * 60 * 24 * 30)


def set_session(response, uid: str):
    response.set_cookie(
        COOKIE,
        signer.dumps(uid),
        max_age=60 * 60 * 24 * 30,
        **_COOKIE_COMMON,
    )


def set_pending_cookie(response, payload: dict):
    response.set_cookie(
        PENDING_COOKIE,
        signer.dumps(payload),
        max_age=60 * 30,
        **_COOKIE_COMMON,
    )


def clear_pending_cookie(response):
    response.delete_cookie(
        PENDING_COOKIE,
        path="/",
        secure=COOKIE_SECURE,
        samesite="lax",
    )


def clear_session_cookie(response):
    response.delete_cookie(COOKIE, path="/", secure=COOKIE_SECURE, samesite="lax")


def get_pending(request: Request) -> dict | None:
    raw = request.cookies.get(PENDING_COOKIE)
    if not raw:
        return None
    try:
        return signer.loads(raw, max_age=60 * 30)
    except (BadSignature, SignatureExpired):
        return None


async def user_for_ws(token: str, cookies: dict) -> dict | None:
    token = (token or "").strip()
    if token:
        decoded = await verify_token(token)
        if decoded:
            user = await db.users.find_one({"firebase_uid": decoded["uid"]})
            if user:
                return user

    uid = get_session_from_cookies(cookies)
    if uid:
        return await db.users.find_one({"uid": uid})
    return None


async def current_user(request: Request) -> dict | None:
    uid = get_session(request)
    if not uid:
        return None
    return await db.users.find_one({"uid": uid})


async def require_user(request: Request) -> dict | None:
    """Alias used as FastAPI dependency — returns user or None."""
    return await current_user(request)


def template_ctx(request: Request, **kw) -> dict:
    return {"request": request, "firebase": FIREBASE_CFG, **kw}


async def page_context(
    request: Request, user: dict, *, active_peer_uid: str | None = None
) -> dict:
    from app.services.websocket_manager import manager

    contacts = await build_contacts(user, manager, active_peer_uid=active_peer_uid)
    return {
        "user": user,
        "contacts": contacts,
        "total_unread": total_unread(user),
    }
