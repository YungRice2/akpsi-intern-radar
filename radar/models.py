from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib, re, time


@dataclass
class Posting:
    company: str
    title: str
    url: str
    source: str
    locations: list = field(default_factory=list)
    terms: list = field(default_factory=list)
    posted_at: int | None = None      # unix seconds — when the employer posted it
    posted_label: str | None = None   # source's own wording, e.g. "Posted 3 Days Ago"
    tier: int = 2
    first_seen: int | None = None     # unix seconds — when the radar first saw it

    # ── recency ──────────────────────────────────────────────────────────────
    @property
    def age_days(self) -> float | None:
        if not self.posted_at:
            return None
        return max(0.0, (time.time() - self.posted_at) / 86400)

    @property
    def age_text(self) -> str:
        """Human phrasing used in the Discord card."""
        d = self.age_days
        if d is None:
            # No date from the source, but we know when *we* first saw it.
            if self.first_seen and (time.time() - self.first_seen) < 86400:
                return "🔥 Just found"
            return self.posted_label or "Date not listed"
        if d < 1:
            return "🔥 Posted today"
        if d < 2:
            return "🔥 Posted yesterday"
        if d < 7:
            return f"Posted {int(d)} days ago"
        if d < 14:
            return "Posted last week"
        if d < 60:
            return f"Posted {int(d // 7)} weeks ago"
        return f"Posted {int(d // 30)} months ago"

    @property
    def is_fresh(self) -> bool:
        d = self.age_days
        return d is not None and d < 3

    @property
    def posted_date_str(self) -> str:
        if not self.posted_at:
            return "—"
        return f"{datetime.fromtimestamp(self.posted_at, timezone.utc):%b %d, %Y}"

    # ── identity ─────────────────────────────────────────────────────────────
    @property
    def key(self) -> str:
        norm = re.sub(r"\W+", " ", f"{self.company} {self.title}".lower()).strip()
        return hashlib.sha1(f"{norm}|{self.url.split('?')[0]}".encode()).hexdigest()[:16]

    def to_dict(self):
        return asdict(self)
