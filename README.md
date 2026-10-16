# 🎬 BMS Ticket Notifier

A Python watcher for [BookMyShow](https://in.bookmyshow.com) that monitors movie booking pages for showtime and ticket-availability changes. It sends an HTML and plain-text email through [Resend](https://resend.com) when a booking date opens, a new showtime appears, or a previously sold-out show becomes bookable again.

The project runs once per invocation as a **manually triggered GitHub Actions workflow** or locally. The current workflow does not have a scheduled cron trigger.

## Features

- Watch one movie with `BMS_URL` or multiple movies with `BMS_WATCHES`.
- Filter results by travel/show date, theatre, time of day, and screen format.
- Fetch showtimes and category-level availability/price details from BookMyShow's showtime API.
- Detect meaningful changes by comparing the current response against the persistent `bms_state.json` snapshot.
- Send a combined digest for multi-movie runs, so multiple watches are summarized in one message.
- Send a separate fetch-failure alert when a movie/date fails repeatedly, while retaining its last successful state.
- Persist state across GitHub Actions runs by committing `bms_state.json` back to the repository.

## How it works

1. Read either the legacy single-movie configuration or the JSON `BMS_WATCHES` list.
2. Extract the BookMyShow event code and region slug from each buy-tickets URL.
3. Resolve the region using the built-in city map.
4. Request showtime data, retrying transient HTTP failures such as `403` and `429` where applicable.
5. Parse movie details, available dates, venues, showtimes, formats and category/status data.
6. Apply the configured date, theatre, time and format filters.
7. Compare results with the previous state and identify:
   - a date newly opening for booking;
   - a new showtime appearing;
   - a previously sold-out showtime becoming available again.
8. Save successful date snapshots without wiping the prior snapshot for a date whose fetch failed.
9. Send the ticket-alert email when a meaningful change is found. A separate system-health email is sent when repeated fetch failures reach the configured threshold.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       └── bms-checker.yml   # Manual GitHub Actions workflow
├── main.py                   # Fetching, parsing, filtering, diffing and emails
├── pyproject.toml             # Project/dependency metadata
├── uv.lock                    # Locked dependency set
├── .python-version            # Python version for uv
├── bms_state.json             # Persistent last-known state
└── LICENSE
```

## Requirements

- Python version compatible with `.python-version` and `pyproject.toml` (currently Python 3.14+).
- [uv](https://docs.astral.sh/uv/) for environment and dependency management.
- A BookMyShow buy-tickets URL for each movie being watched.
- A Resend account, API key, and sender address permitted by your Resend account.

Install and sync dependencies:

```bash
uv sync --frozen
```

## GitHub Actions setup

The workflow is `.github/workflows/bms-checker.yml`.

### 1. Add repository variables

Open **Settings → Secrets and variables → Actions → Variables** and add the relevant values:

| Variable | Purpose |
|---|---|
| `BMS_URL` | BookMyShow buy-tickets URL for the single-watch mode |
| `BMS_DATES` | Optional comma-separated dates in `YYYYMMDD` format |
| `BMS_THEATRE` | Optional theatre-name substring filter |
| `BMS_TIME` | Optional time-period filter, such as `evening,night` |
| `BMS_FORMAT` | Optional screen or language/format substring filter |
| `BMS_WATCHES` | Optional JSON array for multiple movie watches |
| `BMS_FAIL_THRESHOLD` | Consecutive failed runs before a fetch-failure email (default: `3`) |

If `BMS_WATCHES` is not set or cannot be parsed, the script falls back to the single-watch values.

### 2. Add Resend secrets

Open **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Purpose |
|---|---|
| `RESEND_API_KEY` | Resend API key |
| `RESEND_TO_EMAIL` | Alert recipient |
| `RESEND_FROM_EMAIL` | Sender address; use a sender/domain allowed by Resend |

Do not place API keys in `main.py`, the README, or other tracked files.

### 3. Trigger a run

Go to **Actions → BMS Ticket Checker → Run workflow**. The workflow currently supports manual dispatch only and commits the updated `bms_state.json` after the run.

## Automation status

**There is no `schedule:` trigger in the current workflow.** Checks happen only when the workflow is manually triggered (or when invoked separately through the GitHub API/CLI). The code can be run locally or from an external scheduler, but automatic GitHub Actions polling is not enabled in the repository as currently configured.

If you choose to add a schedule later, set a conservative interval and confirm that BookMyShow requests work reliably from the runner first. Do not assume that the examples below are already active.

## Local usage

### Single-movie watch

PowerShell:

```powershell
uv sync --frozen

$env:BMS_URL = "https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890"
$env:BMS_DATES = "20261213,20261214"
$env:BMS_THEATRE = "PVR"
$env:BMS_TIME = "evening,night"
$env:BMS_FORMAT = ""
$env:RESEND_API_KEY = "re_..."
$env:RESEND_TO_EMAIL = "you@example.com"
$env:RESEND_FROM_EMAIL = "alerts@your-verified-domain.example"

uv run main.py
```

On macOS/Linux, use `export NAME="value"` instead of PowerShell's `$env:NAME = "value"`.

If the Resend key or recipient is missing, the script can still print the checked showtimes and skip the email with a warning.

## Multi-movie watches (`BMS_WATCHES`)

To monitor multiple movies or the same movie with different filters, set `BMS_WATCHES` to a JSON array:

```json
[
  {
    "name": "Dhurandhar",
    "url": "https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890",
    "dates": "20261213,20261214",
    "theatre": "PVR"
  },
  {
    "name": "Another movie",
    "url": "https://in.bookmyshow.com/movies/mumbai/example-movie/buytickets/ET00500000",
    "time": "evening,night",
    "format": "IMAX"
  }
]
```

Each entry must have a `url`. Optional fields:

| Field | Purpose |
|---|---|
| `name` | Friendly label for the movie in logs/emails |
| `dates` | Comma-separated `YYYYMMDD` dates; falls back to `BMS_DATES` |
| `theatre` | Theatre-name substring; falls back to `BMS_THEATRE` |
| `time` | Time-period filters; falls back to `BMS_TIME` |
| `format` | Format/screen filters; falls back to `BMS_FORMAT` |

Fields omitted from an individual watch inherit the corresponding single-watch environment setting. An invalid or empty multi-watch configuration prints a warning and falls back to legacy single-watch mode.

A multi-watch invocation sends a single combined digest covering all watched movies, including a note for a watch that had no change or could not be checked.

## Filters

- **Date:** Comma-separated `YYYYMMDD` dates. If omitted, the checker can use the date from the URL or the website's default response behavior.
- **Theatre:** Case-insensitive substring match against venue names.
- **Time:** Comma-separated periods: `morning`, `afternoon`, `evening`, `night`.
- **Format:** Substring filter for screen or format attributes, for example `IMAX 2D` or `Tamil 2D`.

The region resolver contains built-in entries for Chennai, Mumbai, Delhi/NCR, Bengaluru/Bangalore, Hyderabad, Kolkata, Pune, Kochi and Coimbatore. Other region slugs use a best-effort fallback and may need a mapping added to `REGION_MAP` in `main.py`.

## What triggers an email?

| Change | Email behavior |
|---|---|
| A date changes from not open to bookable/available | Notify |
| A new showtime appears | Notify |
| A previously sold-out showtime becomes available again | Notify |
| A price changes only | No alert by itself |
| A show changes from available to almost full/filling fast | No alert by itself |

When an alert is sent, the email summarizes the detected changes and shows the current filtered showtimes. The HTML email includes a plain-text alternative.

## Fetch-failure alerts and state protection

If all retries for a particular movie/date fail, that fetch is treated as **unknown**, not as an empty showtime list. Its last known successful state is retained so a temporary block does not make every show look newly available on the next successful fetch.

The consecutive failure counter is tracked per movie/date. When it reaches `BMS_FAIL_THRESHOLD` (default `3`), a separate failure email is sent once for that outage. The counter resets after a successful fetch.

## State file

`bms_state.json` tracks the latest known booking dates and showtimes, allowing the checker to compare runs.

- Single-watch mode preserves the legacy single-movie state structure.
- Multi-watch mode stores a state block for each movie/event.
- Only successfully fetched dates have their snapshots replaced; failed dates retain their last good data.
- The workflow commits the file after each run so the next run can compare against it.

## Testing and maintenance

The repository currently relies on the main script and its embedded logic; check the current repository tree for any added tests before relying on a test-suite command. A safe smoke test is to run `uv run main.py` with a known BookMyShow URL and verify logs, state changes, and email behavior.

BookMyShow's API behavior, response structure, and rate limiting can change. A successful HTTP request alone does not guarantee that all showtime data was returned. Review the workflow logs after an unexpected empty result, and avoid overly frequent polling.

## License

See [LICENSE](LICENSE).
