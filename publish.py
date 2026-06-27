#!/usr/bin/env python3
"""
publish.py
----------
Publishes the dashboard to a free Netlify site so church leadership can view it
at a permanent web link that updates whenever the data is refreshed.

SECURITY: this uploads ONLY two files — the dashboard page and its data file.
It never uploads config.json, service-account keys, or OAuth tokens.

One-time setup:
  1. Create a free account at https://app.netlify.com
  2. User settings -> Applications -> Personal access tokens -> New access token
  3. Paste that token as the ONLY contents of a file named  netlify_token.txt
     in this folder (no quotes, no JSON — just the token).

After that, running this (it's called automatically by run_dashboard.bat) will:
  - create the Netlify site on first run (saving its id to netlify_site.json)
  - deploy the latest dashboard
  - print the public URL
"""

import io
import json
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "netlify_site.json")
TOKEN_FILE = os.path.join(HERE, "netlify_token.txt")
API = "https://api.netlify.com/api/v1"

# Only these files are ever uploaded (renamed to site root):
UPLOADS = {
    "engagement-dashboard.html": "index.html",
    "engagement-data.js": "engagement-data.js",
}


def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    if os.environ.get("NETLIFY_TOKEN"):
        return os.environ["NETLIFY_TOKEN"].strip()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return ((json.load(f).get("share") or {}).get("netlify_token") or "").strip()
    except Exception:
        return ""


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def publish_min_hours():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return float((json.load(f).get("share") or {}).get("publish_min_hours", 80))
    except Exception:
        return 80.0


def main():
    force = "--force" in sys.argv
    token = get_token()
    if not token:
        print("  [Publish] no Netlify token found - skipping web publish.")
        print("            (Create netlify_token.txt with your token to enable it.)")
        return

    import requests
    headers = {"Authorization": f"Bearer {token}"}

    state = load_state()
    site_id = state.get("site_id")
    site_url = state.get("url")

    # Throttle deploys to protect the free credit budget (deploys cost ~15 credits
    # each; ~20/month fits the free plan). Skip if we published recently, unless
    # forced (a manual run) or the site doesn't exist yet.
    min_h = publish_min_hours()
    last = state.get("last_publish")
    if site_id and not force and last and (time.time() - last) < min_h * 3600:
        remaining = (min_h * 3600 - (time.time() - last)) / 3600
        print(f"  [Publish] up to date; next web update in ~{remaining:.0f}h "
              f"(double-click publish_now.bat to push sooner).")
        return

    # Create the site once.
    if not site_id:
        r = requests.post(f"{API}/sites", headers=headers, json={}, timeout=60)
        if r.status_code not in (200, 201):
            print(f"  [Publish] could not create site: {r.status_code} {r.text[:200]}")
            return
        site = r.json()
        site_id = site.get("id")
        site_url = site.get("ssl_url") or site.get("url")
        save_state({"site_id": site_id, "url": site_url})
        print(f"  [Publish] created Netlify site: {site_url}")

    # Build an in-memory zip with ONLY the dashboard + data.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for src, dest in UPLOADS.items():
            p = os.path.join(HERE, src)
            if os.path.exists(p):
                z.write(p, dest)
    buf.seek(0)

    deploy_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/zip"}
    r = requests.post(f"{API}/sites/{site_id}/deploys",
                      headers=deploy_headers, data=buf.read(), timeout=180)
    if r.status_code not in (200, 201):
        print(f"  [Publish] deploy failed: {r.status_code} {r.text[:200]}")
        return

    if not site_url:
        s = requests.get(f"{API}/sites/{site_id}", headers=headers, timeout=60)
        if s.status_code == 200:
            site_url = s.json().get("ssl_url") or s.json().get("url")

    state.update({"site_id": site_id, "url": site_url, "last_publish": time.time()})
    save_state(state)
    print(f"  [Publish] dashboard published: {site_url}")


if __name__ == "__main__":
    main()
