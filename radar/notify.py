"""Discord output. Tier-1 ("biggest firms") first, in gold, with ⭐ and an @mention.
Every card shows how recently the role was posted."""
import logging, time
from datetime import datetime, timezone
import requests
from .models import Posting

log = logging.getLogger("radar.notify")
GOLD, BLUE, GREY = 0xF1C40F, 0x3498DB, 0x95A5A6


def _embed(p: Posting) -> dict:
    loc = ", ".join([l for l in p.locations if l][:3]) or "See posting"
    fields = [
        {"name": "Posted", "value": p.age_text, "inline": True},
        {"name": "Location", "value": loc[:1024], "inline": True},
        {"name": "Term", "value": ", ".join(p.terms) if p.terms else "—", "inline": True},
    ]
    color = GOLD if p.tier == 1 else (BLUE if p.is_fresh else GREY)
    star = "⭐ " if p.tier == 1 else ""
    foot = f"{p.source}"
    if p.posted_at:
        foot += f" • posted {p.posted_date_str}"
    return {"title": f"{star}{p.company} — {p.title}"[:256], "url": p.url,
            "color": color, "fields": fields,
            "footer": {"text": f"{foot} • found {datetime.now(timezone.utc):%b %d, %I:%M %p} UTC"},
            "timestamp": datetime.fromtimestamp(p.posted_at, timezone.utc).isoformat() if p.posted_at else None}


def _post(webhook, payload):
    for _ in range(4):
        try:
            r = requests.post(webhook, json=payload, timeout=20)
        except Exception as e:
            log.error("discord request failed: %s", e)
            return
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)) + 0.5)
            continue
        if r.status_code >= 400:
            log.error("discord %s: %s", r.status_code, r.text[:300])
        return
    log.error("discord: gave up after repeated rate limits")


def _send(batch, text, hook, cfg):
    for i in range(0, len(batch), 10):
        payload = {"username": cfg.get("username", "Intern Radar"),
                   "embeds": [{k: v for k, v in _embed(p).items() if v is not None}
                              for p in batch[i:i + 10]]}
        if text and i == 0:
            payload["content"] = text[:2000]
        _post(hook, payload)
        time.sleep(1.2)


def announce(posts, cfg, webhook, top_webhook=None):
    if not posts:
        return
    tier1 = [p for p in posts if p.tier == 1]
    tier2 = [p for p in posts if p.tier == 2]
    if tier1:
        fresh = sum(1 for p in tier1 if p.is_fresh)
        mention = cfg.get("tier1_mention") or ""
        extra = f" — {fresh} posted in the last few days" if fresh else ""
        text = f"{mention} **{len(tier1)} new Tier-1 internship{'s' * (len(tier1) != 1)}**{extra}".strip()
        _send(tier1, text, webhook, cfg)
        if top_webhook:
            _send(tier1, text, top_webhook, cfg)
    if tier2:
        _send(tier2, f"**{len(tier2)} new internship{'s' * (len(tier2) != 1)}**", webhook, cfg)
    log.info("announced %d tier-1, %d tier-2", len(tier1), len(tier2))


def _chunk_and_post(lines, hooks, cfg):
    buf, chunks = "", []
    for ln in lines:
        if len(buf) + len(ln) + 1 > 1900:
            chunks.append(buf)
            buf = ""
        buf += ln + "\n"
    chunks.append(buf)
    for hook in filter(None, hooks):
        for c in chunks:
            _post(hook, {"username": cfg.get("username", "Intern Radar"), "content": c})
            time.sleep(1.2)


def digest(posts, cfg, webhook, top_webhook=None, fresh_days=3):
    """Weekly board: freshest first, Tier 1 on top. Plain text so a mod can pin it."""
    lim = cfg.get("digest_max_per_tier", 40)
    if not posts:
        return
    def line(p):
        return f"• **{p.company}** — [{p.title}]({p.url}) · _{p.age_text}_"
    lines = [f"# 📌 Internship Board — week of {datetime.now(timezone.utc):%b %d, %Y}", ""]
    if cfg.get("digest_fresh_section", True):
        fresh = [p for p in posts if p.age_days is not None and p.age_days <= fresh_days][:lim]
        if fresh:
            lines += [f"## 🔥 Posted in the last {fresh_days} days"] + [line(p) for p in fresh] + [""]
    for tier, header in ((1, "## ⭐ Top firms"), (2, "## Everything else")):
        group = [p for p in posts if p.tier == tier][:lim]
        if group:
            lines += [header] + [line(p) for p in group] + [""]
    lines.append("_Mods: pin this message so it stays at the top of the channel._")
    _chunk_and_post(lines, [webhook, top_webhook], cfg)


def health(stats: dict, cfg, webhook):
    """Posts which sources are working. Run on demand from the Actions tab."""
    ok = {k: v for k, v in stats.items() if v > 0}
    bad = {k: v for k, v in stats.items() if v == 0}
    lines = [f"# 🩺 Source health — {datetime.now(timezone.utc):%b %d, %I:%M %p} UTC",
             f"**{len(ok)} working / {len(stats)} total**", ""]
    if bad:
        lines += ["## ❌ Returning nothing (fix the URL in config.yaml, or remove it)"]
        lines += [f"• {k}" for k in sorted(bad)] + [""]
    lines += ["## ✅ Working"] + [f"• {k} — {v}" for k, v in sorted(ok.items(), key=lambda x: -x[1])]
    _chunk_and_post(lines, [webhook], cfg)
