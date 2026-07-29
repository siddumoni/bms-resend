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
    "coimbatore": ("COIM",   "coimbatore",  "11.016845", "76.955832", "t9y"),
}


# ─────────────────────────────────────���────────────────────────────────
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
def filter_shows(shows, theatre_filter, time_periods, date_codes):
    result = []
    kws = [k.strip().lower() for k in theatre_filter.split(",")
           if k.strip()] if theatre_filter else []
    periods = [p.strip().lower() for p in time_periods.split(",")
               if p.strip()] if time_periods else []
    dates_set = set(d.strip() for d in date_codes.split(",")
                    if d.strip()) if date_codes else set()

    for s in shows:
        # Theatre filter
        if kws:
            name_lower = s.venue_name.lower()
            if not any(k in name_lower for k in kws):
                continue

        # Date filter
        if dates_set and s.date_code and s.date_code not in dates_set:
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
                "cat": c.name,
                "price": c.price,
                "status": c.status,
            }

    date_state = {
        d.date_code: d.status for d in dates
    }

    return {"shows": show_state, "dates": date_state}


def detect_changes(old_state, new_state):
    changes = []

    # New dates opening
    old_dates = old_state.get("dates", {})
    new_dates = new_state.get("dates", {})
    for dc, status in new_dates.items():
        old_status = old_dates.get(dc)
        if (old_status == "NOT_OPEN"
                and status in ("BOOKABLE", "AVAILABLE")):
            changes.append(f"📅 NEW DATE OPENED: {dc}")

    old_shows = old_state.get("shows", {})
    new_shows = new_state.get("shows", {})

    # New showtimes
    for key in set(new_shows) - set(old_shows):
        s = new_shows[key]
        changes.append(
            f"🆕 NEW: {s['venue']} {s['time']} [{s['date']}] "
            f"— {s['cat']} ₹{s['price']}"
        )

    # Sold out → available
    for key, new_s in new_shows.items():
        old_s = old_shows.get(key)
        if old_s and old_s["status"] == "0" and new_s["status"] != "0":
            lbl, ico = AVAIL_STATUS_MAP.get(
                new_s["status"], ("UNKNOWN", "⚪")
            )
            changes.append(
                f"{ico} BACK: {new_s['venue']} {new_s['time']} "
                f"[{new_s['date']}] — {new_s['cat']} → {lbl}"
            )

    return changes


# ──────────────────────────────────────────────────────────────────────
# EMAIL NOTIFICATION (Resend)
# ──────────────────────────────────────────────────────────────────────
def _cat_status_label(status):
    return AVAIL_STATUS_MAP.get(status, ("UNKNOWN", ""))[0]

def _format_date(date_code):
    """20260730 -> 30 Jul 2026"""
    try:
        return datetime.strptime(date_code, "%Y%m%d").strftime("%d %b %Y")
    except Exception:
        return date_code or "-"


def _time_sort_key(show):
    try:
        return int(show.time_code)
    except Exception:
        return 9999


def _group_shows(shows):
    """
    Returns:
    {
        theatre:{
            date:[
                ShowInfo...
            ]
        }
    }
    """
    grouped = {}

    for s in sorted(
        shows,
        key=lambda x: (
            x.venue_name.lower(),
            x.date_code,
            _time_sort_key(x),
        ),
    ):
        grouped.setdefault(s.venue_name, {})
        grouped[s.venue_name].setdefault(s.date_code, [])
        grouped[s.venue_name][s.date_code].append(s)

    return grouped


def _status_cells(show):
    """
    Returns html/text for each status column.
    """
    cols = {
        "3": [],   # Available
        "1": [],   # Almost Full
        "2": [],   # Filling Fast
        "0": []    # Sold Out
    }

    for c in show.categories:
        cols.setdefault(c.status, []).append(
            f"{escape(c.name)} ₹{escape(c.price)}"
        )

    def build(items):
        if not items:
            return "—"
        return "<br>".join(items)

    return (
        build(cols["3"]),
        build(cols["1"]),
        build(cols["2"]),
        build(cols["0"]),
    )


def _status_text(show):
    """
    Plain text version.
    """
    cols = {
        "3": [],
        "1": [],
        "2": [],
        "0": [],
    }

    for c in show.categories:
        cols.setdefault(c.status, []).append(
            f"{c.name} ₹{c.price}"
        )

    def build(items):
        return ", ".join(items) if items else "-"

    return (
        build(cols["3"]),
        build(cols["1"]),
        build(cols["2"]),
        build(cols["0"]),
    )

