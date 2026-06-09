import logging

import httpx
from cachetools import TTLCache
from jose import jwt

from app.config import FIREBASE_PROJECT_ID

logger = logging.getLogger(__name__)
GOOGLE_CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


async def _fetch_google_certs() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_CERTS_URL)
        resp.raise_for_status()
        return resp.json()


async def _get_certs(*, force_refresh: bool = False) -> dict:
    if force_refresh or "certs" not in _cache:
        _cache["certs"] = await _fetch_google_certs()
    return _cache["certs"]


async def verify_token(id_token: str) -> dict | None:
    try:
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        if not kid:
            return None

        certs = await _get_certs()
        pub_key = certs.get(kid)
        if not pub_key:
            logger.info("[Auth] Unknown key id %s refreshing Google certs", kid)
            certs = await _get_certs(force_refresh=True)
            pub_key = certs.get(kid)
        if not pub_key:
            logger.warning("[Auth] Unknown key id after refresh: %s", kid)
            return None

        claims = jwt.decode(
            id_token,
            pub_key,
            algorithms=["RS256"],
            audience=FIREBASE_PROJECT_ID,
            issuer=f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}",
            options={"verify_exp": True},
        )
        claims["uid"] = claims.get("sub", "")
        return claims

    except Exception as e:
        logger.warning("[Auth] Token verification failed: %s", e)
        return None
