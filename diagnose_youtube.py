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

import json
import os
import sys

import fetch_engagement as fe
from fetch_engagement import _iso_seconds as _seconds, _is_shorts_type, SHORT_MAX_SECONDS


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
    totals = []
    try:
        r = yta.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                                metrics="views,engagedViews,likes,comments",
                                dimensions="creatorContentType").execute()
        totals = r.get("rows", [])
        for row in totals:
            print(f"  {row[0]:<16} views={row[1]:<6} engagedViews={row[2]:<6} likes={row[3]} comments={row[4]}")
        if not r.get("rows"):
            print("  (no rows)")
    except Exception as e:
        print(f"  query failed: {e}")

    # 2. Per-video Analytics rows. (The API refuses video + creatorContentType
    #    together, so Shorts are identified by duration below.)
    print("\n== Analytics per video (top 200 by views) ==")
    rows = []
    try:
        r = yta.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                                metrics="views,engagedViews,likes,comments",
                                dimensions="video", sort="-views", maxResults=200).execute()
        rows = r.get("rows", [])
        print(f"  {len(rows)} video(s) with activity")
    except Exception as e:
        print(f"  query failed: {e}")
    by_vid = {row[0]: row for row in rows}

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

    n_short = n_short_views = 0
    for i in range(0, len(ids), 50):
        vr = data.videos().list(part="snippet,contentDetails,statistics",
                                id=",".join(ids[i:i + 50])).execute()
        for v in vr.get("items", []):
            secs = _seconds(v["contentDetails"].get("duration"))
            public = int(v["statistics"].get("viewCount") or 0)
            title = fe._clean_title(v["snippet"]["title"], "?", 45)
            is_short = 0 < secs <= SHORT_MAX_SECONDS
            arow = by_vid.get(v["id"])
            analytics = f"analytics={arow[1]}v/{arow[2]}ev" if arow else "no analytics rows"
            kind = "SHORT" if is_short else ("live/upcoming" if secs == 0 else "video")
            if is_short:
                n_short += 1
                n_short_views += int(arow[1]) if arow else 0
            print(f"  {v['id']}  {v['snippet']['publishedAt'][:10]}  {secs:>5}s  {kind:<14} "
                  f"public={public:<5} {analytics:<22} {title}")

    shorts_total = next((int(r[1]) for r in totals if _is_shorts_type(r[0])), 0)
    print(f"\nShorts by duration (<= {SHORT_MAX_SECONDS}s): {n_short} upload(s), "
          f"{n_short_views} Analytics views; Analytics 'shorts' content-type total: {shorts_total}")
    print("Public view counts include plays Analytics filters out (e.g. from the "
          "channel's own account), so small differences are normal.")


if __name__ == "__main__":
    main()
