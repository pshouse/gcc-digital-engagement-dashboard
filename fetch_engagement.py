#!/usr/bin/env python3
"""
fetch_engagement.py
-------------------
Pulls digital-engagement data for Gaston Community Church from the free,
official platform APIs and writes a single data file the dashboard reads:

    - Google Analytics 4   -> Google Analytics Data API
    - Facebook Page        -> Meta Graph API (Page Insights)
    - Instagram            -> Meta Graph API (Instagram Insights)
    - YouTube channel      -> YouTube Analytics API

No third-party aggregator, no subscription. You supply your own credentials
in config.json (see config.example.json and SETUP_GUIDE.md).

Each platform is fetched independently. If a platform is not yet configured,
it is skipped so you can wire sources in one at a time.

Output: engagement-data.js  ->  window.ENGAGEMENT_DATA = { ... }
        (loaded by dashboard.html via a <script> tag, so it works offline)

Run:    python fetch_engagement.py
Install deps once:
    pip install google-analytics-data google-auth google-auth-oauthlib \
                google-api-python-client requests
"""

import json
import os
import sys
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
OUTPUT_JS = os.path.join(HERE, "engagement-data.js")
OUTPUT_JSON = os.path.join(HERE, "engagement-data.json")

DEFAULT_LOOKBACK_DAYS = 90


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            "No config.json found. Copy config.example.json to config.json "
            "and fill in your credentials (see SETUP_GUIDE.md)."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def date_range(days):
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    return start, end


def daily_buckets(start, end):
    """Return ordered list of YYYY-MM-DD strings from start..end inclusive."""
    out = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def empty_series(dates):
    return {d: 0 for d in dates}


def _clean_title(text, fallback, n=70):
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return fallback
    return t[:n] + ("…" if len(t) > n else "")


# ----------------------------------------------------------------------------
# Google Analytics 4  (Google Analytics Data API)
# ----------------------------------------------------------------------------
def fetch_ga4(cfg, dates):
    ga = cfg.get("google_analytics") or {}
    prop = ga.get("property_id")
    key_file = ga.get("service_account_json")
    if not prop or not key_file:
        print("  [GA4] not configured - skipping")
        return None
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
        )
        from google.oauth2 import service_account
    except ImportError as e:
        print(f"  [GA4] import failed: {e} - skipping")
        return None

    key_path = key_file if os.path.isabs(key_file) else os.path.join(HERE, key_file)
    creds = service_account.Credentials.from_service_account_file(key_path)
    client = BetaAnalyticsDataClient(credentials=creds)

    req = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="engagedSessions"),
            Metric(name="activeUsers"),
            Metric(name="screenPageViews"),
        ],
        date_ranges=[DateRange(start_date=dates[0], end_date=dates[-1])],
    )
    resp = client.run_report(req)

    sessions = empty_series(dates)
    engaged = empty_series(dates)
    users = empty_series(dates)
    views = empty_series(dates)
    for row in resp.rows:
        raw = row.dimension_values[0].value  # YYYYMMDD
        iso = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
        if iso in sessions:
            sessions[iso] = int(row.metric_values[0].value)
            engaged[iso] = int(row.metric_values[1].value)
            users[iso] = int(row.metric_values[2].value)
            views[iso] = int(row.metric_values[3].value)

    print(f"  [GA4] ok - {len(resp.rows)} day rows")
    return {
        "engaged_sessions": [engaged[d] for d in dates],
        "sessions": [sessions[d] for d in dates],
        "users": [users[d] for d in dates],
        "pageviews": [views[d] for d in dates],
    }


