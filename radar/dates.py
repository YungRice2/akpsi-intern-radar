"""Turning every source's idea of a date into unix seconds."""
import re, time
from datetime import datetime, timezone

# (pattern, fixed_days_if_no_number, days_per_unit)
_REL = [
    (r"\byesterday\b", 1, 1),
    (r"\btoday\b|\bjust posted\b|\bjust now\b", 0, 1),
    (r"(\d+)\+?\s*day", 1, 1),
    (r"(\d+)\+?\s*week", 7, 7),
    (r"(\d+)\+?\s*month", 30, 30),
    (r"(\d+)\+?\s*hour", 0, 0),
]


def from_relative(text: str) -> int | None:
    """'Posted 3 Days Ago' / 'Posted Today' / 'Posted 30+ Days Ago'  ->  unix seconds."""
    if not text:
        return None
    t = text.lower()
    for pat, fixed, per_unit in _REL:
        m = re.search(pat, t)
        if m:
            days = int(m.group(1)) * per_unit if (m.groups() and m.group(1)) else fixed
            return int(time.time() - days * 86400)
    return None


def from_iso(text: str) -> int | None:
    """Handles '2026-09-04', '2026-09-04T12:00:00Z', '2026-09-04T12:00:00+00:00'."""
    if not text:
        return None
    s = str(text).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def from_epoch(v) -> int | None:
    """Accepts seconds or milliseconds."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v > 1e11:      # milliseconds
        v /= 1000
    return int(v) if 9e8 < v < 4e9 else None
