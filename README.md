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
- [Multi-Movie Watches (`BMS_WATCHES`)](#multi-movie-watches-bms_watches)
- [Supported Cities](#supported-cities)
- [State File](#state-file)
- [What Triggers a Notification](#what-triggers-a-notification)
- [Sample Email Template](#sample-email-template)
- [License](#license)
---

## How It Works

The whole flow lives in `main.py` and runs once per invocation (it's a script, not a long-running service):

1. **Determine what to watch** — either a single movie (`BMS_URL` + friends), or multiple movies at once via `BMS_WATCHES` (see [Multi-Movie Watches](#multi-movie-watches-bms_watches)).
2. **Parse each BMS URL** — extracts the event code (`ET########`) and the region/city slug (e.g. `chennai`) from the watch's URL.
3. **Resolve the region** — maps the city slug to BookMyShow's internal region code, geo-coordinates, and geohash (needed by their API). A small built-in table covers major Indian cities; unknown cities get a best-effort fallback.
4. **Call the BookMyShow API** (`showtimes-by-event/primary-dynamic`) for each date you're tracking, with automatic retry + backoff on `403`/`429` responses (up to 3 attempts).
5. **Parse the response** into structured data: movie name/language, available dates, and every showtime (venue, time, screen format, seat categories with price + availability status).
6. **Apply your filters** — theatre name, date, time-of-day period, and screen/format (see [Configuration Reference](#configuration-reference)).
7. **Compare against the last saved state** (`bms_state.json`) to detect:
   - a date newly opening for booking,
   - a brand-new showtime appearing,
   - a previously sold-out showtime becoming available again.
8. **Save the new state** back to `bms_state.json` (overwriting the old one).
9. **If anything changed**, build an HTML + plain-text email and send it via the Resend API. If nothing changed, no email is sent.
   - The email's "Checked at" timestamp is always rendered in **IST** (`Asia/Kolkata`), regardless of the timezone the script actually runs in — this matters because GitHub Actions runners default to UTC.
   - Each 🗓️ date header in the email is a clickable link straight to that date's BookMyShow "buy tickets" page (built from the event code, region slug, and date), so you can jump directly to booking instead of just seeing the date as plain text.
   - In single-movie mode, one email is sent per run (if there are changes). In multi-movie (`BMS_WATCHES`) mode, one **combined digest email** is sent per run covering every watched movie (see [Multi-Movie Watches](#multi-movie-watches-bms_watches)).

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
| `BMS_URL` | ✅ (unless using `BMS_WATCHES`) | Full BookMyShow "buy tickets" page URL for the movie | `https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890` |
| `BMS_DATES` | optional | Comma-separated dates (`YYYYMMDD`) to check. Empty = auto-detect the single date from the URL if present. | `20260318,20260319` |
| `BMS_THEATRE` | optional | Comma-separated substrings to filter venue names. Empty = all theatres. | `PVR,INOX` |
| `BMS_TIME` | optional | Comma-separated time-of-day periods to filter. Empty = all times. | `evening,night` |
| `BMS_FORMAT` | optional | Comma-separated substrings to filter screen/format attributes (e.g. IMAX, language). Empty = all formats. | `IMAX 2D,Tamil 2D` |
| `BMS_WATCHES` | optional | JSON array to track **multiple movies** in one run — overrides `BMS_URL` and friends when set. See [Multi-Movie Watches](#multi-movie-watches-bms_watches). | see below |

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
| `BMS_WATCHES` | JSON array of multiple movie watches (see below) | `""` (unset → single-movie/legacy mode) |
| `RESEND_API_KEY` | Resend API key | `""` |
| `RESEND_TO_EMAIL` | Recipient email | `""` |
| `RESEND_FROM_EMAIL` | Sender email | `aviiciii@resend.dev` |

---

## Multi-Movie Watches (`BMS_WATCHES`)

By default (no `BMS_WATCHES` set), the script tracks a single movie built from `BMS_URL` / `BMS_DATES` / `BMS_THEATRE` / `BMS_TIME` / `BMS_FORMAT` — this is called **legacy mode**, and behaves exactly like the original single-movie script.

To track **several movies (or the same movie across multiple venues/showtimes) in one run**, set `BMS_WATCHES` to a JSON array instead:

```bash
export BMS_WATCHES='[
  {"name": "Dhurandhar", "url": "https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890", "theatre": "PVR"},
  {"name": "Avatar 3", "url": "https://in.bookmyshow.com/movies/mumbai/avatar-3/buytickets/ET00500000", "time": "evening,night"}
]'
```

**Per-watch fields:**

| Field | Required | Falls back to | Notes |
|---|---|---|---|
| `url` | ✅ | — | Watch is skipped (with a warning) if missing |
| `name` | optional | `""` | Used as a friendly label in the email/logs; `url` is used if empty |
| `dates` | optional | `BMS_DATES` | `YYYYMMDD` comma-separated |
| `theatre` | optional | `BMS_THEATRE` | Substring filter |
| `time` | optional | `BMS_TIME` | Time-of-day period filter |
| `format` | optional | `BMS_FORMAT` | Screen/format substring filter |

Any field you leave off a watch quietly inherits the corresponding single-movie `BMS_*` env var, so a partially-specified watch behaves like the original single-movie config for whatever it doesn't override.

**Fallback behavior:** if `BMS_WATCHES` is unset, empty, not valid JSON, or parses to something that isn't a non-empty array, the script prints a warning and falls back to legacy single-movie mode using `BMS_URL` — nothing breaks.

**How it changes the rest of the run:**
- **State file layout** — in multi-watch mode, `bms_state.json` becomes a dict keyed by each movie's event code (`{"ET00478890": {...}, "ET00500000": {...}}`) instead of the flat single-movie layout. An existing legacy-format state file is transparently migrated in-memory (under an internal `_default` key) the first time you switch to `BMS_WATCHES`, so you won't get a false "everything is new" alert.
- **Email behavior** — instead of one email per movie, the script sends **one combined digest email** per run (via `send_combined_email`) listing changes across all watched movies together, plus the full current showtimes for each. If a particular watch's URL fails to fetch, that failure is reported inline for that movie without blocking the others.

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

This is the **legacy single-movie layout** (used when `BMS_WATCHES` is not set). When `BMS_WATCHES` **is** set, the file instead nests one such block per movie, keyed by event code — see [Multi-Movie Watches](#multi-movie-watches-bms_watches).

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
│                  Checked at 30 Jul 2026,      │
│                          07:05 PM IST         │
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
│  🗓️ Sun, 02 Aug 2026  ← clickable, links to   │
│                          the buytickets page   │
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

Note: in **multi-movie (`BMS_WATCHES`) mode**, this same structure repeats per movie inside a single combined digest email, with one subject line summarizing the total change count across all watched movies (e.g. `BMS Alert: 2 movie(s) — 3 change(s) total`).

---

## License

MIT — see [LICENSE](LICENSE).
