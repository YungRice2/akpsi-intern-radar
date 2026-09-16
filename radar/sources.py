"""Fetchers. Each returns (list[Posting], status_str) and never raises — one broken
career site can't take down the whole scan."""
import logging, re, time
from html import unescape
from urllib.parse import urlparse, quote
import requests
from .models import Posting
from . import dates

log = logging.getLogger("radar.sources")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
TIMEOUT = 30
HEALTH: dict[str, int] = {}       # "Workday · BNY" -> number of postings returned


def _note(platform, name, n):
    HEALTH[f"{platform} · {name}"] = n


def _get(url, **kw):
    extra = kw.pop("headers", {})
    r = requests.get(url, headers={**UA, **extra}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


# ── 1. Simplify community feed ────────────────────────────────────────────────
def fetch_simplify(cfg) -> list[Posting]:
    out = []
    for url in cfg.get("urls", []):
        label = url.split("/")[4] if len(url.split("/")) > 4 else url
        try:
            data = _get(url).json()
        except Exception as e:
            log.warning("simplify %s failed: %s", label, e)
            _note("Simplify", label, 0)
            continue
        n = 0
        for j in data:
            if not j.get("active") or not j.get("is_visible", True):
                continue
            out.append(Posting(
                company=j.get("company_name", "").strip(),
                title=j.get("title", "").strip(),
                url=j.get("url", ""),
                source="Simplify",
                locations=j.get("locations", []),
                terms=j.get("terms", []),
                posted_at=dates.from_epoch(j.get("date_posted")),
            ))
            n += 1
        _note("Simplify", label, n)
    return out


# ── 2. Workday ────────────────────────────────────────────────────────────────
def _workday_api(careers_url: str):
    u = urlparse(careers_url.rstrip("/"))
    parts = [p for p in u.path.split("/") if p and p.lower() not in ("en-us", "en")]
    if "myworkdaysite.com" in u.netloc:            # /recruiting/<tenant>/<site>
        tenant, site = parts[1], parts[2]
        base = f"{u.scheme}://{u.netloc}/{'/'.join(parts)}"
    else:                                          # <tenant>.wdN.myworkdayjobs.com/<site>
        tenant, site = u.netloc.split(".")[0], parts[0]
        base = f"{u.scheme}://{u.netloc}/{site}"
    return f"{u.scheme}://{u.netloc}/wday/cxs/{tenant}/{site}/jobs", base


def fetch_workday(cfg) -> list[Posting]:
    out, search = [], cfg.get("search_text", "intern")
    for site in cfg.get("sites", []):
        found = []
        try:
            api, base = _workday_api(site["careers_url"])
            offset, PAGE = 0, 20   # 20 is Workday's hard ceiling — do not raise this
            while offset < cfg.get("max_per_site", 200):
                r = requests.post(api, json={"appliedFacets": {}, "limit": PAGE,
                                             "offset": offset, "searchText": search},
                                  headers={**UA, "Accept": "application/json",
                                           "Accept-Language": "en-US",
                                           "Content-Type": "application/json"}, timeout=TIMEOUT)
                r.raise_for_status()
                js = r.json()
                jobs = js.get("jobPostings", [])
                for j in jobs:
                    label = j.get("postedOn") or ""
                    found.append(Posting(
                        company=site["name"], title=j.get("title", "").strip(),
                        url=base + j.get("externalPath", ""), source="Workday",
                        locations=[j.get("locationsText", "")] if j.get("locationsText") else [],
                        posted_at=(dates.from_iso(j.get("postingDate"))
                                   or dates.from_relative(label)
                                   or dates.from_iso(j.get("startDate"))),
                        posted_label=label or None))
                if not jobs and offset == 0 and js.get("total", 0) > 0:
                    log.warning("Workday %s: total=%s but 0 returned — page size or facet issue",
                                site["name"], js.get("total"))
                offset += PAGE
                if not jobs or offset >= js.get("total", 0):
                    break
                time.sleep(0.4)
        except Exception as e:
            log.warning("Workday %s failed (%s) — check careers_url", site.get("name"), e)
        _note("Workday", site["name"], len(found))
        out += found
    return out


# ── 3. Oracle Recruiting Cloud (JPMorgan, BNY, Amex, Grant Thornton, …) ───────
def fetch_oracle(cfg) -> list[Posting]:
    out, kw = [], cfg.get("search_text", "intern")
    for site in cfg.get("sites", []):
        found = []
        try:
            host = site["host"].rstrip("/")
            num = site["site_number"]
            finder = (f"findReqs;siteNumber={num},facetsList=LOCATIONS;WORK_LOCATIONS;CATEGORIES,"
                      f"limit=50,offset=0,sortBy=POSTING_DATES_DESC,keyword={quote(kw)}")
            url = (f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                   f"?onlyData=true&expand=requisitionList.secondaryLocations&finder={finder}")
            js = _get(url, headers={**UA, "Accept": "application/json"}).json()
            items = js.get("items", [])
            reqs = items[0].get("requisitionList", []) if items else []
            for j in reqs:
                jid = j.get("Id") or j.get("RequisitionId")
                found.append(Posting(
                    company=site["name"], title=(j.get("Title") or "").strip(),
                    url=f"{host}/hcmUI/CandidateExperience/en/sites/{num}/job/{jid}",
                    source="Oracle",
                    locations=[j.get("PrimaryLocation") or j.get("Location") or ""],
                    posted_at=dates.from_iso(j.get("PostedDate")),
                ))
        except Exception as e:
            log.warning("Oracle %s failed (%s) — check host/site_number", site.get("name"), e)
        _note("Oracle", site["name"], len(found))
        out += found
    return out


# ── 4. iCIMS (Charles Schwab, Stifel, …) ──────────────────────────────────────
_ICIMS_ROW = re.compile(r'href="(?P<u>[^"]*?/jobs/\d+/[^"]*?)"[^>]*>\s*(?P<t>[^<]{4,160}?)\s*</a>', re.I | re.S)


def fetch_icims(cfg) -> list[Posting]:
    """iCIMS has no public JSON API; its search page is server-rendered, so we read
    the job links out of the HTML. Degrades to 0 results rather than crashing."""
    out, kw = [], cfg.get("search_text", "intern")
    for site in cfg.get("sites", []):
        found, seen = [], set()
        try:
            host = site["host"].rstrip("/")
            for page in range(1, cfg.get("max_pages", 3) + 1):
                html = _get(f"{host}/jobs/search?ss=1&searchKeyword={quote(kw)}&pr={page}").text
                hits = list(_ICIMS_ROW.finditer(html))
                if not hits:
                    break
                for m in hits:
                    u = m.group("u")
                    u = u if u.startswith("http") else host + u
                    t = unescape(re.sub(r"\s+", " ", m.group("t"))).strip()
                    if u.split("?")[0] in seen or len(t) < 5:
                        continue
                    seen.add(u.split("?")[0])
                    found.append(Posting(company=site["name"], title=t, url=u, source="iCIMS"))
                time.sleep(0.5)
        except Exception as e:
            log.warning("iCIMS %s failed (%s)", site.get("name"), e)
        _note("iCIMS", site["name"], len(found))
        out += found
    return out


# ── 5. Greenhouse ─────────────────────────────────────────────────────────────
def fetch_greenhouse(cfg) -> list[Posting]:
    out = []
    for b in cfg.get("boards", []):
        found = []
        try:
            js = _get(f"https://boards-api.greenhouse.io/v1/boards/{b['token']}/jobs").json()
            for j in js.get("jobs", []):
                found.append(Posting(company=b["name"], title=j["title"].strip(),
                                     url=j["absolute_url"], source="Greenhouse",
                                     locations=[j.get("location", {}).get("name", "")],
                                     posted_at=dates.from_iso(j.get("first_published") or j.get("updated_at"))))
        except Exception as e:
            log.warning("Greenhouse %s failed: %s", b.get("name"), e)
        _note("Greenhouse", b["name"], len(found))
        out += found
    return out


# ── 6. Lever ──────────────────────────────────────────────────────────────────
def fetch_lever(cfg) -> list[Posting]:
    out = []
    for b in cfg.get("boards", []):
        found = []
        try:
            for j in _get(f"https://api.lever.co/v0/postings/{b['token']}?mode=json").json():
                found.append(Posting(company=b["name"], title=j["text"].strip(), url=j["hostedUrl"],
                                     source="Lever", locations=[j.get("categories", {}).get("location", "")],
                                     posted_at=dates.from_epoch(j.get("createdAt"))))
        except Exception as e:
            log.warning("Lever %s failed: %s", b.get("name"), e)
        _note("Lever", b["name"], len(found))
        out += found
    return out


FETCHERS = {"simplify": fetch_simplify, "workday": fetch_workday, "oracle": fetch_oracle,
            "icims": fetch_icims, "greenhouse": fetch_greenhouse, "lever": fetch_lever}


def fetch_all(sources_cfg) -> list[Posting]:
    posts = []
    for name, fn in FETCHERS.items():
        c = sources_cfg.get(name, {})
        if c.get("enabled"):
            posts += fn(c)
    return posts
