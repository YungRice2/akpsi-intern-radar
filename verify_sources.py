"""Run after editing config.yaml:   python verify_sources.py
Hits every configured source and prints how many postings each returns, so a wrong
URL shows up as ❌ immediately. Same check the `health` job posts to Discord."""
import logging, sys, yaml
sys.stdout.reconfigure(encoding="utf-8")
from radar.sources import FETCHERS, HEALTH

logging.basicConfig(level=logging.WARNING, format="   ⚠ %(message)s")
cfg = yaml.safe_load(open("config.yaml"))["sources"]

total = 0
for name, fn in FETCHERS.items():
    c = cfg.get(name, {})
    if not c.get("enabled"):
        print(f"\n{name.upper():12} (disabled)")
        continue
    print(f"\n{name.upper():12}")
    posts = fn(c)
    total += len(posts)
    for k, v in sorted(HEALTH.items()):
        if not k.lower().startswith(name[:4].lower()):
            continue
        who = k.split(" · ", 1)[1]
        print(f"   {'✅' if v else '❌'} {who:26} {v}")

bad = [k for k, v in HEALTH.items() if v == 0]
print(f"\n{len(HEALTH) - len(bad)}/{len(HEALTH)} sources OK · {total} postings before screening")
if bad:
    print("\nFix or delete these in config.yaml:")
    for b in sorted(bad):
        print(f"   ❌ {b}")
    print("\nTo fix: open the company's careers page, search 'intern', and copy the URL")
    print("from the address bar. See the 'Adding a company' section of the README.")
