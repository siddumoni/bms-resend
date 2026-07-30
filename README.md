# 🎬 BMS Ticket Notifier

Monitors a [BookMyShow](https://in.bookmyshow.com) movie page for showtime and ticket-availability changes, and sends you a formatted email (via [Resend](https://resend.com)) whenever something changes — a new showtime appears, a date opens for booking, or a sold-out show comes back in stock.

Runs as a **manually-triggered GitHub Actions workflow** (see note in [Automation](#automation--important-correction) below), or locally on your own machine/cron.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Setup (GitHub Actions)](#setup-github-actions)
- [Automation — important correction](#automation--important-correction)
- [Local Usage](#local-usage)
- [Configuration Reference](#configuration-reference)
- [Supported Cities](#supported-cities)
- [State File](#state-file)
- [What Triggers a Notification](#what-triggers-a-notification)
- [Sample Email Template](#sample-email-template)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## How It Works

The whole flow lives in `main.py` and runs once per invocation (it's a script, not a long-running service):

1. **Parse the BMS URL** — extracts the event code (`ET########`) and the region/city slug (e.g. `chennai`) from the `BMS_URL` you provide.
2. **Resolve the region** — maps the city slug to BookMyShow's internal region code, geo-coordinates, and geohash (needed by their API). A small built-in table covers major Indian cities; unknown cities get a best-effort fallback.
3. **Call the BookMyShow API** (`showtimes-by-event/primary-dynamic`) for each date you're tracking, with automatic retry + backoff on `403`/`429` responses (up to 3 attempts).
4. **Parse the response** into structured data: movie name/language, available dates, and every showtime (venue, time, screen format, seat categories with price + availability status).
5. **Apply your filters** — theatre name, date, time-of-day period, and screen/format (see [Configuration Reference](#configuration-reference)).
6. **Compare against the last saved state** (`bms_state.json`) to detect:
   - a date newly opening for booking,
   - a brand-new showtime appearing,
   - a previously sold-out showtime becoming available again.
7. **Save the new state** back to `bms_state.json` (overwriting the old one).
8. **If anything changed**, build an HTML + plain-text email and send it via the Resend API. If nothing changed, no email is sent.

No changes → no email. This keeps your inbox quiet until something is actually worth acting on.

---

## Requirements

- Python **3.14+** (pinned via `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- A free [Resend](https://resend.com) account + API key (for sending email)
- A GitHub account, if you want to run this via Actions instead of locally

---

## Setup (GitHub Actions)

### 1. Fork this repository

### 2. Set GitHub Secrets

Go to **Settings → Secrets and variables → Actions → Secrets** and add:

| Secret | Description |
|---|---|
| `RESEND_API_KEY` | API key from [resend.com](https://resend.com) |
| `RESEND_TO_EMAIL` | Email address that should receive alerts |
| `RESEND_FROM_EMAIL` | Sender address (your verified domain, or `onboarding@resend.dev` / `anything@resend.dev` for testing) |

### 3. Set GitHub Variables

Go to **Settings → Secrets and variables → Actions → Variables** and add:

| Variable | Required | Description | Example |
|---|---|---|---|
| `BMS_URL` | ✅ | Full BookMyShow "buy tickets" page URL for the movie | `https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890` |
| `BMS_DATES` | optional | Comma-separated dates (`YYYYMMDD`) to check. Empty = auto-detect the single date from the URL if present. | `20260318,20260319` |
| `BMS_THEATRE` | optional | Comma-separated substrings to filter venue names. Empty = all theatres. | `PVR,INOX` |
| `BMS_TIME` | optional | Comma-separated time-of-day periods to filter. Empty = all times. | `evening,night` |
| `BMS_FORMAT` | optional | Comma-separated substrings to filter screen/format attributes (e.g. IMAX, language). Empty = all formats. | `IMAX 2D,Tamil 2D` |

**Time periods available:** `morning` (06:00–12:00), `afternoon` (12:00–16:00), `evening` (16:00–19:00), `night` (19:00–24:00)

### 4. Trigger the workflow

Go to **Actions → BMS Ticket Checker → Run workflow** and click **Run workflow**.

---

## Automation — important correction

⚠️ The previous README claimed this runs automatically "every 30 minutes" via GitHub Actions. **That is not what the current workflow file (`.github/workflows/bms-checker.yml`) does.**

The workflow's trigger is currently:

```yaml
on:
  workflow_dispatch:  # Manual trigger button only
```

There is **no `schedule:` cron trigger configured**. As shipped, the checker only runs when you (or something else) manually click **Run workflow** in the Actions tab, or manually invoke it via the GitHub API/CLI.

If you want automatic periodic checks, add a schedule trigger yourself, e.g.:

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: "*/30 * * * *"   # every 30 minutes (UTC)
```

Also note: the workflow has `permissions: contents: write` and, after each run, commits the updated `bms_state.json` back to the repo (`chore: update bms_state.json [skip ci]`) so state persists across runs. Make sure GitHub Actions is allowed to push to your fork (Settings → Actions → General → Workflow permissions → **Read and write permissions**).

---

## Local Usage

```bash
uv sync --frozen

export BMS_URL="https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890"
export BMS_DATES="20260318,20260319"
export BMS_THEATRE="PVR"
export BMS_TIME="evening,night"
export BMS_FORMAT=""
export RESEND_API_KEY="re_..."
export RESEND_FROM_EMAIL="onboarding@resend.dev"
export RESEND_TO_EMAIL="you@example.com"

uv run main.py
```

If `RESEND_API_KEY` or `RESEND_TO_EMAIL` is missing, the script still runs and prints the current showtimes to the console — it just skips sending the email (with a warning).

You can also just edit the defaults directly inside the `CONFIG` dict at the top of `main.py` instead of exporting env vars.

---

## Configuration Reference

All configuration is environment-variable driven (with hardcoded fallbacks in `main.py`):

| Variable | Purpose | Default |
|---|---|---|
| `BMS_URL` | Movie's BookMyShow buy-tickets URL | sample Dhurandhar URL baked into `main.py` |
| `BMS_DATES` | Dates to check, `YYYYMMDD` comma-separated | `""` (auto-detect from URL, or checks with no date filter) |
| `BMS_THEATRE` | Venue-name substring filter | `""` (all theatres) |
| `BMS_TIME` | Time-of-day period filter | `""` (all times) |
| `BMS_FORMAT` | Screen/format substring filter | `""` (all formats) |
| `RESEND_API_KEY` | Resend API key | `""` |
| `RESEND_TO_EMAIL` | Recipient email | `""` |
| `RESEND_FROM_EMAIL` | Sender email | `aviiciii@resend.dev` |

---

## Supported Cities

The region resolver has built-in mappings (region code, geo-coordinates, geohash) for:

`chennai`, `mumbai`, `delhi` / `delhi-ncr`, `bengaluru` / `bangalore`, `hyderabad`, `kolkata`, `pune`, `kochi`, `coimbatore`

For any other city slug, it falls back to a best-effort guess (uppercased slug as region code, coordinates `0,0`, empty geohash) — this may not return accurate results, so if your city isn't listed above, expect to add it to the `REGION_MAP` in `main.py` yourself.

---

## State File

`bms_state.json` stores the last-seen snapshot so the script can diff runs:

```json
{
  "shows": {
    "PVPZ|36072|20260802|ELITE": {
      "venue": "PVR: Palazzo, The Nexus Vijaya Mall",
      "time": "09:00 AM",
      "date": "20260802",
      "time_code": "0900",
      "cat": "ELITE",
      "price": "508.34",
      "status": "1"
    }
  },
  "dates": {
    "20260802": "BOOKABLE"
  }
}
```

- Each show entry is keyed by `venue_code|session_id|date_code|category_name`.
- `status` values: `0` = SOLD OUT, `1` = ALMOST FULL, `2` = FILLING FAST, `3` = AVAILABLE.
- `dates` maps each date code to `BOOKABLE`, `NOT_OPEN`, or `AVAILABLE`.

This file is committed back to the repo by the workflow after every run, so state survives between GitHub Actions runs (not just within a single job).

---

## What Triggers a Notification

An email is sent only when the diff between old and new state finds one of these:

| Change | Condition |
|---|---|
| 📅 **Date opened** | A date's status flips from `NOT_OPEN` → `BOOKABLE`/`AVAILABLE` |
| 🆕 **New showtime** | A show key exists in the new state but not the old one |
| 🟢 **Back in stock** | A show's status was `0` (SOLD OUT) and is now anything else |

Note: general price changes or "available → almost full" type shifts are **not** treated as notification-worthy changes — only sold-out-recovery, new showtimes, and date openings are. This keeps alerts meaningful instead of noisy.

---

## Sample Email Template

Below is what an actual alert looks like (subject line, HTML rendering, and the plain-text fallback that's sent alongside it).

**Subject:**
```
BMS Alert: Dhurandhar - The Revenge - 2 change(s)
```

**HTML body (rendered structure):**

```
┌──────────────────────────────────────────────┐
│   🎬 BMS TICKET ALERT                         │  ← red/orange gradient banner
│   Dhurandhar - The Revenge                    │
├──────────────────────────────────────────────┤
│                        Checked at 30 Jul 2026,│
│                                    07:05 PM   │
├──────────────────────────────────────────────┤
│ 🔔 Changes Detected                           │
│  ─────────────────────────────────────────── │
│  📅 New date opened: Sun, 02 Aug 2026         │
│  🆕 New showtime: PVR: Palazzo — 07:40 PM     │
│                              (Sun, 02 Aug)    │
│  🟢 Back in stock: INOX: Chennai — 09:15 PM   │
│                (Sun, 02 Aug) → AVAILABLE      │
├──────────────────────────────────────────────┤
│ 🎟️ Current Showtimes                          │
│                                                │
│  🗓️ Sun, 02 Aug 2026                          │
│  📍 PVR: Palazzo, The Nexus Vijaya Mall       │
│     [09:00 AM] [12:30 PM] [04:05 PM · IMAX 2D]│
│     [07:40 PM]                                │
│                                                │
│  📍 INOX: Chennai Citi Centre                 │
│     [09:15 PM · Tamil 2D]                     │
├──────────────────────────────────────────────┤
│         Automated alert from BMS Ticket       │
│                    Notifier                   │
└──────────────────────────────────────────────┘
```

The real output is a responsive HTML email (max-width 600px, mobile-friendly via a media query), built with inline styles for email-client compatibility. Showtimes are grouped by date (newest/soonest first), then by venue, with each time rendered as a rounded "chip" and the screen format appended when available (e.g. `07:40 PM · IMAX 2D`).

**Plain-text fallback (sent in the same email as the `text` part):**

```
BMS Alert: Dhurandhar - The Revenge - 2 change(s)

Checked at: 2026-07-30 19:05:00

Changes Detected:
  - New date opened: Sun, 02 Aug 2026
  - New showtime: PVR: Palazzo, The Nexus Vijaya Mall — 07:40 PM (Sun, 02 Aug 2026)
  - Back in stock: INOX: Chennai Citi Centre — 09:15 PM (Sun, 02 Aug 2026) → AVAILABLE

Current Showtimes:

Sun, 02 Aug 2026
  PVR: Palazzo, The Nexus Vijaya Mall
    - 09:00 AM
    - 12:30 PM
    - 04:05 PM [IMAX 2D]
    - 07:40 PM
  INOX: Chennai Citi Centre
    - 09:15 PM [Tamil 2D]

This is an automated alert from BMS Ticket Notifier.
```

> If you want to customize the look, the HTML template lives inside `send_email()` in `main.py` (the `html = f"""..."""` block) — it's plain inline-styled HTML, no external template engine or CSS file involved.

---

## Project Structure

```
bms-resend/
├── .github/
│   └── workflows/
│       └── bms-checker.yml   # Manual-trigger workflow, commits state back
├── main.py                   # All logic: fetch → parse → filter → diff → email
├── bms_state.json            # Persisted last-seen state (auto-updated)
├── pyproject.toml            # requires-python >=3.14, deps: requests
├── uv.lock                   # Locked dependency versions
├── .python-version           # 3.14
├── LICENSE                   # MIT
└── README.md
```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `❌ Invalid BMS_URL. Could not extract event/region.` | URL doesn't contain an `ET########` event code or a `movies/<city>/...` segment — double check you copied the full "buy tickets" URL. |
| `HTTP 403` / `HTTP 429` repeatedly | BookMyShow is rate-limiting/blocking the request. The script retries with backoff (3 attempts), but persistent blocks usually mean the `User-Agent`/headers need refreshing or you're hitting it too frequently. |
| `⚠️ Skipping email — RESEND_API_KEY or RESEND_TO_EMAIL not set.` | One of those two env vars/secrets is empty — the script otherwise runs fine and prints results to the console. |
| No email even though tickets changed | Remember: only *new date/new showtime/sold-out→available* count as changes. Price or minor availability-tier shifts (e.g. `AVAILABLE → ALMOST FULL`) are intentionally not alerted on. |
| Workflow never runs on its own | By design — see [Automation](#automation--important-correction). Add a `schedule:` trigger if you want periodic runs. |
| State keeps "resetting" | Make sure the workflow has **Read and write permissions** under repo Settings → Actions → General, so it can commit `bms_state.json` back after each run. |

---

## License

MIT — see [LICENSE](LICENSE).
