import os
import sys

from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

MONGO_URL = os.getenv("MONGO_URL", "")
DB_NAME = os.getenv("DB_NAME", "wolfy")

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "")
FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN", "")
FIREBASE_APP_ID = os.getenv("FIREBASE_APP_ID", "")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

_DEFAULT_SECRET = "change-me-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET)

COOKIE_SECURE = os.getenv(
    "COOKIE_SECURE", "true" if IS_PRODUCTION else "false"
).lower() in (
    "1",
    "true",
    "yes",
)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

MAX_MESSAGE_LEN = int(os.getenv("MAX_MESSAGE_LEN", "10000"))


def validate_config() -> None:
    """Fail fast on dangerous production configuration."""
    if not IS_PRODUCTION:
        return
    problems: list[str] = []
    if not SECRET_KEY or SECRET_KEY == _DEFAULT_SECRET or len(SECRET_KEY) < 32:
        problems.append(
            "SECRET_KEY must be set to a random string (32+ chars) in production"
        )
    if not MONGO_URL:
        problems.append("MONGO_URL is required in production")
    if not FIREBASE_PROJECT_ID or not FIREBASE_API_KEY:
        problems.append(
            "FIREBASE_PROJECT_ID and FIREBASE_API_KEY are required in production"
        )
    if "localhost" in MONGO_URL and os.getenv("ALLOW_LOCAL_MONGO") != "true":
        problems.append(
            "MONGO_URL points at localhost, set ALLOW_LOCAL_MONGO=true to allow in production"
        )
    if problems:
        print("Configuration error:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)


validate_config()
