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
# Replace the entire send_email(...) function in main.py with this:

def _cat_status_label(status):
    return AVAIL_STATUS_MAP.get(status, ("UNKNOWN", ""))[0]


def _time_sort_key(time_code, time_text):
    try:
        return int(time_code or 0)
    except (TypeError, ValueError):
        pass

    text = (time_text or "").strip().lower()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not m:
        return 9999

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridian = m.group(3)

    if meridian == "pm" and hour != 12:
        hour += 12
    elif meridian == "am" and hour == 12:
        hour = 0

    return hour * 100 + minute


def _date_sort_key(date_code):
    try:
        return int(date_code or 99999999)
    except (TypeError, ValueError):
        return 99999999


def _group_sorted_shows(shows):
    venue_groups = {}
    for s in shows:
        venue_groups.setdefault(s.venue_name, []).append(s)

    grouped = []
    for venue_name in sorted(venue_groups.keys(), key=lambda x: x.lower()):
        venue_shows = sorted(
            venue_groups[venue_name],
            key=lambda s: (
                _date_sort_key(s.date_code),
                _time_sort_key(s.time_code, s.time),
                s.time.lower(),
                s.screen_attr.lower() if s.screen_attr else "",
            ),
        )
        grouped.append((venue_name, venue_shows))
    return grouped


def _format_show_label(s):
    date_part = s.date_code.strip() if s.date_code else "TBD"
    time_part = s.time.strip() if s.time else "TBD"
    fmt = f" • {s.screen_attr}" if s.screen_attr else ""
    return f"{date_part} • {time_part}{fmt}"


def _build_status_badge(status):
    label, icon = AVAIL_STATUS_MAP.get(status, ("UNKNOWN", "⚪"))
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'font-size:12px;font-weight:700;background:#f3f4f6;color:#111827;">'
        f'{escape(icon)} {escape(label)}</span>'
    )


def send_email(subject, changes, shows, movie_info):
    api_key = RESEND_API_KEY.strip()
    to = RESEND_TO_EMAIL.strip()
    frm = RESEND_FROM_EMAIL.strip() or "onboarding@resend.dev"

    if not api_key or not to:
        print("  ⚠️  Skipping email — RESEND_API_KEY or RESEND_TO_EMAIL not set.")
        return

    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    movie_name = movie_info.get("name", "Movie")
    grouped_shows = _group_sorted_shows(shows)

    # Build changes HTML
    changes_html = ""
    if changes:
        rows = "".join(
            f'<li style="padding:4px 0;font-size:14px;line-height:1.5;">{escape(c)}</li>'
            for c in changes
        )
        changes_html = f"""
        <div style="margin:0 0 20px 0;padding:16px;border:1px solid #e5e7eb;border-radius:14px;background:#fafafa;">
            <h3 style="margin:0 0 10px 0;font-size:15px;font-weight:700;color:#111827;">
                Changes Detected
            </h3>
            <ul style="margin:0;padding-left:20px;color:#374151;">
                {rows}
            </ul>
        </div>"""

    # Build shows section grouped by venue and sorted chronologically
    shows_html = ""
    for vname, vshows in grouped_shows:
        show_rows = ""
        for s in vshows:
            cat_rows = ""
            for c in sorted(
                s.categories,
                key=lambda x: (
                    int(x.status) if str(x.status).isdigit() else 9,
                    int(x.price) if str(x.price).isdigit() else 999999,
                    (x.name or "").lower(),
                ),
            ):
                cat_rows += f"""
                <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;
                            padding:10px 0;border-top:1px solid #eef2f7;">
                    <div style="min-width:0;flex:1;">
                        <div style="font-size:14px;font-weight:700;color:#111827;line-height:1.35;">
                            {escape(c.name)}
                        </div>
                        <div style="margin-top:4px;font-size:12px;color:#6b7280;line-height:1.35;">
                            Status: {_build_status_badge(c.status)}
                        </div>
                    </div>
                    <div style="font-size:14px;font-weight:700;color:#111827;white-space:nowrap;">
                        ₹{escape(c.price)}
                    </div>
                </div>"""

            screen_html = (
                f'<div style="margin-top:6px;font-size:12px;color:#6b7280;">'
                f'Screen: {escape(s.screen_attr)}</div>'
                if s.screen_attr else ""
            )

            show_rows += f"""
            <div style="padding:14px 0;border-top:1px solid #e5e7eb;">
                <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
                    <div style="min-width:0;flex:1;">
                        <div style="font-size:15px;font-weight:700;color:#111827;line-height:1.35;">
                            {_format_show_label(s)}
                        </div>
                        {screen_html}
                    </div>
                </div>
                <div style="margin-top:10px;">
                    {cat_rows}
                </div>
            </div>"""

        shows_html += f"""
        <div style="margin:0 0 18px 0;padding:16px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
                <h3 style="margin:0;font-size:16px;font-weight:800;color:#111827;">
                    {escape(vname)}
                </h3>
                <span style="font-size:12px;color:#6b7280;">
                    {len(vshows)} showtime(s)
                </span>
            </div>
            {show_rows}
        </div>"""

    html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <div style="max-width:760px;margin:0 auto;padding:24px;">
        <div style="padding:24px;border-radius:18px;background:#ffffff;border:1px solid #e5e7eb;">
            <div style="margin:0 0 18px 0;">
                <div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#6b7280;">
                    BMS Alert
                </div>
                <h2 style="margin:6px 0 8px 0;font-size:24px;line-height:1.25;color:#111827;">
                    {escape(movie_name)}
                </h2>
                <div style="font-size:13px;color:#6b7280;line-height:1.5;">
                    Checked at {escape(now_str)}
                </div>
            </div>

            {changes_html}

            <div style="margin:0 0 12px 0;">
                <h3 style="margin:0;font-size:18px;font-weight:800;color:#111827;">
                    Current Showtimes
                </h3>
                <div style="margin-top:6px;font-size:13px;color:#6b7280;line-height:1.5;">
                    Sorted by date and show time for easier reading.
                </div>
            </div>

            {shows_html}

            <div style="margin-top:20px;padding-top:14px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;">
                This is an automated alert from BMS Ticket Notifier.
            </div>
        </div>
    </div>
</body>
</html>"""

    # Build plain-text version with chronological order
    plain_lines = [subject, "", f"Checked at: {now_str}", ""]
    if changes:
        plain_lines.append("Changes Detected:")
        plain_lines.extend(f"  - {c}" for c in changes)
        plain_lines.append("")
    plain_lines.append("Current Showtimes:")
    for vname, vshows in grouped_shows:
        plain_lines.append(f"\n{vname}")
        for s in vshows:
            plain_lines.append(f"  {s.date_code or 'TBD'} | {s.time or 'TBD'}")
            if s.screen_attr:
                plain_lines.append(f"    Screen: {s.screen_attr}")
            for c in sorted(
                s.categories,
                key=lambda x: (
                    int(x.status) if str(x.status).isdigit() else 9,
                    int(x.price) if str(x.price).isdigit() else 999999,
                    (x.name or "").lower(),
                ),
            ):
                plain_lines.append(
                    f"    - {c.name} | ₹{c.price} | {_cat_status_label(c.status)}"
                )
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
