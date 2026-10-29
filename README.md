# 🎬 BMS Ticket Notifier

A Python tool that monitors [BookMyShow](https://in.bookmyshow.com) for movie showtime and ticket-availability changes, then sends email alerts through [Resend](https://resend.com).

## Overview

The checker can monitor one or multiple movies, apply optional date/theatre/time/format filters, and compare each scan with the last saved state. It alerts when a booking date opens, a new showtime appears, or a previously sold-out show becomes available again.

## Key features

- Monitor one movie or multiple movie pages.
- Filter results by date, theatre, time of day, and format.
- Send a combined email digest when relevant changes are detected.
- Send a separate notification after repeated fetch failures.
- Preserve the last successful data when a scan fails, so a failed request is not mistaken for no available shows.
- Save scan state in `bms_state.json` between runs.
- Log request diagnostics to help investigate BookMyShow access errors.

## GitHub Actions

The workflow can be started manually from **Actions → BMS Ticket Checker → Run workflow**. It runs on a Windows-hosted GitHub Actions runner and commits updated state back to the repository. **Automatic scheduled polling is not currently enabled.**

## Configuration

Set these GitHub Actions variables for the movie(s) you want to monitor:

- `BMS_URL` or `BMS_WATCHES` — one BookMyShow URL or a JSON list of movie watches.
- `BMS_DATES`, `BMS_THEATRE`, `BMS_TIME`, `BMS_FORMAT` — optional filters.
- `BMS_FAIL_THRESHOLD` — repeated fetch failures before a failure notification.

Add these GitHub Actions secrets for email alerts:

- `RESEND_API_KEY`
- `RESEND_TO_EMAIL`
- `RESEND_FROM_EMAIL`

Keep API keys in GitHub Secrets or local environment variables, never in tracked source files.

## Run locally

Install dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --frozen
uv run main.py
```

Set the required movie configuration and Resend environment variables before running.

## Note on BookMyShow access

BookMyShow may intermittently return HTTP `403` from hosted runners. A 403 is treated as an access failure, not proof that no shows are available, and the checker records diagnostic details to help investigate. Repeated failures may require checking the provider's permitted access options.

## License

See [LICENSE](LICENSE).
