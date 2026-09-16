"""Entry point.
    python -m radar.main scan      # find & announce new postings (every 30 min)
    python -m radar.main digest    # weekly pinned-style board
    python -m radar.main health    # report which career sites are responding
    python -m radar.main dry-run   # scan and print, without posting
"""
import json, logging, os, sys, time
import yaml
from .sources import fetch_all, HEALTH
from .screener import Screener
from . import notify
from .models import Posting

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("radar")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN = os.path.join(ROOT, "seen.json")


def _cfg():
    with open(os.path.join(ROOT, "config.yaml")) as f:
        return yaml.safe_load(f)


def _load_seen():
    try:
        with open(SEEN) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_seen(seen, retention_days):
    cutoff = time.time() - retention_days * 86400
    seen = {k: v for k, v in seen.items() if v.get("first_seen", 0) >= cutoff}
    with open(SEEN, "w") as f:
        json.dump(seen, f, indent=0, sort_keys=True)


def main(mode="scan"):
    cfg = _cfg()
    webhook = os.environ.get("DISCORD_WEBHOOK")
    top_webhook = os.environ.get("DISCORD_TOP_WEBHOOK") or None
    if mode != "dry-run" and not webhook:
        sys.exit("DISCORD_WEBHOOK env var is not set")
    fresh_days = cfg.get("recency", {}).get("fresh_days", 3)
    seen = _load_seen()

    if mode == "digest":
        lookback = time.time() - cfg["discord"]["digest_lookback_days"] * 86400
        scr = Screener(cfg)
        recent = [Posting(**v["post"]) for v in seen.values() if v.get("first_seen", 0) >= lookback]
        recent.sort(key=scr.sort_key)
        notify.digest(recent, cfg["discord"], webhook, top_webhook, fresh_days)
        log.info("digest sent with %d postings", len(recent))
        return

    if mode == "health":
        fetch_all(cfg["sources"])
        notify.health(HEALTH, cfg["discord"], webhook)
        bad = [k for k, v in HEALTH.items() if v == 0]
        log.info("health: %d/%d sources OK", len(HEALTH) - len(bad), len(HEALTH))
        for b in bad:
            log.warning("no results from %s", b)
        return

    first_run = len(seen) == 0
    posts = Screener(cfg).run(fetch_all(cfg["sources"]))
    now = int(time.time())
    new = []
    for p in posts:
        if p.key in seen:
            continue
        p.first_seen = now
        new.append(p)
    fresh = sum(1 for p in new if p.is_fresh)
    log.info("%d pass the screener · %d new · %d posted in the last %d days",
             len(posts), len(new), fresh, fresh_days)

    for p in posts:
        seen.setdefault(p.key, {"first_seen": now, "post": {**p.to_dict(), "first_seen": now}})

    to_announce = new
    if first_run:
        cap = cfg["discord"].get("first_run_max_posts", 25)
        to_announce = new[:cap]          # already sorted: Tier 1, then newest
        log.info("first run: announcing %d of %d, silently seeding the rest", len(to_announce), len(new))

    if mode == "dry-run":
        for p in to_announce:
            print(f"[T{p.tier}] {p.age_text:22} | {p.company:24} | {p.title[:80]}")
    else:
        notify.announce(to_announce, cfg["discord"], webhook, top_webhook)
        bad = [k for k, v in HEALTH.items() if v == 0]
        if bad:
            log.warning("%d source(s) returned nothing: %s", len(bad), ", ".join(sorted(bad)[:8]))
    _save_seen(seen, cfg.get("seen_retention_days", 200))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scan")
