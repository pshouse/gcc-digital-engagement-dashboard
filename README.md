# Gaston Community Church — Digital Engagement Dashboard

A self-hosted dashboard that pulls Gaston Community Church's digital engagement
numbers straight from each platform's free official API and renders them as a
single web page. No third-party aggregator, no subscription — you supply your own
credentials.

**Channels covered**

| Channel | Source API |
|---|---|
| Website | Google Analytics 4 (Analytics Data API) |
| Facebook Page | Meta Graph API — Page Insights |
| Instagram | Meta Graph API — Instagram Insights |
| YouTube (incl. Shorts) | YouTube Analytics API |
| Facebook Reels | Meta Graph API — Page `video_reels` + `video_insights` |
| Google Search visibility | Google Search Console API |

Each platform is fetched independently, so the dashboard lights up channel by
channel as you configure them — anything not set up yet is simply skipped.

## What the dashboard shows

- Total engagement & reach across all channels
- Engagement actions over time, by channel, plus each channel's share of the total
- Google Search clicks & impressions
- Audience growth — followers and subscribers
- Short-form video — YouTube Shorts views and Facebook Reels plays per day, with
  the top Shorts & Reels (Instagram Reels are tagged too)
- Top performing content, sampled per channel so no channel gets buried

## How it works

```
fetch_engagement.py  →  engagement-data.js  →  engagement-dashboard.html
                        engagement-data.json
```

`fetch_engagement.py` reads `config.json`, queries each configured API over a
rolling lookback window (default 90 days), and writes `engagement-data.js`
(`window.ENGAGEMENT_DATA = {...}`) plus a plain `engagement-data.json`. The
dashboard page loads the `.js` file with a `<script>` tag, so it works from the
local filesystem with no web server.

## Quick start (local)

1. **Install Python 3.12+** and the dependencies:

   ```bash
   pip install google-analytics-data google-auth google-auth-oauthlib google-api-python-client requests
   ```

2. **Create your config** — copy `config.example.json` to `config.json` and fill in
   the values for whichever platforms you've set up. Follow
   [SETUP_GUIDE.md](SETUP_GUIDE.md) for step-by-step credential instructions for
   each platform.

3. **Fetch and view:**

   ```bash
   python fetch_engagement.py
   ```

   Then open `engagement-dashboard.html` in any browser.

On Windows you can skip steps 1 and 3 and just double-click **`run_dashboard.bat`**,
which installs the libraries, fetches the data, optionally publishes, and opens the
dashboard.

## Configuration

`config.json` (git-ignored — never commit it):

| Key | Meaning |
|---|---|
| `lookback_days` | Size of the rolling window, in days (default 90) |
| `meta_api_version` | Meta Graph API version, e.g. `v21.0` |
| `google_analytics.property_id` | GA4 property ID |
| `google_analytics.service_account_json` | Filename of the GA4 service-account key |
| `facebook.page_id` / `facebook.page_access_token` | Page ID and long-lived Page token |
| `instagram.ig_user_id` | Instagram business account ID (leave `access_token` blank to reuse the Facebook token) |
| `youtube.oauth_client_secret_json` / `youtube.token_json` | OAuth client file and saved token file |
| `search_console.site_url` *(optional)* | Search Console property URL; falls back to `search_console.domain` matching, and reuses the GA4 service account key unless `search_console.service_account_json` is set |

Set `DASHBOARD_HEADLESS=1` to prevent the YouTube OAuth flow from trying to open a
browser (used by the GitHub Actions run).

## Hosted deployment (GitHub Actions + Pages)

The repo ships a workflow at `.github/workflows/refresh.yml` that runs the fetch in
GitHub's cloud every Monday (and on demand via **Actions → Refresh dashboard → Run
workflow**), then publishes to GitHub Pages — so the dashboard stays online and
current even with your computer off. Credentials live in encrypted repository
secrets:

| Secret | Contents |
|---|---|
| `CONFIG_JSON` | Your `config.json` |
| `GCC_SERVICE_ACCOUNT_JSON` | Your Google service-account key file |
| `YOUTUBE_TOKEN_JSON` | Your saved `youtube_token.json` |

Full walkthrough: [GITHUB_SETUP.md](GITHUB_SETUP.md).

### Netlify alternative

`publish.py` deploys the dashboard to a free Netlify site instead. Put a Netlify
personal access token in `netlify_token.txt`; the script creates the site on first
run and uploads **only** `engagement-dashboard.html` (as `index.html`) and
`engagement-data.js` — never credentials.

## Files

| File | Purpose |
|---|---|
| `fetch_engagement.py` | Pulls data from every configured API and writes the data files |
| `engagement-dashboard.html` | The dashboard itself (self-contained, reads `engagement-data.js`) |
| `publish.py` | Optional Netlify deploy |
| `.github/workflows/refresh.yml` | Scheduled cloud refresh + GitHub Pages deploy |
| `run_dashboard.bat` | Windows: install deps, fetch, publish, open the dashboard |
| `publish_now.bat` | Windows: force an immediate refresh and publish |
| `refresh_quiet.bat` | Windows: silent refresh used by the scheduled task, logs to `refresh_log.txt` |
| `setup_schedule.bat` | Windows: register the daily Task Scheduler job (redundant if using GitHub Actions) |
| `config.example.json` | Template for `config.json` |
| `SETUP_GUIDE.md` | Per-platform credential setup |
| `GITHUB_SETUP.md` | GitHub Actions + Pages hosting setup |

## Security

`.gitignore` already excludes every secret this project touches — `config.json`,
`ga4-service-account.json`, `gcc-service-account.json`, `youtube-oauth-client.json`,
`youtube_token.json`, `netlify_token.txt`, and any `*.key` / `*.pem`. Generated data
files (`engagement-data.js` / `.json`) are ignored too, since the hosted workflow
regenerates them at deploy time.

If you host on GitHub Pages the repo must be **public**, which means the generated
engagement numbers are publicly visible — the credentials are not.

## Troubleshooting

- **A channel is missing from the dashboard** — the fetch script prints a line per
  channel; an unconfigured or failing platform is skipped rather than aborting the
  run. Check that run's output for the reason.
- **YouTube token expired in CI** — the cloud can't open a browser. Run
  `run_dashboard.bat` locally once to refresh `youtube_token.json`, then update the
  `YOUTUBE_TOKEN_JSON` secret with its new contents.
- **Facebook token expired** — regenerate the long-lived Page token and update the
  `CONFIG_JSON` secret.
- **Reels show "n/a" plays** — the Page token can list Reels but not read their
  insights. Regenerate it with `read_insights` (and `pages_read_engagement`)
  granted; Reels engagement still counts without it.
- **No Shorts split on YouTube** — the fetch log says "Shorts split unavailable";
  the dashboard then shows channel totals only. The `creatorContentType`
  dimension needs data from 2019 onward and the same read-only scopes.
- **Changing the refresh schedule** — edit the `cron` line in
  `.github/workflows/refresh.yml`.
