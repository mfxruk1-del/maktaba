"""Arabic normalisation shared by the indexer and the server (index and queries must match)."""
import re, unicodedata

_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ء": "",
    "ى": "ي", "ی": "ي", "ئ": "ي",
    "ة": "ه", "ۀ": "ه", "ہ": "ه",
    "ؤ": "و", "ک": "ك",
    # Urdu/Persian typing of Arabic letters (Fatawa Ridawiyya etc.)
    "ھ": "ه", "ۃ": "ه", "ے": "ي", "ۓ": "ي",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # harakat, Quranic marks, tatweel
_NONWORD = re.compile(r"[^ء-ي0-9a-zA-Zپٹڈڑںگچژ]+")  # keep Urdu/Persian-only letters inside words


def norm(text: str) -> str:
    """Lower-noise form for searching: no diacritics, unified letter variants, single spaces."""
    t = unicodedata.normalize("NFC", text)
    t = _MARKS.sub("", t).translate(_MAP)
    t = _MARKS.sub("", t)  # marks exposed after decomposition-like cases
    return _NONWORD.sub(" ", t).strip()
