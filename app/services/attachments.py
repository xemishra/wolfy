from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.paths import UPLOAD_DIR
from app.utils.text import preview_snippet

MAX_BYTES = 10 * 1024 * 1024

IMAGE_MIMES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }
)

ALLOWED_MIMES = IMAGE_MIMES | frozenset(
    {
        "application/pdf",
        "text/plain",
        "application/zip",
        "application/x-zip-compressed",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)

EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def ensure_upload_dir() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _sniff_mime(data: bytes) -> str | None:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 4 and data[:4] == b"%PDF":
        return "application/pdf"
    if len(data) >= 4 and data[:4] == b"PK\x03\x04":
        return "application/zip"
    return None


def safe_filename(name: str) -> str:
    name = Path(name or "file").name
    cleaned = re.sub(r"[^\w.\- ]", "_", name).strip()
    return (cleaned or "file")[:200]


def file_path(file_id: str, ext: str = "") -> Path:
    if not re.fullmatch(r"[0-9a-f\-]{36}", file_id):
        raise ValueError("Invalid file id")
    ext = ext if ext.startswith(".") else f".{ext}" if ext else ""
    return UPLOAD_DIR / f"{file_id}{ext}"


def resolve_stored_path(file_id: str, ext: str = "") -> Path | None:
    if ext:
        p = file_path(file_id, ext)
        if p.is_file():
            return p
    for candidate in UPLOAD_DIR.glob(f"{file_id}.*"):
        if candidate.is_file():
            return candidate
    return None


async def save_chat_upload(upload: UploadFile) -> tuple[str, str, dict]:
    raw = await upload.read()
    if not raw:
        raise ValueError("Empty file")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB)")

    declared = (upload.content_type or "").split(";")[0].strip().lower()
    sniffed = _sniff_mime(raw)
    mime = sniffed or declared
    if mime not in ALLOWED_MIMES:
        raise ValueError("File type not allowed")
    if sniffed and declared and sniffed != declared and declared in IMAGE_MIMES:
        mime = sniffed

    file_id = str(uuid.uuid4())
    ext = (
        EXT_BY_MIME.get(mime)
        or Path(safe_filename(upload.filename or "")).suffix.lower()
        or ""
    )
    if ext and not ext.startswith("."):
        ext = f".{ext}"

    dest = UPLOAD_DIR / f"{file_id}{ext}"
    dest.write_bytes(raw)

    msg_type = "image" if mime in IMAGE_MIMES else "file"
    meta = {
        "file_id": file_id,
        "filename": safe_filename(upload.filename or "file"),
        "mime": mime,
        "size": len(raw),
        "ext": ext,
    }
    return file_id, msg_type, meta


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def message_preview(msg_type: str, attachment: dict | None, text: str = "") -> str:
    if text and text.strip():
        return preview_snippet(text)
    if msg_type == "image":
        return "📷 Photo"
    if msg_type == "file" and attachment:
        return f"📎 {attachment.get('filename', 'File')}"
    return "Message"
