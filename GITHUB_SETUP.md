# Hosting the dashboard with GitHub Actions + GitHub Pages

This runs everything in GitHub's cloud, so the dashboard updates and stays online
**even when your computer is off**. It refreshes every Monday (and on demand), pulling
fresh data from all your accounts and publishing to a public web link. Cost: $0.

## What you need to know first

- The repo must be **public** (free GitHub Pages requires it). Your code and the
  generated `engagement-data.js` will be publicly visible. Your **credentials are NOT** —
  they go into encrypted GitHub *Secrets*, never into the repo.
- Three secrets hold your credentials. The workflow writes them to files at run time,
  runs the fetch, and throws them away.

---

## Step 1 — Create the repository

1. On https://github.com, click **New repository**
2. Name it e.g. `gcc-engagement-dashboard`, set it **Public**, click **Create**
3. Push this whole folder to it. Easiest with **GitHub Desktop**:
   - **File → Add local repository** → choose your *Live Digital Engagement Dashboard* folder
   - It will offer to create the repo / publish — publish it to the repo above
   - The `.gitignore` already excludes your secrets (config.json, the key/token files,
     and engagement-data.js), so those are **not** uploaded. Good.

After pushing, the repo should contain: `fetch_engagement.py`, `engagement-dashboard.html`,
`.github/workflows/refresh.yml`, and the helper files — but **not** config.json,
gcc-service-account.json, or youtube_token.json.

## Step 2 — Add your three secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
Create these three. For each, open the matching local file, copy ALL of its contents,
and paste as the secret value:

| Secret name | Paste the contents of |
|---|---|
| `CONFIG_JSON` | `config.json` |
| `GCC_SERVICE_ACCOUNT_JSON` | `gcc-service-account.json` |
| `YOUTUBE_TOKEN_JSON` | `youtube_token.json` |

(Tip: open each file in Notepad, Ctrl+A, Ctrl+C, paste into the secret box.)

## Step 3 — Turn on GitHub Pages

In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
(You don't pick a branch — the workflow handles publishing.)

## Step 4 — Run it

1. Go to the **Actions** tab → **Refresh dashboard** → **Run workflow** → **Run workflow**
2. Wait ~1–2 minutes for it to finish (green check)
3. Open the run → the **deploy** step shows your **page URL** — that's your live link
   (also under **Settings → Pages**)

Share that URL with leadership. From then on it refreshes itself every Monday. To update
sooner, just hit **Run workflow** again.

---

## Notes

- **YouTube**: the cloud can't open a browser, so it refreshes your saved token silently.
  If the YouTube token ever breaks, run `run_dashboard.bat` locally once to refresh it,
  then update the `YOUTUBE_TOKEN_JSON` secret with the new `youtube_token.json` contents.
- **Facebook token**: long-lived, but if it ever expires, regenerate it and update the
  `CONFIG_JSON` secret.
- The local **Windows scheduled task** is now redundant (GitHub does the refresh). You can
  leave it or remove it from Task Scheduler — your call. `run_dashboard.bat` still works
  any time for a local look.
- Change the schedule by editing the `cron` line in `.github/workflows/refresh.yml`.
