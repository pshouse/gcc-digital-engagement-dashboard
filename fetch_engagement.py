#!/usr/bin/env python3
"""
fetch_engagement.py
-------------------
Pulls digital-engagement data for Gaston Community Church from the free,
official platform APIs and writes a single data file the dashboard reads:

    - Google Analytics 4   -> Google Analytics Data API
    - Facebook Page        -> Meta Graph API (Page Insights)
    - Instagram            -> Meta Graph API (Instagram Insights)
    - YouTube channel      -> YouTube Analytics API (Shorts split out)
    - Facebook Reels       -> Meta Graph API (Page video_reels + video_insights)

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


def _is_shorts_type(ctype):
    """creatorContentType comes back as 'shorts' in practice, 'SHORTS' per the docs."""
    return str(ctype or "").replace("_", "").lower() == "shorts"


def _iso_seconds(iso):
    """ISO-8601 duration from the YouTube Data API (PT1M30S) -> 90."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, sec = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + sec


SHORT_MAX_SECONDS = 180  # YouTube Shorts can be up to 3 minutes


def _clean_title(text, fallback, n=70):
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return fallback
    return t[:n] + ("…" if len(t) > n else "")


# GA4 reports a missing page_title as "(not set)" (or an empty string), which
# collapses every untitled page into a single meaningless row. When that
# happens, name the page after its URL path instead.
MISSING_TITLES = {"(not set)", "(none)", "(other)", "(page)"}


def _page_label(title, path):
    t = (title or "").strip()
    if t and t.lower() not in MISSING_TITLES:
        return _clean_title(t, "Web page")
    seg = (path or "").split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    for ext in (".dc.html", ".html", ".htm", ".php"):
        if seg.lower().endswith(ext):
            seg = seg[: -len(ext)]
            break
    seg = seg.replace("-", " ").replace("_", " ").strip()
    if not seg:
        return "Home"
    return _clean_title(seg[:1].upper() + seg[1:], "Web page")


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
def _meta_reach(ver, obj_id, token, metric):
    """Best-effort unique reach for a post / media item via the Insights edge."""
    import requests
    try:
        ir = requests.get(
            f"https://graph.facebook.com/{ver}/{obj_id}/insights",
            params={"metric": metric, "access_token": token}, timeout=60)
        if ir.status_code == 200:
            vals = ir.json().get("data", [])
            if vals and vals[0].get("values"):
                return int(vals[0]["values"][0].get("value") or 0)
    except Exception:
        pass
    return 0


def _norm_text(t):
    return " ".join((t or "").split()).lower()[:120]


