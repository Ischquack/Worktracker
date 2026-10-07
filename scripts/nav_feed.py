#!/usr/bin/env python3
"""Pull NAV's official job feed (pam-stilling-feed) and save active ads for the
chosen municipalities as JSON for Jobbjakt's morning run.

Stdlib only. Configuration via environment variables:
  NAV_FEED_TOKEN   Personal token from NAV (recommended). Falls back to NAV's
                   rotating public test token when unset.
  MUNICIPALITIES   Comma-separated municipality names, default "OSLO".
  LOOKBACK_DAYS    How far back to read the feed, default 8.
  OUTPUT           Output path, default data/nav-ads.json.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

BASE = "https://pam-stilling-feed.nav.no"
UA = "Jobbjakt/1.0 (+https://github.com/Ischquack/worktracker)"
MAX_PAGES = 600
DESC_LIMIT = 8000


def http(url, token=None, headers=None, retries=3):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (304, 401, 403, 404):
                return e.code, ""
            if attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2 * (attempt + 1))
    return 0, ""


def get_token():
    tok = os.environ.get("NAV_FEED_TOKEN", "").strip()
    if tok:
        return tok.removeprefix("Bearer ").strip(), "personal"
    status, body = http(f"{BASE}/api/publicToken")
    m = re.search(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", body or "")
    if not m:
        sys.exit(f"Could not read NAV public token (HTTP {status}).")
    return m.group(0), "public"


def absolute(url):
    return url if url.startswith("http") else BASE + (url if url.startswith("/") else "/" + url)


def read_feed(token, since):
    """Walk the feed from `since` and keep the newest entry per ad uuid."""
    latest = {}
    url = f"{BASE}/api/v1/feed"
    headers = {"If-Modified-Since": format_datetime(since, usegmt=True)}
    for page in range(MAX_PAGES):
        status, body = http(url, token, headers)
        if status in (401, 403):
            sys.exit(f"NAV rejected the token (HTTP {status}). Set a valid NAV_FEED_TOKEN secret.")
        if status != 200 or not body:
            break
        data = json.loads(body)
        for item in data.get("items", []):
            fe = item.get("_feed_entry") or {}
            uuid = fe.get("uuid")
            if not uuid:
                continue
            modified = item.get("date_modified") or fe.get("sistEndret") or ""
            prev = latest.get(uuid)
            if prev is None or modified >= prev["modified"]:
                latest[uuid] = {"modified": modified, "status": fe.get("status"),
                                "municipal": (fe.get("municipal") or "").upper(),
                                "title": fe.get("title") or item.get("title"),
                                "employer": fe.get("businessName"),
                                "url": item.get("url")}
        if not data.get("next_id") or not data.get("next_url"):
            break
        url = absolute(data["next_url"])
        headers = {}
    return latest, page + 1


def text_from_html(s):
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s or "")
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def detail(token, url):
    status, body = http(absolute(url), token)
    if status != 200 or not body:
        return None
    d = json.loads(body)
    return d.get("ad_content") or d.get("json") or d


def main():
    munis = [m.strip().upper() for m in os.environ.get("MUNICIPALITIES", "OSLO").split(",") if m.strip()]
    days = int(os.environ.get("LOOKBACK_DAYS", "8"))
    out_path = os.environ.get("OUTPUT", "data/nav-ads.json")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    token, kind = get_token()
    latest, pages = read_feed(token, since)
    wanted = {u: e for u, e in latest.items() if e["status"] == "ACTIVE" and e["municipal"] in munis}
    print(f"Feed pages read: {pages}; ads changed since {since:%Y-%m-%d}: {len(latest)}; active in {munis}: {len(wanted)}")

    ads = []
    for i, (uuid, e) in enumerate(sorted(wanted.items(), key=lambda kv: kv[1]["modified"], reverse=True)):
        a = detail(token, e["url"]) if e.get("url") else None
        if a is None:
            continue
        published = a.get("published") or ""
        if published and published < since.isoformat()[:19]:
            continue  # changed recently but first published long ago
        loc = (a.get("workLocations") or [{}])[0]
        emp = a.get("employer") or {}
        ads.append({
            "id": f"nav-{uuid}",
            "uuid": uuid,
            "title": a.get("title") or e["title"],
            "jobtitle": a.get("jobtitle"),
            "employer": emp.get("name") or e["employer"],
            "location": ", ".join(x for x in [loc.get("city"), loc.get("municipal")] if x),
            "postalCode": loc.get("postalCode"),
            "published": published,
            "updated": a.get("updated") or e["modified"],
            "expires": a.get("expires"),
            "applicationDue": a.get("applicationDue"),
            "applicationUrl": a.get("applicationUrl"),
            "url": f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}",
            "sourceurl": a.get("sourceurl"),
            "source": a.get("source"),
            "engagementtype": a.get("engagementtype"),
            "extent": a.get("extent"),
            "sector": a.get("sector"),
            "starttime": a.get("starttime"),
            "occupations": [f"{o.get('level1')} / {o.get('level2')}" for o in a.get("occupationCategories") or []],
            "description": text_from_html(a.get("description"))[:DESC_LIMIT],
        })
        if i % 25 == 24:
            time.sleep(1)  # be gentle with NAV

    ads.sort(key=lambda x: x["published"] or "", reverse=True)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": now.isoformat(timespec="seconds"), "tokenType": kind,
                   "lookbackDays": days, "municipalities": munis, "count": len(ads), "ads": ads},
                  f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(ads)} ads to {out_path} (token: {kind})")


if __name__ == "__main__":
    main()
