from app.core.database import db, ensure_indexes
from app.core.paths import (ASSETS_DIR, ROOT_DIR, STATIC_DIR, TEMPLATES_DIR,
                            UPLOAD_DIR)

__all__ = [
    "db",
    "ensure_indexes",
    "ROOT_DIR",
    "STATIC_DIR",
    "TEMPLATES_DIR",
    "ASSETS_DIR",
    "UPLOAD_DIR",
]