def _reel_insights(vi):
    """Pull (plays, reach) out of a nested video_insights expansion."""
    found = {}
    for m in ((vi or {}).get("data") or []):
        vals = m.get("values") or []
        if vals:
            try:
                found[m.get("name")] = int(vals[0].get("value") or 0)
            except (TypeError, ValueError):
                pass
    plays = found.get("blue_reels_play_count") or found.get("fb_reels_total_plays") or 0
    reach = found.get("post_impressions_unique") or 0
    return plays, reach


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
    # attachments{target} exposes the video id of a Reel post, so Reels returned
    # by BOTH /posts and /video_reels can be matched up and counted once.
    url = f"https://graph.facebook.com/{ver}/{page_id}/posts"
    params = {
        "fields": "created_time,message,shares,"
                  "reactions.summary(true),comments.summary(true),"
                  "attachments{media_type,target}",
        "since": since, "until": until, "limit": 100, "access_token": token,
    }
    records = []  # per-post for the "top content" table
    post_by_vid = {}
    post_by_text = {}
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
            rec = {"id": post.get("id"),
                   "title": _clean_title(post.get("message"), "Facebook post"),
                   "eng": pe, "day": day}
            records.append(rec)
            for att in ((post.get("attachments") or {}).get("data") or []):
                vid = ((att.get("target") or {}).get("id"))
                if vid:
                    post_by_vid.setdefault(vid, rec)
            key = (day, _norm_text(post.get("message")))
            if key[1]:
                post_by_text.setdefault(key, rec)
        url = body.get("paging", {}).get("next")
        pages += 1

    # Facebook Reels live on a separate edge (not returned by /posts). Pull
    # likes + comments AND play counts so Reels can be shown on their own.
    # Plays are lifetime totals attributed to the day the Reel was published.
    reels_eng = empty_series(dates)
    reels_plays = empty_series(dates)
    reels_found = 0
    reels_with_plays = 0
    reels_ok = False
    probe_id = None
    basic_fields = "created_time,title,description,likes.summary(true),comments.summary(true)"
    insight_fields = (basic_fields + ",video_insights.metric("
                      "blue_reels_play_count,fb_reels_total_plays,post_impressions_unique)")
    reels_url = f"https://graph.facebook.com/{ver}/{page_id}/video_reels"
    reels_params = {"fields": insight_fields, "limit": 100, "access_token": token}
    rpages = 0
    while reels_url and rpages < 8:
        try:
            rr = requests.get(reels_url, params=reels_params, timeout=60)
        except Exception:
            break
        if rr.status_code != 200 and reels_params and reels_params["fields"] == insight_fields:
            # Token can't expand video_insights -> retry once without play counts.
            reels_params["fields"] = basic_fields
            continue
        reels_params = None
        if rr.status_code != 200:
            break  # Reels edge unavailable for this page; skip quietly.
        reels_ok = True
        rbody = rr.json()
        stop = False
        for reel in rbody.get("data", []):
            day = (reel.get("created_time", "") or "")[:10]
            if day and day < dates[0]:
                stop = True  # newest-first; past the window
                continue
            if day not in eng:
                continue
            likes = (reel.get("likes", {}).get("summary", {}) or {}).get("total_count", 0)
            comm = (reel.get("comments", {}).get("summary", {}) or {}).get("total_count", 0)
            re_eng = int(likes) + int(comm)
            plays, reach = _reel_insights(reel.get("video_insights"))
            text = reel.get("description") or reel.get("title")
            reels_found += 1
            probe_id = probe_id or reel.get("id")
            if plays:
                reels_with_plays += 1
            reels_plays[day] += plays
            # The same Reel usually also shows up in /posts (with reactions and
            # shares). Reuse that record instead of counting it a second time.
            rec = post_by_vid.get(reel.get("id")) or post_by_text.get((day, _norm_text(text)))
            if rec is None:
                eng[day] += re_eng
                rec = {"id": reel.get("id"), "title": _clean_title(text, "Facebook Reel"),
                       "eng": re_eng, "day": day}
                records.append(rec)
            rec["kind"] = "reel"
            rec["plays"] = plays
            rec["reach"] = reach or plays
            reels_eng[day] += rec["eng"]
        if stop:
            break
        reels_url = rbody.get("paging", {}).get("next")
        rpages += 1

    # When the Reels came back without play counts, ask for one Reel's insights
    # directly so the log says WHY (usually the token is missing read_insights).
    if reels_found and not reels_with_plays and probe_id:
        try:
            pr = requests.get(
                f"https://graph.facebook.com/{ver}/{probe_id}/video_insights",
                params={"metric": "blue_reels_play_count", "access_token": token}, timeout=60)
            msg = (pr.json().get("error") or {}).get("message") if pr.status_code != 200 else "empty result"
            print(f"  [Facebook] Reels play counts unavailable: HTTP {pr.status_code} - {msg} "
                  "(the Page token needs read_insights)")
        except Exception as e:
            print(f"  [Facebook] Reels play counts unavailable ({e})")

    # Top content by engagement (posts and Reels compete on equal footing).
    # Reach comes from the Reel insights when we have it, else one insights call.
    def entry(rec):
        if "reach" not in rec:
            rec["reach"] = _meta_reach(ver, rec["id"], token, "post_impressions_unique")
        e = {"title": rec["title"], "chan": "fb", "reach": rec["reach"], "eng": rec["eng"]}
        if rec.get("kind"):
            e["kind"] = rec["kind"]
        return e

    records.sort(key=lambda x: x["eng"], reverse=True)
    top = [entry(rec) for rec in records[:5] if rec["eng"] > 0]

    # Top Reels for the short-form panel, ranked by plays (then engagement).
    reels = sorted((r for r in records if r.get("kind") == "reel"),
                   key=lambda r: (r["plays"], r["eng"]), reverse=True)
    top_short = [dict(entry(r), plays=r["plays"]) for r in reels[:3]
                 if r["plays"] > 0 or r["eng"] > 0]

    out = {"engagement": [eng[d] for d in dates], "top": top, "top_short": top_short}
    if reels_ok:
        out["reels"] = {"engagement": [reels_eng[d] for d in dates],
                        "plays": [reels_plays[d] for d in dates],
                        "count": reels_found}
    print(f"  [Facebook] ok - posts ({pages} page(s)) + {reels_found} reel(s) in range"
          + ("" if reels_ok else " (Reels edge unavailable)"))
    return out


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
    # media_product_type lets us tag Reels in the top-content tables.
    url = f"https://graph.facebook.com/{ver}/{ig_id}/media"
    params = {"fields": "timestamp,caption,like_count,comments_count,media_product_type",
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
                is_reel = (m.get("media_product_type") or "").upper() == "REELS"
                records.append({"id": m.get("id"),
                                "title": _clean_title(m.get("caption"),
                                                      "Instagram Reel" if is_reel else "Instagram post"),
                                "eng": me, "kind": "reel" if is_reel else None})
            elif day and day < dates[0]:
                stop = True  # media is reverse-chronological; past the window
        if stop:
            break
        url = body.get("paging", {}).get("next")
        pages += 1

    result = {"engagement": [eng[d] for d in dates]}

    # Top media by engagement, with per-media reach (best effort) for the table,
    # plus the top Reels for the short-form panel. Reach is looked up once per item.
    records.sort(key=lambda x: x["eng"], reverse=True)
    reach_cache = {}

    def entry(rec):
        if rec["id"] not in reach_cache:
            reach_cache[rec["id"]] = _meta_reach(ver, rec["id"], token, "reach")
        e = {"title": rec["title"], "chan": "ig", "reach": reach_cache[rec["id"]], "eng": rec["eng"]}
        if rec["kind"]:
            e["kind"] = rec["kind"]
        return e

    result["top"] = [entry(rec) for rec in records[:5] if rec["eng"] > 0]
    result["top_short"] = [entry(rec) for rec in
                           [r for r in records if r["kind"] == "reel"][:3] if rec["eng"] > 0]

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
    metrics = "views,estimatedMinutesWatched,likes,comments,shares,subscribersGained"

    # Daily stats split by content type so Shorts can be reported separately.
    # (creatorContentType: shorts / videoOnDemand / liveStream / story.)
    # Falls back to a plain per-day query if the split is unavailable.
    split_ok = True
    try:
        resp = yta.reports().query(
            ids="channel==MINE", startDate=dates[0], endDate=dates[-1],
            metrics=metrics, dimensions="day,creatorContentType",
        ).execute()
    except Exception as e:
        print(f"  [YouTube] Shorts split unavailable ({e}); using channel totals only")
        split_ok = False
        resp = yta.reports().query(
            ids="channel==MINE", startDate=dates[0], endDate=dates[-1],
            metrics=metrics, dimensions="day",
        ).execute()

    views = empty_series(dates)
    likes = empty_series(dates)
    comments = empty_series(dates)
    shares = empty_series(dates)
    subs = empty_series(dates)
    watch = empty_series(dates)
    s_views = empty_series(dates)
    s_eng = empty_series(dates)
    s_watch = empty_series(dates)
    for row in resp.get("rows", []):
        day = row[0]
        if day not in views:
            continue
        ctype = row[1] if split_ok else None
        vals = row[2:] if split_ok else row[1:]
        v, w, lk, cm, sh, sg = (int(x) for x in vals[:6])
        views[day] += v
        watch[day] += w
        likes[day] += lk
        comments[day] += cm
        shares[day] += sh
        subs[day] += sg
        if _is_shorts_type(ctype):
            s_views[day] += v
            s_watch[day] += w
            s_eng[day] += lk + cm + sh

    eng = [likes[d] + comments[d] + shares[d] for d in dates]
    out = {
        "views": [views[d] for d in dates],
        "engagement": eng,
        "watch_minutes": [watch[d] for d in dates],
        "subscribers_gained": [subs[d] for d in dates],
    }
    if split_ok:
        out["shorts"] = {
            "views": [s_views[d] for d in dates],
            "engagement": [s_eng[d] for d in dates],
            "watch_minutes": [s_watch[d] for d in dates],
        }

    # Top videos by views (+ titles & current subscriber count via Data API v3).
    # The Analytics API cannot combine the video and content-type dimensions,
    # so a video counts as a Short when its Data API duration is <= 3 minutes.
    try:
        topresp = yta.reports().query(
            ids="channel==MINE", startDate=dates[0], endDate=dates[-1],
            metrics="views,likes,comments", dimensions="video",
            sort="-views", maxResults=50,
        ).execute()
        ranked = [{"id": r[0], "views": int(r[1]), "eng": int(r[2]) + int(r[3]), "short": False}
                  for r in topresp.get("rows", [])]

        yt_data = build("youtube", "v3", credentials=creds)
        titles = {}
        for i in range(0, len(ranked), 50):
            chunk = ranked[i:i + 50]
            vresp = yt_data.videos().list(
                part="snippet,contentDetails", id=",".join(x["id"] for x in chunk)).execute()
            info = {item["id"]: item for item in vresp.get("items", [])}
            for x in chunk:
                item = info.get(x["id"])
                if not item:
                    continue
                titles[x["id"]] = item["snippet"]["title"]
                secs = _iso_seconds(item.get("contentDetails", {}).get("duration"))
                x["short"] = 0 < secs <= SHORT_MAX_SECONDS
        top_all = ranked[:5]
        top_shorts = [x for x in ranked if x["short"]][:3]

        cresp = yt_data.channels().list(part="statistics", mine=True).execute()
        citems = cresp.get("items", [])
        if citems:
            out["subscriber_count"] = int(citems[0]["statistics"].get("subscriberCount") or 0)

        def entry(x):
            fallback = "YouTube Short" if x["short"] else "YouTube video"
            e = {"title": _clean_title(titles.get(x["id"], fallback), fallback),
                 "chan": "yt", "reach": x["views"], "eng": x["eng"]}
            if x["short"]:
                e["kind"] = "short"
            return e

        out["top"] = [entry(x) for x in top_all]
        out["top_short"] = [dict(entry(x), plays=x["views"]) for x in top_shorts]
    except Exception as e:
        print(f"  [YouTube] top videos / subscriber count skipped ({e})")

    n_short = sum(s_views.values())
    print(f"  [YouTube] ok - {len(resp.get('rows', []))} rows"
          + (f", {n_short} Shorts views" if split_ok else ""))
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
        dimensions=[Dimension(name="pageTitle"), Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews"), Metric(name="engagedSessions")],
        date_ranges=[DateRange(start_date=dates[0], end_date=dates[-1])],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=5,
    )
    resp = client.run_report(req)
    out = []
    for row in resp.rows:
        title = row.dimension_values[0].value
        path = row.dimension_values[1].value
        views = int(row.metric_values[0].value)
        engaged = int(row.metric_values[1].value)
        if views <= 0:
            continue
        out.append({"title": _page_label(title, path), "chan": "web",
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
    top_short = []  # YouTube Shorts + Facebook / Instagram Reels for the short-form panel
    for ch_name in ("ig", "fb", "yt"):
        chd = result["channels"].get(ch_name, {})
        top_content += (chd.pop("top", None) or [])[:3]   # pop: keep channel dict clean
        top_short += (chd.pop("top_short", None) or [])[:3]
    result["top_content"] = top_content
    result["top_shortform"] = top_short

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
