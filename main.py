"""
BMS Ticket Checker — CI/Headless mode for GitHub Actions.
Runs once, checks all configured watches, emails on changes.
State is persisted via a JSON artifact.

Configure via environment variables or edit the CONFIG below.
"""

import os
import re
import sys
import json
from html import escape
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import urlparse
import requests

# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION — edit these or set via env vars
# ──────────────────────────────────────────────────────────────────────
CONFIG = {
    "url": os.getenv(
        "BMS_URL",
        "https://in.bookmyshow.com/movies/chennai/dhurandhar-the-revenge/buytickets/ET00478890"
    ),
    "dates": os.getenv("BMS_DATES", ""),          # comma-separated YYYYMMDD, empty = from URL
    "theatre": os.getenv("BMS_THEATRE", ""),       # substring filter, empty = all
    "time_period": os.getenv("BMS_TIME", ""),      # e.g. "evening,night", empty = all
    "format": os.getenv("BMS_FORMAT", ""),         # e.g. "IMAX 2D,Tamil 2D", empty = all
}

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_TO_EMAIL = os.getenv("RESEND_TO_EMAIL", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "aviiciii@resend.dev")

STATE_FILE = "bms_state.json"

# ──────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────
AVAIL_STATUS_MAP = {
    "0": ("SOLD OUT",    "🔴"),
    "1": ("ALMOST FULL", "🟡"),
    "2": ("FILLING FAST","🟠"),
    "3": ("AVAILABLE",   "🟢"),
}

DATE_STYLE_MAP = {
    "date-selected": "BOOKABLE",
    "date-disabled": "NOT_OPEN",
    "date-default":  "AVAILABLE",
}

TIME_PERIODS = {
    "morning":   (600, 1200),
    "afternoon": (1200, 1600),
    "evening":   (1600, 1900),
    "night":     (1900, 2400),
}

REGION_MAP = {
    "chennai":    ("CHEN",   "chennai",    "13.056", "80.206", "tf3"),
    "mumbai":     ("MUMBAI", "mumbai",     "19.076", "72.878", "te7"),
    "delhi-ncr":  ("NCR",    "delhi-ncr",  "28.613", "77.209", "ttn"),
    "delhi":      ("NCR",    "delhi-ncr",  "28.613", "77.209", "ttn"),
    "bengaluru":  ("BANG",   "bengaluru",  "12.972", "77.594", "tdr"),
    "bangalore":  ("BANG",   "bengaluru",  "12.972", "77.594", "tdr"),
    "hyderabad":  ("HYD",    "hyderabad",  "17.385", "78.487", "tep"),
    "kolkata":    ("KOLK",   "kolkata",    "22.573", "88.364", "tun"),
    "pune":       ("PUNE",   "pune",       "18.520", "73.856", "te2"),
    "kochi":      ("KOCH",   "kochi",      "9.932",  "76.267", "t9z"),
    "coimbatore": ("COIM",   "coimbatore", "11.016845", "76.955832", "t9y"),
}


# ──────────────────────────────────────────────────────────────────────
# DATA
# ──────────────────────────────────────────────────────────────────────
@dataclass
class CatInfo:
    name: str
    price: str
    status: str

@dataclass
class ShowInfo:
    venue_code: str
    venue_name: str
    session_id: str
    date_code: str
    time: str
    time_code: str
    screen_attr: str
    categories: list[CatInfo] = field(default_factory=list)

@dataclass
class DateInfo:
    date_code: str
    status: str


# ──────────────────────────────────────────────────────────────────────
# URL PARSER + REGION RESOLVER
# ──────────────────────────────────────────────────────────────────────
def parse_bms_url(url):
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    result = {"event_code": None, "date_code": None, "region_slug": None}
    for p in parts:
        if re.match(r"^ET\d{8,}$", p):
            result["event_code"] = p
        elif re.match(r"^\d{8}$", p):
            result["date_code"] = p
    if "movies" in parts:
        idx = parts.index("movies")
        if idx + 1 < len(parts):
            result["region_slug"] = parts[idx + 1]
    return result


