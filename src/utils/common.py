import re
import unicodedata


def normalize_text(text: str) -> str:
    """Lowercase and strip Vietnamese accents for robust keyword matching."""

    lowered = (text or "").lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^0-9a-z]+", " ", stripped).strip()


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")
