# 🎬 BMS Ticket Notifier

A Python tool that monitors [BookMyShow](https://in.bookmyshow.com) for movie showtime and ticket-availability changes, then sends email alerts through [Resend](https://resend.com).

## What it does

- Monitor one or multiple movies.
- Optionally filter each movie by date, theatre, time of day, and format.
- Email a digest when booking dates open, new showtimes appear, or availability changes.
- Send a separate alert after repeated fetch failures.
- Save known results in `bms_state.json` so a failed request is not mistaken for no available shows.

## 1. Set up Resend email

1. Sign in to [Resend](https://resend.com) and create an API key.
2. Use a sender address permitted by your Resend account. For production use, verify your sending domain in Resend.
3. In GitHub, open **Settings → Secrets and variables → Actions → Secrets**, then create these repository secrets:

| Secret | Example / value |
| --- | --- |
| `RESEND_API_KEY` | Paste the API key from Resend. Keep it private. |
| `RESEND_TO_EMAIL` | `you@example.com` — the inbox that should receive alerts. |
| `RESEND_FROM_EMAIL` | `Movie Alerts <alerts@your-verified-domain.com>` — use a sender address accepted by Resend. |

Do not put real API keys in the README, source code, or a GitHub repository variable.

## 2. Configure movies using `BMS_WATCHES`

For movie monitoring, configure the **`BMS_WATCHES` repository variable**. In GitHub, go to **Settings → Secrets and variables → Actions → Variables → New repository variable**.

- **Name:** `BMS_WATCHES`
- **Value:** a JSON array containing the movie or movies to monitor.

Example value (paste as one line or formatted JSON):

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

Replace the example URLs and event codes with the actual BookMyShow movie URLs you want to monitor. Each object must include `url`; the other fields are optional.

| Field | Example | Meaning |
| --- | --- | --- |
| `name` | `Movie A` | Optional friendly name for the movie. |
| `url` | A BookMyShow movie URL | Required. Use the movie's actual BookMyShow page URL. |
| `dates` | `20261103,20261104` | Optional comma-separated dates in `YYYYMMDD` format. |
| `theatre` | `PVR` | Optional theatre-name substring filter. |
| `time` | `evening,night` | Optional time filter: `morning`, `afternoon`, `evening`, or `night`. |
| `format` | `IMAX 2D,Tamil 2D` | Optional comma-separated format/category filter. |

Omit a filter or leave it empty to avoid filtering on that field. Keep the JSON valid: use double quotes around property names and string values, commas between properties/items, and no trailing comma after the final property. A malformed or empty value will cause the script to fall back to its legacy single-movie configuration, so check the workflow logs if the configured watches do not appear to load.

## 3. Run the workflow

1. Open the repository's **Actions** tab.
2. Select **BMS Ticket Checker**.
3. Click **Run workflow**, select the branch, and start the run.
4. Open the run to view logs. The workflow saves state changes to `bms_state.json`.

The workflow can be started manually. **Automatic scheduled polling is not currently enabled.**

## 4. Run locally on Windows (PowerShell)

Install Python 3.14 and [uv](https://docs.astral.sh/uv/), clone the repository, and open PowerShell in the project folder:

```powershell
uv sync --frozen

$env:BMS_WATCHES = '[{"name":"Movie A","url":"https://in.bookmyshow.com/movies/chennai/movie-a/buytickets/ET00123456","theatre":"PVR"}]'
$env:RESEND_API_KEY = "YOUR_RESEND_API_KEY"
$env:RESEND_TO_EMAIL = "you@example.com"
$env:RESEND_FROM_EMAIL = "Movie Alerts <alerts@your-verified-domain.com>"

uv run --with tzdata main.py
```

Replace all sample values with your actual movie URL and email settings. These PowerShell environment variables apply only to the current PowerShell session. Never commit real API keys.

## Troubleshooting

- **No email arrives:** Check the workflow logs and confirm all three `RESEND_*` secrets. Verify that the sender is permitted by Resend.
- **HTTP 403 from BookMyShow:** This means the request was denied, not that tickets are unavailable. The checker logs diagnostic details and stops retrying a 403 response. Use access methods permitted by BookMyShow; a hosted runner may continue to be blocked.
- **No change email:** An unchanged scan may correctly produce no change notification because results are compared with the saved state in `bms_state.json`.
- **Movie list not loading:** Confirm `BMS_WATCHES` is set under **Variables**, contains a valid JSON array, and every movie object has a valid `url`.

## License

See [LICENSE](LICENSE).