def resolve_region(slug):
    key = (slug or "").lower().strip()
    if key in REGION_MAP:
        return REGION_MAP[key]
    return (key.upper()[:6], key, "0", "0", "")


# ──────────────────────────────────────────────────────────────────────
# BMS API
# ──────────────────────────────────────────────────────────────────────
API_URL = (
    "https://in.bookmyshow.com/api/movies-data/v4/"
    "showtimes-by-event/primary-dynamic"
)


def fetch_bms(event_code, date_code, region_code, region_slug,
              lat, lon, geohash):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": (
            f"https://in.bookmyshow.com/movies/"
            f"{region_slug}/buytickets/{event_code}/"
        ),
        "sec-ch-ua": '"Chromium";v="145", "Not:A-Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "x-app-code": "WEB",
        "x-region-code": region_code,
        "x-region-slug": region_slug,
        "x-geohash": geohash,
        "x-latitude": lat,
        "x-longitude": lon,
        "x-location-selection": "manual",
        "x-lsid": "",
    }
    params = {
        "eventCode": event_code,
        "dateCode": date_code or "",
        "isDesktop": "true",
        "regionCode": region_code,
        "xLocationShared": "false",
        "memberId": "", "lsId": "", "subCode": "",
        "lat": lat, "lon": lon,
    }
    try:
        resp = requests.get(API_URL, headers=headers,
                            params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"  HTTP {resp.status_code}")
        print(f"  Response snippet: {resp.text[:300]!r}")
    except requests.RequestException as e:
        print(f"  Request failed: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────
# PARSERS
# ──────────────────────────────────────────────────────────────────────
def parse_movie_info(data):
    info = {"name": "Unknown Movie", "language": ""}
    for w in data.get("data", {}).get("topStickyWidgets", []):
        if w.get("type") == "horizontal-text-list":
            for item in w.get("data", []):
                for row in item.get("leftText", {}).get("data", []):
                    for c in row.get("components", []):
                        if "•" in c.get("text", ""):
                            info["language"] = c["text"].strip()
    bs = data.get("data", {}).get("bottomSheetData", {})
    for w in bs.get("format-selector", {}).get("widgets", []):
        if w.get("type") == "vertical-text-list":
            for d in w.get("data", []):
                if d.get("styleId") == "bottomsheet-subtitle":
                    info["name"] = d.get("text", info["name"])
    return info


def parse_dates(data):
    dates = []
    for w in data.get("data", {}).get("topStickyWidgets", []):
        if w.get("type") != "horizontal-block-list":
            continue
        for item in w.get("data", []):
            texts = item.get("data", [])
            if len(texts) >= 3:
                style = item.get("styleId", "")
                dates.append(DateInfo(
                    date_code=item.get("id", ""),
                    status=DATE_STYLE_MAP.get(style, "UNKNOWN"),
                ))
    return dates


def parse_shows(data):
    shows = []
    for w in data.get("data", {}).get("showtimeWidgets", []):
        if w.get("type") != "groupList":
            continue
        for g in w.get("data", []):
            if g.get("type") != "venueGroup":
                continue
            for card in g.get("data", []):
                if card.get("type") != "venue-card":
                    continue
                addl = card.get("additionalData", {})
                vname = addl.get("venueName", "Unknown")
                vcode = addl.get("venueCode", "")

                for st in card.get("showtimes", []):
                    sa = st.get("additionalData", {})
                    date_code = str(
                        sa.get("showDateCode", "")
                        or sa.get("dateCode", "")
                    ).strip()
                    if not date_code and re.match(
                            r"^\d{8}", sa.get("cutOffDateTime", "")):
                        date_code = sa["cutOffDateTime"][:8]

                    show = ShowInfo(
                        venue_code=vcode,
                        venue_name=vname,
                        session_id=sa.get("sessionId", ""),
                        date_code=date_code,
                        time=st.get("title", ""),
                        time_code=sa.get("showTimeCode", ""),
                        screen_attr=(st.get("screenAttr", "")
                                     or sa.get("attributes", "")),
                    )
                    for cat in sa.get("categories", []):
                        ca = str(cat.get("availStatus", ""))
                        lbl, _ = AVAIL_STATUS_MAP.get(ca, ("UNKNOWN", ""))
                        show.categories.append(CatInfo(
                            name=cat.get("priceDesc", ""),
                            price=cat.get("curPrice", "0"),
                            status=ca,
                        ))
                    shows.append(show)
    return shows


# ──────────────────────────────────────────────────────────────────────
# FILTERING
# ──────────────────────────────────────────────────────────────────────
def filter_shows(shows, theatre_filter, time_periods, date_codes, format_filter=""):
    result = []
    kws = [k.strip().lower() for k in theatre_filter.split(",")
           if k.strip()] if theatre_filter else []
    periods = [p.strip().lower() for p in time_periods.split(",")
               if p.strip()] if time_periods else []
    dates_set = set(d.strip() for d in date_codes.split(",")
                    if d.strip()) if date_codes else set()
    fmt_kws = [f.strip().lower() for f in format_filter.split(",")
               if f.strip()] if format_filter else []

    for s in shows:
        # Theatre filter
        if kws:
            name_lower = s.venue_name.lower()
            if not any(k in name_lower for k in kws):
                continue

        # Date filter
        if dates_set and s.date_code and s.date_code not in dates_set:
            continue

        # Screen/format filter (e.g. "IMAX 2D", "Tamil 2D")
        if fmt_kws:
            fmt_lower = s.screen_attr.lower()
            if not any(k in fmt_lower for k in fmt_kws):
                continue

        # Time period filter
        if periods:
            try:
                tc = int(s.time_code)
            except ValueError:
                tc = 0
            matched = False
            for p in periods:
                if p in TIME_PERIODS:
                    lo, hi = TIME_PERIODS[p]
                    if lo <= tc < hi:
                        matched = True
                        break
            if not matched:
                continue

        result.append(s)
    return result


# ──────────────────────────────────────────────────────────────────────
# STATE (for change detection between runs)
# ──────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def build_state(shows, dates):
    """Build a comparable state dict."""
    show_state = {}
    for s in shows:
        for c in s.categories:
            key = f"{s.venue_code}|{s.session_id}|{s.date_code}|{c.name}"
            show_state[key] = {
                "venue": s.venue_name,
                "time": s.time,
                "date": s.date_code,
                "time_code": s.time_code,
                "cat": c.name,
                "price": c.price,
                "status": c.status,
            }

    date_state = {
        d.date_code: d.status for d in dates
    }

    return {"shows": show_state, "dates": date_state}


def detect_changes(old_state, new_state):
    """Returns a list of change dicts (kind/date_code/time_code/venue/time/...),
    deduped per showtime and sorted chronologically. No category/price info —
    that's display-level (email) detail, not a change fact."""
    changes = []

    # New dates opening
    old_dates = old_state.get("dates", {})
    new_dates = new_state.get("dates", {})
    for dc, status in new_dates.items():
        old_status = old_dates.get(dc)
        if (old_status == "NOT_OPEN"
                and status in ("BOOKABLE", "AVAILABLE")):
            changes.append({
                "kind": "date", "date_code": dc, "time_code": "0000",
                "venue": "", "time": "",
            })

    old_shows = old_state.get("shows", {})
    new_shows = new_state.get("shows", {})

    # New showtimes (dedupe — multiple categories on one show collapse to one line)
    seen_new = set()
    for key in set(new_shows) - set(old_shows):
        s = new_shows[key]
        dedupe_key = (s["venue"], s["date"], s.get("time_code", ""))
        if dedupe_key in seen_new:
            continue
        seen_new.add(dedupe_key)
        changes.append({
            "kind": "new", "date_code": s["date"],
            "time_code": s.get("time_code", ""),
            "venue": s["venue"], "time": s["time"],
        })

    # Sold out → available (dedupe — multiple categories collapse to one line)
    seen_back = set()
    for key, new_s in new_shows.items():
        old_s = old_shows.get(key)
        if old_s and old_s["status"] == "0" and new_s["status"] != "0":
            dedupe_key = (new_s["venue"], new_s["date"], new_s.get("time_code", ""))
            if dedupe_key in seen_back:
                continue
            seen_back.add(dedupe_key)
            lbl, ico = AVAIL_STATUS_MAP.get(
                new_s["status"], ("UNKNOWN", "⚪")
            )
            changes.append({
                "kind": "back", "date_code": new_s["date"],
                "time_code": new_s.get("time_code", ""),
                "venue": new_s["venue"], "time": new_s["time"],
                "status_label": lbl, "status_icon": ico,
            })

    changes.sort(
        key=lambda c: (c["date_code"] or "99999999", _time_sort_val(c["time_code"]))
    )
    return changes


# ──────────────────────────────────────────────────────────────────────
# EMAIL NOTIFICATION (Resend)
# ──────────────────────────────────────────────────────────────────────
def _time_sort_val(time_code):
    try:
        return int(time_code)
    except (TypeError, ValueError):
        return 0


def format_date_clean(date_code):
    """YYYYMMDD -> 'Thu, 30 Jul 2026'. Falls back gracefully if unparsable."""
    try:
        return datetime.strptime(date_code, "%Y%m%d").strftime("%a, %d %b %Y")
    except (TypeError, ValueError):
        return date_code or "N/A"


def format_change_line(c):
    """Plain-text rendering of a change dict (used for console + email text part)."""
    date_label = format_date_clean(c["date_code"]) if c["date_code"] else ""
    if c["kind"] == "date":
        return f"New date opened: {date_label}"
    if c["kind"] == "new":
        return f"New showtime: {c['venue']} — {c['time']} ({date_label})"
    if c["kind"] == "back":
        return (f"Back in stock: {c['venue']} — {c['time']} ({date_label}) "
                f"→ {c.get('status_label', '')}")
    return str(c)


def _change_row_html(c):
    """HTML rendering of a change dict for the email template."""
    date_label = escape(format_date_clean(c["date_code"])) if c["date_code"] else ""
    if c["kind"] == "date":
        return f'📅 <b>New date opened:</b> {date_label}'
    if c["kind"] == "new":
        return (f'🆕 <b>New showtime:</b> {escape(c["venue"])} — {escape(c["time"])} '
                 f'<span style="color:#888;">({date_label})</span>')
    if c["kind"] == "back":
        return (f'{c.get("status_icon", "⚪")} <b>Back in stock:</b> '
                 f'{escape(c["venue"])} — {escape(c["time"])} '
                 f'<span style="color:#888;">({date_label})</span> '
                 f'→ {escape(c.get("status_label", ""))}')
    return escape(str(c))


def send_email(subject, changes, shows, movie_info):
    api_key = RESEND_API_KEY.strip()
    to = RESEND_TO_EMAIL.strip()
    frm = RESEND_FROM_EMAIL.strip() or "onboarding@resend.dev"

    if not api_key or not to:
        print("  ⚠️  Skipping email — RESEND_API_KEY or RESEND_TO_EMAIL not set.")
        return

    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    movie_name = movie_info.get("name", "Movie")

    # Sort chronologically: earliest date first, then earliest time first
    sorted_changes = sorted(
        changes,
        key=lambda c: (c["date_code"] or "99999999", _time_sort_val(c["time_code"]))
    )
    sorted_shows = sorted(
        shows,
        key=lambda s: (s.date_code or "99999999", _time_sort_val(s.time_code), s.venue_name)
    )

    # Build changes HTML (chronological, clean dates, no category/price)
    changes_html = ""
    if sorted_changes:
        rows = "".join(
            f'<tr><td style="padding:10px 14px;border-bottom:1px solid #eee;'
            f'font-size:14px;color:#222;">{_change_row_html(c)}</td></tr>'
            for c in sorted_changes
        )
        changes_html = f"""
        <tr><td style="padding:0 20px;">
            <h3 style="margin:20px 0 10px 0;font-size:15px;font-weight:700;color:#111;">
                🔔 Changes Detected
            </h3>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="width:100%;border-collapse:collapse;background:#fafafa;
                          border-radius:8px;overflow:hidden;">
                {rows}
            </table>
        </td></tr>"""

    # Build showtimes section: grouped by date (chronological), then venue —
    # times only, no category/price clutter
    date_groups, date_order = {}, []
    for s in sorted_shows:
        if s.date_code not in date_groups:
            date_groups[s.date_code] = {}
            date_order.append(s.date_code)
        date_groups[s.date_code].setdefault(s.venue_name, []).append(s)

    shows_html = ""
    for dc in date_order:
        venue_blocks = ""
        for vname, vshows in date_groups[dc].items():
            time_chips = "".join(
                f'<span style="display:inline-block;margin:4px 6px 0 0;padding:6px 12px;'
                f'background:#eef2ff;color:#3949ab;border-radius:16px;font-size:13px;'
                f'font-weight:600;white-space:nowrap;">'
                f'{escape(s.time)}'
                f'{f" · {escape(s.screen_attr)}" if s.screen_attr else ""}'
                f'</span>'
                for s in vshows
            )
            venue_blocks += f"""
            <div style="margin:0 0 14px 0;">
                <div style="font-size:14px;font-weight:700;color:#222;margin:0 0 6px 0;">
                    📍 {escape(vname)}
                </div>
                <div>{time_chips}</div>
            </div>"""

        shows_html += f"""
        <tr><td style="padding:0 20px;">
            <div style="margin:20px 0 10px 0;padding:6px 14px;background:#111;color:#fff;
                        border-radius:6px;font-size:13px;font-weight:700;display:inline-block;">
                🗓️ {escape(format_date_clean(dc))}
            </div>
            {venue_blocks}
        </td></tr>"""

    if not shows_html:
        shows_html = ('<tr><td style="padding:0 20px 10px 20px;">'
                      '<p style="font-size:14px;color:#777;">'
                      'No showtimes currently match your filters.</p></td></tr>')

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  @media only screen and (max-width:480px) {{
    .bms-container {{ width:100% !important; }}
    .bms-banner {{ font-size:20px !important; padding:20px 16px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#f2f2f5;
             font-family:-apple-system,Segoe UI,Roboto,Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f2f2f5;padding:20px 0;">
<tr><td align="center">
<table role="presentation" class="bms-container" width="600" cellpadding="0" cellspacing="0"
       style="width:600px;max-width:100%;background:#ffffff;border-radius:10px;
              overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <tr><td class="bms-banner"
            style="background:linear-gradient(135deg,#e50914,#ff5f6d);color:#ffffff;
                   padding:26px 24px;text-align:center;">
        <div style="font-size:12px;font-weight:600;letter-spacing:1px;opacity:0.9;
                    text-transform:uppercase;margin:0 0 6px 0;">🎬 BMS Ticket Alert</div>
        <div style="font-size:24px;font-weight:800;line-height:1.25;">
            {escape(movie_name)}
        </div>
    </td></tr>
    <tr><td style="padding:14px 20px 0 20px;">
        <p style="margin:0;font-size:12px;color:#999;text-align:right;">
            Checked at {escape(now_str)}
        </p>
    </td></tr>
    {changes_html}
    <tr><td style="padding:0 20px;">
        <h3 style="margin:22px 0 10px 0;font-size:15px;font-weight:700;color:#111;">
            🎟️ Current Showtimes
        </h3>
    </td></tr>
    {shows_html}
    <tr><td style="padding:24px 20px;">
        <hr style="border:none;border-top:1px solid #eee;margin:0 0 14px 0;">
        <p style="margin:0;font-size:11px;color:#aaa;text-align:center;">
            Automated alert from BMS Ticket Notifier
        </p>
    </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    # Build plain-text version (chronological, clean dates, no category/price)
    plain_lines = [subject, "", f"Checked at: {now_str}", ""]
    if sorted_changes:
        plain_lines.append("Changes Detected:")
        plain_lines.extend(f"  - {format_change_line(c)}" for c in sorted_changes)
        plain_lines.append("")
    plain_lines.append("Current Showtimes:")
    for dc in date_order:
        plain_lines.append(f"\n{format_date_clean(dc)}")
        for vname, vshows in date_groups[dc].items():
            plain_lines.append(f"  {vname}")
            for s in vshows:
                fmt = f" [{s.screen_attr}]" if s.screen_attr else ""
                plain_lines.append(f"    - {s.time}{fmt}")
    plain_lines.extend(["", "This is an automated alert from BMS Ticket Notifier."])
    plain = "\n".join(plain_lines)

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": frm, "to": [to],
                "subject": subject,
                "text": plain, "html": html,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print(f"  ✅ Email sent to {to}")
        else:
            print(f"  ❌ Resend {resp.status_code}: {resp.text}")
            sys.exit(1)
    except requests.RequestException as e:
        print(f"  ❌ Email failed: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────
def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] BMS Ticket Checker — CI mode")

    # Parse config
    parsed = parse_bms_url(CONFIG["url"])
    event_code = parsed["event_code"]
    region_slug = parsed["region_slug"]
    url_date = parsed.get("date_code", "")

    if not event_code or not region_slug:
        print("  ❌ Invalid BMS_URL. Could not extract event/region.")
        sys.exit(1)

    region_code, region_slug_r, lat, lon, geohash = resolve_region(
        region_slug
    )

    # Determine dates to check
    raw_dates = CONFIG["dates"].strip()
    if raw_dates:
        date_list = [d.strip() for d in raw_dates.split(",") if d.strip()]
    elif url_date:
        date_list = [url_date]
    else:
        date_list = [""]

    print(f"  Event: {event_code}  Region: {region_code}  "
          f"Dates: {date_list}")

    # Fetch data for each date
    all_shows = []
    all_dates = []
    movie_info = {"name": "Unknown", "language": ""}

    for dc in date_list:
        data = fetch_bms(event_code, dc, region_code,
                         region_slug_r, lat, lon, geohash)
        if not data:
            print(f"  ⚠️  No data for date {dc or '(default)'}")
            continue

        if movie_info["name"] == "Unknown":
            movie_info = parse_movie_info(data)

        all_dates.extend(parse_dates(data))
        all_shows.extend(parse_shows(data))

    if not all_shows:
        print("  ❌ No showtimes found.")
        sys.exit(0)

    print(f"  🎬 {movie_info['name']}  {movie_info['language']}")

    # Apply filters
    filtered = filter_shows(
        all_shows,
        CONFIG["theatre"],
        CONFIG["time_period"],
        CONFIG["dates"],
        CONFIG["format"],
    )
    print(f"  📊 {len(filtered)} showtime(s) after filters")

    # Build state & detect changes
    new_state = build_state(filtered, all_dates)
    old_state = load_state()

    changes = []
    if old_state:
        changes = detect_changes(old_state, new_state)

    save_state(new_state)

    if changes:
        print(f"\n  ⚡ {len(changes)} change(s) detected:")
        for c in changes:
            print(f"     {format_change_line(c)}")
        send_email(
            f"BMS Alert: {movie_info['name']} - {len(changes)} change(s)",
            changes, filtered, movie_info,
        )
    else:
        print("  ✅ No changes since last check.")

    # Print current status
    print(f"\n  Current status ({len(filtered)} shows):")
    for s in filtered:
        cats = ", ".join(
            f"{c.name}=₹{c.price}({AVAIL_STATUS_MAP.get(c.status, ('?',''))[0]})"
            for c in s.categories
        )
        fmt = f"|{s.screen_attr}" if s.screen_attr else ""
        print(f"    {s.venue_name} — {s.time}{fmt} [{s.date_code}] — {cats}")

    print("\n  Done.")


if __name__ == "__main__":
    main()