def send_email(subject, changes, shows, movie_info):
    api_key = RESEND_API_KEY.strip()
    to = RESEND_TO_EMAIL.strip()
    frm = RESEND_FROM_EMAIL.strip() or "onboarding@resend.dev"

    if not api_key or not to:
        print("  ⚠️  Skipping email — RESEND_API_KEY or RESEND_TO_EMAIL not set.")
        return

    movie_name = movie_info.get("name", "Movie")
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    grouped = _group_shows(shows)

    total_theatres = len(grouped)
    total_showtimes = sum(
        len(show_list)
        for dates in grouped.values()
        for show_list in dates.values()
    )

    available_count = 0
    almost_count = 0
    filling_count = 0
    sold_count = 0

    for s in shows:
        for c in s.categories:
            if c.status == "3":
                available_count += 1
            elif c.status == "1":
                almost_count += 1
            elif c.status == "2":
                filling_count += 1
            elif c.status == "0":
                sold_count += 1

    if changes:
        change_items = "".join(
            f"<li style='margin-bottom:6px'>{escape(c)}</li>"
            for c in changes
        )

        changes_html = f"""
        <div style="margin-bottom:25px;">
            <h2 style="margin:0 0 10px 0;color:#d97706;">
                🚨 Changes Detected
            </h2>

            <ul style="padding-left:20px;margin:0;">
                {change_items}
            </ul>
        </div>
        """
    else:
        changes_html = ""

    theatre_html = ""

    for theatre_name, dates in grouped.items():

        theatre_html += f"""
        <div style="
            margin-top:28px;
            border:1px solid #ddd;
            border-radius:8px;
            overflow:hidden;
        ">

        <div style="
            background:#1f2937;
            color:white;
            padding:12px 16px;
            font-size:18px;
            font-weight:bold;
        ">
            📍 {escape(theatre_name)}
        </div>

        <div style="padding:16px;">
        """

        for date_code in sorted(dates.keys()):

            theatre_html += f"""
            <h3 style="
                margin-top:0;
                margin-bottom:10px;
                color:#2563eb;
            ">
                📅 {_format_date(date_code)}
            </h3>

            <table style="
                width:100%;
                border-collapse:collapse;
                margin-bottom:22px;
                font-size:13px;
            ">

            <tr style="background:#f5f5f5;">
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">Time</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">🟢 Available</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">🟡 Almost Full</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">🟠 Filling Fast</th>
                <th style="padding:8px;border:1px solid #ddd;text-align:left;">🔴 Sold Out</th>
            </tr>
            """

            for show in sorted(dates[date_code], key=_time_sort_key):

                available, almost, filling, sold = _status_cells(show)

                screen = (
                    f"<br><span style='color:#666;font-size:12px'>[{escape(show.screen_attr)}]</span>"
                    if show.screen_attr
                    else ""
                )

                theatre_html += f"""
                <tr>

                    <td style="
                        padding:8px;
                        border:1px solid #ddd;
                        vertical-align:top;
                        white-space:nowrap;
                    ">
                        <b>{escape(show.time)}</b>
                        {screen}
                    </td>

                    <td style="padding:8px;border:1px solid #ddd;">
                        {available}
                    </td>

                    <td style="padding:8px;border:1px solid #ddd;">
                        {almost}
                    </td>

                    <td style="padding:8px;border:1px solid #ddd;">
                        {filling}
                    </td>

                    <td style="padding:8px;border:1px solid #ddd;">
                        {sold}
                    </td>

                </tr>
                """

            theatre_html += "</table>"

        theatre_html += """
        </div>
        </div>
        """
    html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
</head>

<body style="
    margin:0;
    padding:24px;
    font-family:Arial,Helvetica,sans-serif;
    background:#f5f5f5;
">

<div style="
    max-width:1000px;
    margin:auto;
    background:white;
    padding:24px;
    border-radius:10px;
">

<h1 style="margin-top:0;">
🎬 {escape(movie_name)}
</h1>

<p style="color:#666;margin-top:-8px;">
Checked: {now_str}
</p>

<div style="
    background:#f8fafc;
    border:1px solid #ddd;
    padding:16px;
    border-radius:8px;
    margin:20px 0;
">

<h2 style="margin-top:0;">
📊 Summary
</h2>

<table style="border-collapse:collapse;">

<tr><td style="padding:4px 20px 4px 0;">🎭 Theatres</td><td><b>{total_theatres}</b></td></tr>
<tr><td style="padding:4px 20px 4px 0;">🎬 Showtimes</td><td><b>{total_showtimes}</b></td></tr>
<tr><td style="padding:4px 20px 4px 0;">🟢 Available</td><td><b>{available_count}</b></td></tr>
<tr><td style="padding:4px 20px 4px 0;">🟡 Almost Full</td><td><b>{almost_count}</b></td></tr>
<tr><td style="padding:4px 20px 4px 0;">🟠 Filling Fast</td><td><b>{filling_count}</b></td></tr>
<tr><td style="padding:4px 20px 4px 0;">🔴 Sold Out</td><td><b>{sold_count}</b></td></tr>

</table>

</div>

{changes_html}

{theatre_html}

<hr style="margin-top:30px;">

<p style="font-size:12px;color:#888;">
Generated automatically by your BookMyShow Ticket Notifier.
</p>

</div>

</body>
</html>
"""

    # ---------- Plain Text ----------

    plain = []

    plain.append(subject)
    plain.append("")
    plain.append(f"Checked: {now_str}")
    plain.append("")

    if changes:
        plain.append("Changes Detected")
        plain.append("----------------")

        for c in changes:
            plain.append(c)

        plain.append("")

    plain.append("Summary")
    plain.append("-------")
    plain.append(f"Theatres      : {total_theatres}")
    plain.append(f"Showtimes     : {total_showtimes}")
    plain.append(f"Available     : {available_count}")
    plain.append(f"Almost Full   : {almost_count}")
    plain.append(f"Filling Fast  : {filling_count}")
    plain.append(f"Sold Out      : {sold_count}")
    plain.append("")

    for theatre_name, dates in grouped.items():

        plain.append("=" * 70)
        plain.append(theatre_name)
        plain.append("=" * 70)

        for date_code in sorted(dates.keys()):

            plain.append(_format_date(date_code))

            for show in sorted(dates[date_code], key=_time_sort_key):

                a, af, ff, so = _status_text(show)

                plain.append(f"  {show.time}")

                if a != "-":
                    plain.append(f"      Available    : {a}")

                if af != "-":
                    plain.append(f"      Almost Full  : {af}")

                if ff != "-":
                    plain.append(f"      Filling Fast : {ff}")

                if so != "-":
                    plain.append(f"      Sold Out     : {so}")

            plain.append("")

    plain = "\n".join(plain)

    try:

        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": frm,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": plain,
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
            print(f"     {c}")
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