# ----------------------------------------------------------------------------
# Facebook Page Insights  (Meta Graph API)
# ----------------------------------------------------------------------------
def fetch_facebook(cfg, dates):
    fb = cfg.get("facebook") or {}
    page_id = fb.get("page_id")
    token = fb.get("page_access_token")
    if not page_id or not token:
        print("  [Facebook] not configured - skipping")
        return None
    import requests

    ver = cfg.get("meta_api_version", "v21.0")
    since = dates[0]
    until = (dt.date.fromisoformat(dates[-1]) + dt.timedelta(days=1)).isoformat()
    eng = empty_series(dates)

    # Engagement = reactions + comments + shares on each post, bucketed by day.
    # (Page-level engagement metrics were deprecated by Meta, so we aggregate posts.)
    url = f"https://graph.facebook.com/{ver}/{page_id}/posts"
    params = {
        "fields": "created_time,message,shares,"
                  "reactions.summary(true),comments.summary(true)",
        "since": since, "until": until, "limit": 100, "access_token": token,
    }
    records = []  # per-post for the "top content" table
    pages = 0
    while url and pages < 12:
        r = requests.get(url, params=params, timeout=60)
        params = None  # paging 'next' URLs already include all params
        if r.status_code != 200:
            print(f"  [Facebook] API error {r.status_code}: {r.text[:200]}")
            return None
        body = r.json()
        for post in body.get("data", []):
            day = post.get("created_time", "")[:10]
            if day not in eng:
                continue
            react = (post.get("reactions", {}).get("summary", {}) or {}).get("total_count", 0)
            comm = (post.get("comments", {}).get("summary", {}) or {}).get("total_count", 0)
            shar = (post.get("shares", {}) or {}).get("count", 0)
            pe = int(react) + int(comm) + int(shar)
            eng[day] += pe
            records.append({"id": post.get("id"),
                            "title": _clean_title(post.get("message"), "Facebook post"),
                            "eng": pe})
        url = body.get("paging", {}).get("next")
        pages += 1

    # Also include Facebook Reels (a separate edge; not returned by /posts).
    reels_url = f"https://graph.facebook.com/{ver}/{page_id}/video_reels"
    reels_params = {
        "fields": "created_time,likes.summary(true),comments.summary(true)",
        "limit": 100, "access_token": token,
    }
    reels_found = 0
    rpages = 0
    while reels_url and rpages < 8:
        try:
            rr = requests.get(reels_url, params=reels_params, timeout=60)
        except Exception:
            break
        reels_params = None
        if rr.status_code != 200:
            break  # Reels edge unavailable for this page; skip quietly.
        rbody = rr.json()
        stop = False
        for reel in rbody.get("data", []):
            day = (reel.get("created_time", "") or "")[:10]
            if day in eng:
                likes = (reel.get("likes", {}).get("summary", {}) or {}).get("total_count", 0)
                comm = (reel.get("comments", {}).get("summary", {}) or {}).get("total_count", 0)
                eng[day] += int(likes) + int(comm)
                reels_found += 1
            elif day and day < dates[0]:
                stop = True  # newest-first; past the window
        if stop:
            break
        reels_url = rbody.get("paging", {}).get("next")
        rpages += 1

    # Top posts by engagement, with per-post reach (best effort) for the table.
    records.sort(key=lambda x: x["eng"], reverse=True)
    top = []
    for rec in records[:5]:
        if rec["eng"] <= 0:
            break
        reach = 0
        try:
            ir = requests.get(
                f"https://graph.facebook.com/{ver}/{rec['id']}/insights",
                params={"metric": "post_impressions_unique", "access_token": token},
                timeout=60)
            if ir.status_code == 200:
                vals = ir.json().get("data", [])
                if vals and vals[0].get("values"):
                    reach = int(vals[0]["values"][0].get("value") or 0)
        except Exception:
            pass
        top.append({"title": rec["title"], "chan": "fb", "reach": reach, "eng": rec["eng"]})

    print(f"  [Facebook] ok - posts ({pages} page(s)) + {reels_found} reel(s) in range")
    return {"engagement": [eng[d] for d in dates], "top": top}


