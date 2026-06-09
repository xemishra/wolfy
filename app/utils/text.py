def name_initial(name: str) -> str:
    n = (name or "").strip()
    return n[0].upper() if n else "?"


def preview_snippet(text: str, max_len: int = 40) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t if len(t) <= max_len else t[: max_len - 1] + "…"
