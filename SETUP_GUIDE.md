# Engagement Dashboard — Credential Setup Guide

This dashboard pulls data straight from each platform's free official API. No
subscription, no middleman. The one-time cost is creating the credentials below.
You only do this once per platform; after that, refreshes are automatic.

Work through the platforms in any order. You can wire them in one at a time — the
fetch script simply skips any platform that isn't configured yet, so the dashboard
lights up channel by channel.

When you finish a platform, copy `config.example.json` to `config.json` and paste
your values into the matching section. Keep `config.json` and any downloaded key
files private — they're like passwords. (They're already covered by `.gitignore`.)

---

## 1. Google Analytics 4 (website)

**Prerequisite:** your SnapPages site must have a GA4 tag installed and collecting
data. If it doesn't yet, that's a separate step — tell me and I'll help. Without it
there's simply no website data to read.

You'll create a *service account* — a robot Google login the script uses to read
(only read) your analytics.

1. Go to https://console.cloud.google.com and create a new project (name it e.g.
   "GCC Dashboard").
2. In the search bar, find **Google Analytics Data API** and click **Enable**.
3. Left menu → **APIs & Services → Credentials → Create credentials → Service account.**
   Give it a name, click through, **Done**.
4. Click the new service account → **Keys → Add key → Create new key → JSON.**
   A `.json` file downloads. Rename it `ga4-service-account.json` and put it in this
   folder.
5. Copy the service account's **email** (looks like
   `something@yourproject.iam.gserviceaccount.com`).
6. In **Google Analytics** (analytics.google.com) → **Admin → Property Access
   Management → +** → paste that email → role **Viewer** → save.
7. Still in Admin → **Property Settings**, copy the **Property ID** (a number like
   `123456789`).

Put the Property ID and the JSON filename into `config.json` under
`google_analytics`.

---

## 2. Facebook Page (GastonCommunityChurch)

You'll create a Meta developer app and get a long-lived **Page access token**.

1. Go to https://developers.facebook.com → **My Apps → Create App** → choose
   **Business** type. Name it "GCC Dashboard".
2. Open **Graph API Explorer** (developers.facebook.com/tools/explorer).
3. Top right: select your app. Click **Generate Access Token** and grant these
   permissions: `pages_read_engagement`, `pages_show_list`, `read_insights`,
   `instagram_basic`, `instagram_manage_insights` (the last two also cover step 3).
4. In the Explorer, run `me/accounts` — this lists your Pages and shows each Page's
   **id**. Copy the **id** for Gaston Community Church.
5. The token from step 3 is short-lived (~1 hour). To get a long-lived one, I can
   run a one-line exchange for you once you paste the short token, your **App ID**,
   and **App Secret** (Settings → Basic in the app dashboard). Long-lived Page
   tokens generally don't expire.

Put the Page **id** and long-lived token into `config.json` under `facebook`.

---

## 3. Instagram (@gaston_community_church)

**Prerequisite:** the Instagram account must be a **Professional** (Business or
Creator) account and **linked to the Facebook Page** above. Check in the Instagram
app: Settings → Account type. If it's already linked, the same token from step 2
works.

1. In the Graph API Explorer, run:
   `{page-id}?fields=instagram_business_account`
   (use the Page id from step 2). It returns an **id** — that's your Instagram
   business account ID.

Put that id into `config.json` under `instagram.ig_user_id`. Leave `access_token`
blank to reuse the Facebook Page token.

---

## 4. YouTube (@gastoncommunitychurch6944)

YouTube Analytics needs you to sign in as the channel owner (a one-time browser
approval), so this one uses OAuth rather than a robot account.

1. In the same Google Cloud project from step 1, enable the **YouTube Analytics
   API**.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID.** If
   prompted, configure the consent screen (External, add your email as a test
   user). Application type: **Desktop app.**
3. Download the client JSON, rename it `youtube-oauth-client.json`, put it in this
   folder.
4. The first time the script runs, it opens a browser asking you to sign in with
   the Google account that manages the YouTube channel and approve read-only
   access. It saves a `youtube_token.json` so you won't be asked again.

Put the client filename into `config.json` under `youtube`.

---

## 5. Google Search Console (how people find you in Google)

This is what fills the **Google Search visibility** panel — how often the church
shows up in Google Search, how often people click through, and which searches
brought them. It reuses the **same service account you made in step 1**, so there's
no new key file to download.

1. In the same Google Cloud project from step 1, search for **Google Search Console
   API** and click **Enable**.
2. Make sure the site is verified in Search Console. Go to
   https://search.google.com/search-console — if you already see the church's site
   listed, you're set. If not, add it there first (that's a separate step; tell me
   and I'll help).
3. Give the robot account read access: in Search Console, pick the property, then
   **Settings → Users and permissions → Add user.** Paste the same service account
   email from step 1.5 (`something@yourproject.iam.gserviceaccount.com`) and choose
   permission **Restricted** — that's enough to read the performance reports.
4. Copy the property's identifier exactly as Search Console shows it in the property
   dropdown:
   - a **Domain** property looks like `gastoncommunitychurch.org` — write it in
     `config.json` as `sc-domain:gastoncommunitychurch.org`
   - a **URL prefix** property looks like `https://www.gastoncommunitychurch.org/` —
     write it exactly that way, trailing slash included

Put that value into `config.json` under `search_console.site_url`:

```json
"search_console": {
  "site_url": "sc-domain:gastoncommunitychurch.org",
  "domain": "",
  "service_account_json": ""
}
```

Leave `service_account_json` blank to reuse the GA4 key from step 1. If you'd rather
not look up the exact property name, you can instead leave `site_url` blank and put
just your domain (e.g. `gastoncommunitychurch.org`) in `domain` — the script will
list the properties the service account can see and pick the matching one,
preferring the domain-wide property.

**If it says "no matching property found"** or "could not list properties", it's
almost always step 3 — the service account hasn't been added as a user on that
property yet.

---

## Running it

Once at least one platform is configured:

```
pip install google-analytics-data google-auth google-auth-oauthlib google-api-python-client requests
python fetch_engagement.py
```

It writes `engagement-data.js`, which `engagement-dashboard.html` reads. Open
`engagement-dashboard.html` in any browser to see your numbers. I'll also set up a
scheduled task so this refreshes on its own.

**Stuck on any step?** Tell me which platform and where, and I can walk you through
it on screen.