# ----------------------------------------------------------------------------
# Instagram Insights  (Meta Graph API)
# ----------------------------------------------------------------------------
def fetch_instagram(cfg, dates):
    ig = cfg.get("instagram") or {}
    ig_id = ig.get("ig_user_id")
    token = ig.get("access_token") or (cfg.get("facebook") or {}).get("page_access_token")
    if not ig_id or not token:
        print("  [Instagram] not configured - skipping")
        return None
    import requests

    ver = cfg.get("meta_api_version", "v21.0")
    date_set = set(dates)
    eng = empty_series(dates)

    # Engagement = likes + comments per media item, bucketed by day.
    url = f"https://graph.facebook.com/{ver}/{ig_id}/media"
    params = {"fields": "timestamp,caption,like_count,comments_count",
              "limit": 100, "access_token": token}
    records = []  # per-media for the "top content" table
    pages = 0
    while url and pages < 12:
        r = requests.get(url, params=params, timeout=60)
        params = None
        if r.status_code != 200:
            print(f"  [Instagram] API error {r.status_code}: {r.text[:200]}")
            return None
        body = r.json()
        stop = False
        for m in body.get("data", []):
            day = (m.get("timestamp", "") or "")[:10]
            if day in date_set:
                me = int(m.get("like_count") or 0) + int(m.get("comments_count") or 0)
                eng[day] += me
                records.append({"id": m.get("id"),
                                "title": _clean_title(m.get("caption"), "Instagram post"),
                                "eng": me})
            elif day and day < dates[0]:
                stop = True  # media is reverse-chronological; past the window
        if stop:
            break
        url = body.get("paging", {}).get("next")
        pages += 1

    result = {"engagement": [eng[d] for d in dates]}

    # Top media by engagement, with per-media reach (best effort) for the table.
    records.sort(key=lambda x: x["eng"], reverse=True)
    top = []
    for rec in records[:5]:
        if rec["eng"] <= 0:
            break
        reach = 0
        try:
            ir = requests.get(
                f"https://graph.facebook.com/{ver}/{rec['id']}/insights",
                params={"metric": "reach", "access_token": token}, timeout=60)
            if ir.status_code == 200:
                vals = ir.json().get("data", [])
                if vals and vals[0].get("values"):
                    reach = int(vals[0]["values"][0].get("value") or 0)
        except Exception:
            pass
        top.append({"title": rec["title"], "chan": "ig", "reach": reach, "eng": rec["eng"]})
    result["top"] = top

    # Reach (optional) in <=30-day chunks; non-fatal if it errors.
    try:
        reach = empty_series(dates)
        start = dt.date.fromisoformat(dates[0]); end = dt.date.fromisoformat(dates[-1])
        win = start
        while win <= end:
            wend = min(win + dt.timedelta(days=29), end)
            rr = requests.get(
                f"https://graph.facebook.com/{ver}/{ig_id}/insights",
                params={"metric": "reach", "period": "day",
                        "since": win.isoformat(),
                        "until": (wend + dt.timedelta(days=1)).isoformat(),
                        "access_token": token}, timeout=60)
            if rr.status_code == 200:
                for metric in rr.json().get("data", []):
                    for v in metric.get("values", []):
                        d = v.get("end_time", "")[:10]
                        if d in reach:
                            reach[d] = int(v.get("value") or 0)
            win = wend + dt.timedelta(days=1)
        result["reach"] = [reach[d] for d in dates]
    except Exception as e:
        print(f"  [Instagram] reach skipped ({e})")

    print(f"  [Instagram] ok - engagement from media ({pages} page(s))")
    return result


