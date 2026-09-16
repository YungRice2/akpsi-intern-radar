# AKPsi Intern Radar

A fully automated internship screener for the chapter. Every 30 minutes it checks 50+ company career sites and a community feed, filters for business roles (finance, accounting, audit, consulting, wealth management, HR, sales, marketing, management), and posts anything **new** to Discord — big firms first, in gold, with a ⭐ and an @here.

Every alert shows **how recently the role was posted** ("🔥 Posted today", "Posted 3 days ago"), and anything older than 45 days is filtered out entirely.

Runs for free on GitHub Actions. No server, no laptop that has to stay on.

---

## Setup (≈10 minutes, one time)

### 1. Discord webhooks
1. In your Discord server, go to the channel you want alerts in (e.g. `#internships`) → **Edit Channel → Integrations → Webhooks → New Webhook** → **Copy Webhook URL**.
2. *(Optional but recommended)* Make a second channel like `#top-firms`, create a webhook for it the same way. Tier-1 postings get sent here too, and the weekly digest lands here so a mod can **pin** it. That's the "biggest companies pinned to the top" behavior — Discord webhooks can't pin messages themselves, so this is the cleanest workaround.

### 2. GitHub
1. Create a **new private repo** on github.com (Free plan is fine — you get 2,000 Actions minutes/month; this uses ~150).
2. Upload everything in this folder (drag-and-drop in the browser works, or `git push`). Make sure the `.github/workflows/scan.yml` file comes along — it's a hidden folder.
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `DISCORD_WEBHOOK` = the `#internships` webhook URL
   - `DISCORD_TOP_WEBHOOK` = the `#top-firms` webhook URL *(skip if you didn't make one)*
4. Repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save. (The bot commits `seen.json` so it doesn't re-post the same job.)
5. Repo → **Actions** tab → **Intern Radar** → **Run workflow**. The first run announces up to 25 postings (Tier 1 first) and silently remembers the rest, so the channel isn't flooded. After that it only posts genuinely new listings.

That's it. It now runs every 30 min forever, plus a Monday 9 AM ET digest.

---

## Tuning (all in `config.yaml`, no code)

| Want to… | Edit |
|---|---|
| Add/remove role types | `include_keywords` / `exclude_keywords` |
| Change which companies count as "big" | `tiers.tier1` |
| Change the @mention (e.g. a `@Brothers` role) | `discord.tier1_mention` → `<@&ROLE_ID>` |
| Track a new company directly | add to `sources.workday.sites` / `greenhouse.boards` / `lever.boards` |
| Allow MBA roles | delete the `\bMBA\b` line under `exclude_keywords` |
| Change seasons | `allowed_terms` |
| Only show very recent postings | `recency.max_age_days` (default 45; `0` = no limit) |
| Change what counts as "🔥 fresh" | `recency.fresh_days` (default 3) |

Push the change to GitHub; it takes effect on the next run.

### Workday notes (learned the hard way)
- **Page size is capped at 20.** Asking for more returns HTTP 200 with an empty list and a filled-in `total` — identical to "this company has no openings." The code pages at 20 and warns if a tenant reports a total but returns nothing.
- **`postedOn` is a sentence, not a date** ("Posted 3 Days Ago"), returned in whatever locale the endpoint picks. The requests pin `Accept-Language: en-US` so the date parser always sees English.
- **You cannot guess a Workday URL from a company name.** The tenant, shard (`wd1`/`wd5`/`wd103`), and site name are all arbitrary. Every URL in `config.yaml` was extracted from a real live job link, which is why they're reliable.

### Where recency comes from
| Platform | Date source | Accuracy |
|---|---|---|
| Simplify feed | `date_posted` timestamp | exact |
| Oracle (JPMorgan, BNY, Amex) | `PostedDate` | exact |
| Greenhouse / Lever | first published / created | exact |
| Workday | `startDate`, else "Posted 3 Days Ago" text | exact or ±1 day |
| iCIMS | not published | falls back to "🔥 Just found" the first time the radar sees it |

Sorting is always **Tier 1 first, then newest first**, so the biggest firms stay on top and the freshest roles lead within each group.

### Adding a company
Most large firms use one of these job platforms. Find the company's careers page and match the URL:

- **Workday** — `https://<company>.wd5.myworkdayjobs.com/<SiteName>` or `https://wd1.myworkdaysite.com/recruiting/<company>/<SiteName>` → paste the whole thing as `careers_url`.
- **Oracle** — `https://<code>.fa.<region>.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/...` → `host` is everything before `/hcmUI`, `site_number` is the `CX_...` part.
- **iCIMS** — `https://career-<company>.icims.com/jobs/...` → `host` is everything before `/jobs`.
- **Greenhouse** — `https://boards.greenhouse.io/<token>` → use `<token>`.
- **Lever** — `https://jobs.lever.co/<token>` → use `<token>`.

Then run `python verify_sources.py` (or trigger the **health** run from the Actions tab, which posts the same report to Discord). Anything showing ❌ has a bad URL — open that company's careers page, search "intern", and copy the URL from the address bar.

Every URL shipped in `config.yaml` was derived from a real live job posting, not guessed. Two caveats worth knowing:

- **iCIMS (Schwab, Stifel) is HTML-scraped**, because iCIMS publishes no API. If Schwab redesigns their careers page it may start returning 0 — the health report will tell you, and Schwab stays covered by the Simplify feed either way.
- **Goldman, Morgan Stanley, Deloitte, EY, KPMG, MBB, and the bulge-bracket boutiques** run custom or login-walled career sites with no callable endpoint. They come through the Simplify feed, which refreshes many times a day — a few hours behind the company site rather than 30 minutes.

A common mistake worth flagging: **JPMorgan and BNY are not on Workday.** Both moved to Oracle Recruiting Cloud. Pointing a Workday URL at them silently returns nothing.

---

## Running locally (optional)
```bash
pip install -r requirements.txt
python verify_sources.py          # check every source works
python -m radar.main dry-run      # see what would be posted, without posting
DISCORD_WEBHOOK=https://... python -m radar.main scan
DISCORD_WEBHOOK=https://... python -m radar.main health   # post a source-health report
```

## How it works
```
50+ career sites + Simplify feed ──▶ screener ──▶ new? ──▶ Discord
       every 30 min                keywords, term,   seen.json   Tier 1 first,
                                   age, tier                     then newest first
```
- `radar/sources.py` – fetchers (Workday, Oracle, iCIMS, Greenhouse, Lever, Simplify). One failing site never stops the others; each records a health count.
- `radar/dates.py` – normalizes every source's date format into one timestamp.
- `radar/screener.py` – keyword logic, internship check, age filter, tier assignment, duplicate collapsing, sorting.
- `radar/notify.py` – Discord embeds (gold ⭐ Tier 1, blue = fresh, grey = older), weekly board, health report.
- `seen.json` – memory of what's already been posted (auto-committed by the workflow, pruned after 200 days).


## Monthly upkeep (5 minutes, optional)
Career sites get restructured occasionally. On the 1st of each month the bot posts a health report listing any source returning zero. If one shows up:
1. Open that company's careers page and search "intern".
2. Copy the URL from the address bar into `config.yaml`.
3. Commit. Nothing else to do.

If nobody ever does this, the radar keeps working — the Simplify feed covers the same companies with a few hours' delay.
