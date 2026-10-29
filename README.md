# 🎬 BMS Ticket Notifier

A Python tool that monitors [BookMyShow](https://in.bookmyshow.com) for movie showtime and ticket-availability changes, then sends email alerts through [Resend](https://resend.com).

## What it does

- Monitor one movie or several movie pages.
- Filter by date, theatre, time of day, and format.
- Email a combined digest when a booking date opens, a new showtime appears, or availability changes.
- Send a separate alert after repeated fetch failures.
- Save the last known results in `bms_state.json`, so a failed request is not mistaken for zero shows.

## 1. Set up email alerts with Resend

1. Create or sign in to your account at [Resend](https://resend.com) and create an API key.
2. Choose a sender address that Resend permits you to use. For production sending, verify your domain in Resend and use a sender on that domain.
3. Keep the API key private. Add it to GitHub as a **secret**, not a variable.

You will need:
- `RESEND_API_KEY` — your Resend API key.
- `RESEND_TO_EMAIL` — the email address that should receive alerts.
- `RESEND_FROM_EMAIL` — the sender address accepted by Resend. The code has a fallback of `aviiciii@resend.dev`, but set this explicitly for your setup.

## 2. Configure GitHub Actions

Open your repository on GitHub, then go to **Settings → Secrets and variables → Actions**.

### Add repository variables

Open the **Variables** tab and select **New repository variable**. Add the variables you need from the table below. Variable names must match exactly.

| Variable | Example value | Purpose |
| --- | --- | --- |
| `BMS_URL` | `https://in.bookmyshow.com/movies/chennai/movie-name/buytickets/ET00123456` | BookMyShow movie page for a single-movie watch; replace this example with the actual URL. |
| `BMS_DATES` | `20261103,20261104` | Optional dates to check, comma-separated in `YYYYMMDD` format. Leave blank to use the date in the URL/default results. |
| `BMS_THEATRE` | `PVR` | Optional theatre-name substring filter, e.g. `PVR` or `INOX`. Leave blank to include all theatres. |
| `BMS_TIME` | `evening,night` | Optional time filter. Supported values: `morning`, `afternoon`, `evening`, `night`. |
| `BMS_FORMAT` | `IMAX 2D,Tamil 2D` | Optional format/category substring filter, comma-separated. Leave blank to include all formats. |
| `BMS_FAIL_THRESHOLD` | `3` | Number of consecutive fetch failures for a movie/date before a separate failure alert is sent. Defaults to `3`. |

### Add repository secrets

Open the **Secrets** tab and select **New repository secret** for each item:

| Secret name | Example / what to enter |
| --- | --- |
| `RESEND_API_KEY` | Paste the API key generated in your Resend dashboard. Do not use a real key in documentation, code, or chat. |
| `RESEND_TO_EMAIL` | `you@example.com` — the inbox where you want alerts. |
| `RESEND_FROM_EMAIL` | `Movie Alerts <alerts@your-verified-domain.com>` — use a sender address permitted by your Resend setup. |

GitHub Actions passes these values to the checker when the workflow runs. Do not commit API keys or other credentials to the repository.

## 3. Monitor more than one movie (optional)

To monitor multiple movies in one run, set the `BMS_WATCHES` **repository variable** to a valid JSON array. Each watch needs a `url`; `name`, `dates`, `theatre`, `time`, and `format` are optional.

Example value for `BMS_WATCHES` (paste as one line in GitHub Variables):

```json
[
  {
    "name": "Movie A",
    "url": "https://in.bookmyshow.com/movies/chennai/movie-a/buytickets/ET00123456",
    "dates": "20261103,20261104",
    "theatre": "PVR",
    "time": "evening,night",
    "format": "Tamil 2D"
  },
  {
    "name": "Movie B",
    "url": "https://in.bookmyshow.com/movies/chennai/movie-b/buytickets/ET00654321",
    "theatre": "INOX"
  }
]
```

Replace both sample URLs and event codes with the real BookMyShow movie URLs you want to monitor. If a watch omits a filter, it inherits the matching single-movie setting (such as `BMS_THEATRE`). When `BMS_WATCHES` is valid, it is used instead of the single `BMS_URL` watch. If it is invalid, the checker logs a warning and falls back to the single-movie configuration.

**Tip:** Start with just `BMS_URL` and add `BMS_WATCHES` only when you want multiple movies.

## 4. Run the checker in GitHub

1. Open the repository's **Actions** tab.
2. Select **BMS Ticket Checker**.
3. Click **Run workflow**, choose the branch, and start it.
4. Open the run and inspect the logs if it fails. The checker commits changes to `bms_state.json` when there are updates to save.

The workflow is manually triggerable. **Automatic scheduled polling is not currently enabled**, so it will not run repeatedly on a timer unless a schedule is added to the workflow.

## 5. Run locally on Windows (PowerShell)

Install Python 3.14 and [uv](https://docs.astral.sh/uv/), clone the repository, and open PowerShell in the project folder. Then run:

```powershell
uv sync --frozen

$env:BMS_URL = "https://in.bookmyshow.com/movies/chennai/movie-name/buytickets/ET00123456"
$env:BMS_DATES = "20261103,20261104"
$env:BMS_THEATRE = "PVR"
$env:BMS_TIME = "evening,night"
$env:BMS_FORMAT = "Tamil 2D"
$env:RESEND_API_KEY = "YOUR_RESEND_API_KEY"
$env:RESEND_TO_EMAIL = "you@example.com"
$env:RESEND_FROM_EMAIL = "Movie Alerts <alerts@your-verified-domain.com>"

uv run --with tzdata main.py
```

Replace the sample values before running. These PowerShell environment variables apply only to the current PowerShell session. Avoid pasting real API keys into shared terminals or screenshots. For multiple movies, set `$env:BMS_WATCHES` to the JSON array shown above; do not set it unless you want multi-movie mode.

## Troubleshooting

- **No email arrives:** Check the workflow logs and confirm the three `RESEND_*` secrets are set correctly. Make sure the sender is permitted by Resend.
- **HTTP 403 from BookMyShow:** This means the request was denied, not that tickets are unavailable. The checker records diagnostic details and stops retrying a 403 response. Use access methods permitted by BookMyShow; changing the runner does not guarantee access.
- **No changes reported:** The checker compares results with the saved state in `bms_state.json`; an unchanged scan may correctly produce no change email.
- **Invalid `BMS_WATCHES`:** Check that it is valid JSON, is an array, and every item has a `url`.

## License

See [LICENSE](LICENSE).