# ----------------------------------------------------------------------------
# YouTube Analytics API
# ----------------------------------------------------------------------------
def fetch_youtube(cfg, dates):
    yt = cfg.get("youtube") or {}
    client_secret = yt.get("oauth_client_secret_json")
    token_file = yt.get("token_json", "youtube_token.json")
    if not client_secret:
        print("  [YouTube] not configured - skipping")
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as e:
        print(f"  [YouTube] import failed: {e} - skipping")
        return None

    scopes = ["https://www.googleapis.com/auth/yt-analytics.readonly",
              "https://www.googleapis.com/auth/youtube.readonly"]
    token_path = token_file if os.path.isabs(token_file) else os.path.join(HERE, token_file)
    secret_path = client_secret if os.path.isabs(client_secret) else os.path.join(HERE, client_secret)

    creds = None
    granted = set()
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                tok = json.load(f)
            granted = set(tok.get("scopes") or [])          # actual granted scopes
            creds = Credentials.from_authorized_user_info(tok, scopes)
        except Exception:
            creds = None
    has_all = set(scopes).issubset(granted)
    headless = bool(os.environ.get("DASHBOARD_HEADLESS"))
    if (not creds) or (not creds.valid) or (not has_all):
        if creds and creds.expired and creds.refresh_token and has_all:
            creds.refresh(Request())
        elif headless:
            # In GitHub Actions / any server: never open a browser.
            print("  [YouTube] token needs re-auth but running headless - skipping "
                  "(run run_dashboard.bat locally once to refresh youtube_token.json).")
            return None
        else:
            # Missing/added scope -> full re-authorization in the browser.
            flow = InstalledAppFlow.from_client_secrets_file(secret_path, scopes)
            creds = flow.run_local_server(port=0)
        try:
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception:
            pass

    yta = build("youtubeAnalytics", "v2", credentials=creds)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=dates[0],
        endDate=dates[-1],
        metrics="views,estimatedMinutesWatched,likes,comments,shares,subscribersGained",
        dimensions="day",
    ).execute()

    views = empty_series(dates)
    likes = empty_series(dates)
    comments = empty_series(dates)
    shares = empty_series(dates)
    subs = empty_series(dates)
    watch = empty_series(dates)
    for row in resp.get("rows", []):
        day = row[0]
        if day in views:
            views[day] = int(row[1])
            watch[day] = int(row[2])
            likes[day] = int(row[3])
            comments[day] = int(row[4])
            shares[day] = int(row[5])
            subs[day] = int(row[6])

    eng = [likes[d] + comments[d] + shares[d] for d in dates]
    out = {
        "views": [views[d] for d in dates],
        "engagement": eng,
        "watch_minutes": [watch[d] for d in dates],
        "subscribers_gained": [subs[d] for d in dates],
    }

    # Top videos by views (+ titles & current subscriber count via Data API v3).
    try:
        topresp = yta.reports().query(
            ids="channel==MINE", startDate=dates[0], endDate=dates[-1],
            metrics="views,likes,comments", dimensions="video",
            sort="-views", maxResults=5,
        ).execute()
        vid_rows = topresp.get("rows", [])
        vid_ids = [r[0] for r in vid_rows]

        yt_data = build("youtube", "v3", credentials=creds)
        titles = {}
        if vid_ids:
            vresp = yt_data.videos().list(part="snippet", id=",".join(vid_ids)).execute()
            for item in vresp.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]

        cresp = yt_data.channels().list(part="statistics", mine=True).execute()
        citems = cresp.get("items", [])
        if citems:
            out["subscriber_count"] = int(citems[0]["statistics"].get("subscriberCount") or 0)

        top = []
        for r in vid_rows:
            v = int(r[1]); lk = int(r[2]); cm = int(r[3])
            top.append({"title": _clean_title(titles.get(r[0], "YouTube video"), "YouTube video"),
                        "chan": "yt", "reach": v, "eng": lk + cm})
        out["top"] = top
    except Exception as e:
        print(f"  [YouTube] top videos / subscriber count skipped ({e})")

    print(f"  [YouTube] ok - {len(resp.get('rows', []))} day rows")
    return out


# ----------------------------------------------------------------------------
# Top website pages (Google Analytics Data API)
# ----------------------------------------------------------------------------
def fetch_ga4_pages(cfg, dates):
    ga = cfg.get("google_analytics") or {}
    prop = ga.get("property_id")
    key_file = ga.get("service_account_json")
    if not prop or not key_file:
        return []
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest, OrderBy,
        )
        from google.oauth2 import service_account
    except ImportError:
        return []

    key_path = key_file if os.path.isabs(key_file) else os.path.join(HERE, key_file)
    creds = service_account.Credentials.from_service_account_file(key_path)
    client = BetaAnalyticsDataClient(credentials=creds)
    req = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="pageTitle")],
        metrics=[Metric(name="screenPageViews"), Metric(name="engagedSessions")],
        date_ranges=[DateRange(start_date=dates[0], end_date=dates[-1])],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=5,
    )
    resp = client.run_report(req)
    out = []
    for row in resp.rows:
        title = row.dimension_values[0].value or "(page)"
        views = int(row.metric_values[0].value)
        engaged = int(row.metric_values[1].value)
        if views <= 0:
            continue
        out.append({"title": _clean_title(title, "Web page"), "chan": "web",
                    "reach": views, "eng": engaged})
    return out


