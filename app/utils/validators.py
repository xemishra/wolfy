import re

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")

UID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_valid_uid(uid: str | None) -> bool:
    return bool(uid and UID_PATTERN.match(uid))
