#!/usr/bin/env python3
"""
diagnose_youtube.py
-------------------
Prints what the YouTube Analytics API reports per video, with its content
type (SHORTS / VIDEO_ON_DEMAND / LIVE_STREAM), next to the public view count
from the Data API. Use it when the dashboard's Shorts numbers look wrong.

Run locally:   python diagnose_youtube.py
In the cloud:  Actions -> "Diagnose YouTube" -> Run workflow, then read the log.
"""

import datetime as dt
import json
import os
import re
import sys

import fetch_engagement as fe


def _seconds(iso):
    """PT1M30S -> 90."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def main():
    cfg = fe.load_config()
    yt = cfg.get("youtube") or {}
    token_file = yt.get("token_json", "youtube_token.json")
    token_path = token_file if os.path.isabs(token_file) else os.path.join(fe.HERE, token_file)
    if not os.path.exists(token_path):
        sys.exit("No youtube_token.json - run fetch_engagement.py once first.")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(token_path, "r", encoding="utf-8") as f:
        creds = Credentials.from_authorized_user_info(json.load(f))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    days = int(cfg.get("lookback_days", fe.DEFAULT_LOOKBACK_DAYS))
    start, end = fe.date_range(days)
    print(f"Window: {start} -> {end}\n")

    yta = build("youtubeAnalytics", "v2", credentials=creds)
    data = build("youtube", "v3", credentials=creds)

    # 1. Channel totals per content type.
    print("== Analytics totals by content type ==")
    try:
        r = yta.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                                metrics="views,engagedViews,likes,comments",
                                dimensions="creatorContentType").execute()
        for row in r.get("rows", []):
            print(f"  {row[0]:<16} views={row[1]:<6} engagedViews={row[2]:<6} likes={row[3]} comments={row[4]}")
        if not r.get("rows"):
            print("  (no rows)")
    except Exception as e:
        print(f"  query failed: {e}")

    # 2. Per-video Analytics rows with content type.
    print("\n== Analytics per video (top 200 by views) ==")
    rows = []
    try:
        r = yta.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                                metrics="views,engagedViews,likes,comments",
                                dimensions="video,creatorContentType",
                                sort="-views", maxResults=200).execute()
        rows = r.get("rows", [])
    except Exception as e:
        print(f"  query failed: {e}")
    by_vid = {}
    for row in rows:
        by_vid.setdefault(row[0], []).append(row)

    # 3. Every upload in the window from the Data API, with duration + public views.
    print("\n== Uploads in window (Data API) vs Analytics ==")
    ch = data.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        pl = data.playlistItems().list(part="contentDetails", playlistId=uploads,
                                       maxResults=50, pageToken=page).execute()
        for it in pl.get("items", []):
            pub = (it["contentDetails"].get("videoPublishedAt") or "")[:10]
            if pub and pub >= str(start):
                ids.append(it["contentDetails"]["videoId"])
        page = pl.get("nextPageToken")
        if not page or len(ids) >= 200:
            break

    looks_short_no_rows = 0
    for i in range(0, len(ids), 50):
        vr = data.videos().list(part="snippet,contentDetails,statistics",
                                id=",".join(ids[i:i + 50])).execute()
        for v in vr.get("items", []):
            secs = _seconds(v["contentDetails"].get("duration"))
            public = int(v["statistics"].get("viewCount") or 0)
            title = fe._clean_title(v["snippet"]["title"], "?", 45)
            looks_short = secs <= 180
            arows = by_vid.get(v["id"], [])
            types = ", ".join(f"{a[1]}={a[2]}v/{a[3]}ev" for a in arows) or "NO ANALYTICS ROWS"
            flag = ""
            if looks_short and not any(a[1] == "SHORTS" for a in arows):
                flag = "  <-- looks like a Short but not reported as SHORTS"
                if not arows:
                    looks_short_no_rows += 1
            print(f"  {v['id']}  {v['snippet']['publishedAt'][:10]}  {secs:>4}s  public={public:<5} "
                  f"{title:<46} {types}{flag}")

    n_short_rows = sum(1 for r in rows if r[1] == "SHORTS")
    print(f"\nAnalytics rows tagged SHORTS: {n_short_rows}; "
          f"short-looking uploads with no Analytics rows at all: {looks_short_no_rows}")
    print("If public views > 0 but there are no Analytics rows, Analytics has not "
          "recorded those views (it excludes some plays, e.g. from the channel's own "
          "account or unlisted embeds). If rows exist but are VIDEO_ON_DEMAND, the "
          "views came through the regular watch page, not the Shorts player.")


if __name__ == "__main__":
    main()