# ----------------------------------------------------------------------------
# Google Search Console (how people find the site in Google Search)
# ----------------------------------------------------------------------------
def fetch_search_console(cfg, dates):
    sc = cfg.get("search_console") or {}
    ga = cfg.get("google_analytics") or {}
    key_file = sc.get("service_account_json") or ga.get("service_account_json")
    if not key_file:
        print("  [Search] not configured - skipping")
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        print(f"  [Search] import failed: {e} - skipping")
        return None

    key_path = key_file if os.path.isabs(key_file) else os.path.join(HERE, key_file)
    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=scopes)
    svc = build("searchconsole", "v1", credentials=creds)

    site_url = sc.get("site_url") or None
    if not site_url:
        domain = sc.get("domain", "")
        try:
            sites = svc.sites().list().execute().get("siteEntry", [])
        except Exception as e:
            print(f"  [Search] could not list properties ({e}) - is the service account added in Search Console?")
            return None
        cand = [s["siteUrl"] for s in sites if domain in s.get("siteUrl", "")]
        cand.sort(key=lambda u: 0 if u.startswith("sc-domain:") else 1)  # prefer domain property
        site_url = cand[0] if cand else None
    if not site_url:
        print("  [Search] no matching property found - add the service account as a user in Search Console.")
        return None

    def query(dimensions, limit):
        body = {"startDate": dates[0], "endDate": dates[-1],
                "dimensions": dimensions, "rowLimit": limit}
        return svc.searchanalytics().query(siteUrl=site_url, body=body).execute().get("rows", [])

    clicks = empty_series(dates)
    impr = empty_series(dates)
    for row in query(["date"], 1000):
        d = row["keys"][0]
        if d in clicks:
            clicks[d] = int(row.get("clicks") or 0)
            impr[d] = int(round(row.get("impressions") or 0))

    queries = []
    for row in query(["query"], 10):
        queries.append({"query": row["keys"][0],
                        "clicks": int(row.get("clicks") or 0),
                        "impressions": int(round(row.get("impressions") or 0)),
                        "position": round(row.get("position") or 0, 1)})

    print(f"  [Search] ok - {site_url}")
    return {"clicks": [clicks[d] for d in dates],
            "impressions": [impr[d] for d in dates],
            "queries": queries, "site": site_url}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    cfg = load_config()
    days = int(cfg.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    start, end = date_range(days)
    dates = daily_buckets(start, end)

    print(f"Fetching {days} days: {dates[0]} -> {dates[-1]}")
    result = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "church": "Gaston Community Church",
        "dates": dates,
        "channels": {},
    }

    for name, fn in (
        ("web", fetch_ga4),
        ("fb", fetch_facebook),
        ("ig", fetch_instagram),
        ("yt", fetch_youtube),
    ):
        try:
            data = fn(cfg, dates)
        except Exception as e:  # keep going even if one platform fails
            print(f"  [{name}] error: {e}")
            data = None
        if data:
            result["channels"][name] = data

    # Assemble the "top performing content" list across channels.
    # Top content: take each channel's best so every channel is represented
    # (a single global sort by engagement would bury YouTube, whose engagement
    #  is low even when view counts are healthy).
    top_content = []
    try:
        top_content += fetch_ga4_pages(cfg, dates)[:4]
    except Exception as e:
        print(f"  [top content] web pages skipped: {e}")
    for ch_name in ("ig", "fb", "yt"):
        top_content += (result["channels"].get(ch_name, {}).get("top") or [])[:3]
        result["channels"].get(ch_name, {}).pop("top", None)  # keep channel dict clean
    result["top_content"] = top_content

    # Google Search Console (separate from the engagement channels).
    try:
        search = fetch_search_console(cfg, dates)
        if search:
            result["search"] = search
    except Exception as e:
        print(f"  [Search] error: {e}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    with open(OUTPUT_JS, "w", encoding="utf-8") as f:
        f.write("window.ENGAGEMENT_DATA = ")
        json.dump(result, f)
        f.write(";\n")

    got = ", ".join(result["channels"].keys()) or "none yet"
    print(f"\nWrote engagement-data.js and engagement-data.json")
    print(f"Channels with data: {got}")


if __name__ == "__main__":
    main()
