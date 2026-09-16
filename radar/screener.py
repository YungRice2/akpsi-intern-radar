"""Decides which postings are worth announcing and assigns company tiers."""
import logging, re
from datetime import datetime
from .models import Posting

log = logging.getLogger("radar.screener")


def _compile(words):
    pats = []
    for w in words:
        if w.startswith("\\b") or "\\" in w:       # already a regex
            pats.append(re.compile(w, re.I))
        else:
            pats.append(re.compile(r"\b" + re.escape(w) + r"\w*", re.I))
    return pats


def _compile_strict(words):
    pats = []
    for w in words:
        if w.startswith("\\b") or "\\" in w:
            pats.append(re.compile(w, re.I))
        else:
            pats.append(re.compile(r"\b" + re.escape(w) + r"s?\b", re.I))
    return pats


class Screener:
    def __init__(self, cfg):
        rec = cfg.get("recency", {})
        self.max_age = rec.get("max_age_days", 0) or 0
        self.newest_first = rec.get("sort_newest_first", True)
        self.max_per_company = cfg.get("max_per_company_per_scan", 0) or 0
        self.inc = _compile(cfg["include_keywords"])
        self.exc = _compile(cfg["exclude_keywords"])
        self.markers = _compile_strict(cfg["internship_markers"])
        self.terms = set(cfg["allowed_terms"])
        cyc = cfg.get("cycles", {})
        if "allowed_years" in cyc:
            self.allowed_years = set(cyc["allowed_years"])
        else:
            now = datetime.now()
            rollover = cyc.get("rollover_month", 7)
            base = now.year if now.month >= rollover else now.year - 1
            self.allowed_years = {base + n for n in cyc.get("years_ahead", [])}
        self.allowed_seasons = {s.lower() for s in cyc.get("allowed_seasons", [])}
        self._year_re = re.compile(r"\b(20\d{2})\b")
        self._season_re = re.compile(r"\b(summer|winter|spring|fall)\b", re.I)
        if self.allowed_years or self.allowed_seasons:
            log.info("cycle filter: base_year=%s  years=%s  seasons=%s",
                     base if "allowed_years" not in cyc else "override",
                     sorted(self.allowed_years) or "any",
                     sorted(self.allowed_seasons) or "any")
        self.tier1 = [t.lower() for t in cfg["tiers"]["tier1"]]
        self.blocked = [b.lower() for b in cfg.get("blocked_companies", [])]

    def tier(self, company: str) -> int:
        c = company.lower()
        return 1 if any(re.search(r"\b" + re.escape(t) + r"\b", c) for t in self.tier1) else 2

    def passes(self, p: Posting) -> bool:
        if not p.title or not p.url:
            return False
        c = p.company.lower()
        if any(b in c for b in self.blocked):
            return False
        # term filter only applies when the source knows the term
        if p.terms and not (set(p.terms) & self.terms):
            return False
        if self.max_age and p.age_days is not None and p.age_days > self.max_age:
            return False
        t = p.title
        if not any(m.search(t) for m in self.markers):
            return False
        # Cycle filter: drop only if a year/season IS present and not allowed.
        # No year and no season → pass (most postings omit them).
        if self.allowed_years or self.allowed_seasons:
            years = [int(m) for m in self._year_re.findall(t)]
            seasons = [m.lower() for m in self._season_re.findall(t)]
            if years and not any(y in self.allowed_years for y in years):
                return False
            if seasons and not any(s in self.allowed_seasons for s in seasons):
                return False
        if any(e.search(t) for e in self.exc):
            return False
        return any(i.search(t) for i in self.inc)

    def run(self, posts: list[Posting]) -> list[Posting]:
        kept, seen = [], set()
        for p in posts:
            # collapse duplicate (company, title) pairs – e.g. same role in 3 cities – into one alert
            dup = (p.company.lower(), re.sub(r"\W+", " ", p.title.lower()).strip())
            if p.key in seen or dup in seen or not self.passes(p):
                continue
            p.tier = self.tier(p.company)
            seen.update({p.key, dup})
            kept.append(p)
        kept.sort(key=self.sort_key)
        if self.max_per_company:
            counts: dict[str, int] = {}
            capped = []
            for p in kept:
                c = p.company.lower()
                if counts.get(c, 0) < self.max_per_company:
                    counts[c] = counts.get(c, 0) + 1
                    capped.append(p)
            kept = capped
        return kept

    def sort_key(self, p):
        """Tier 1 always on top; then newest first (undated postings last)."""
        if self.newest_first:
            return (p.tier, -(p.posted_at or 0), p.company.lower())
        return (p.tier, p.company.lower(), p.title.lower())
