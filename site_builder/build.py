import json
import shutil
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site_src"
OUTPUT = ROOT / "dist"


def render_cards(cards):
    return "\n".join(
        f"""<article class=\"card\">
          <p class=\"eyebrow\">{escape(card['eyebrow'])}</p>
          <h3>{escape(card['title'])}</h3>
          <p>{escape(card['body'])}</p>
          <a href=\"{escape(card['url'], quote=True)}\">{escape(card['link'])}<span aria-hidden=\"true\"> ↗</span></a>
        </article>"""
        for card in cards
    )


def show_artist_and_note(billing):
    known_artists = ("Humble Chuck", "Charlie Schlinkert", "Del Water Gap", "Star Four")
    for artist in known_artists:
        if billing.startswith(artist):
            note = billing[len(artist) :].lstrip(" —·")
            return artist, note
    if billing.startswith("With "):
        return billing.removeprefix("With "), ""
    if billing.startswith("Guitar-and-vibes duo with Holden Jaffe"):
        note = billing.split("—", 1)[1].strip() if "—" in billing else "Guitar-and-vibes duo"
        return "Charlie Schlinkert + Holden Jaffe", note
    return "Artist not listed", billing


def render_show(show):
    performance_date = date.fromisoformat(show["date"])
    artist, note = show_artist_and_note(show["billing"])
    note_html = f'<p class="show-note">{escape(note)}</p>' if note else '<p class="show-note" aria-hidden="true"></p>'
    return f"""<li class=\"show-row\">
          <time datetime=\"{escape(show['date'], quote=True)}\"><span>{performance_date.strftime('%b')}</span><strong>{performance_date.strftime('%d')}</strong></time>
          <div class=\"show-credit\"><span class=\"eyebrow\">Artist</span><h3>{escape(artist)}</h3></div>
          <div class=\"show-credit\"><span class=\"eyebrow\">Venue</span><h3>{escape(show['venue'])}</h3><p>{escape(show['location'])}</p></div>
          {note_html}
        </li>"""


def render_past_shows(shows):
    shows_by_year = defaultdict(list)
    for show in shows:
        shows_by_year[show["date"][:4]].append(show)

    groups = []
    for year in sorted(shows_by_year, reverse=True):
        year_shows = shows_by_year[year]
        count_label = f"{len(year_shows)} {'show' if len(year_shows) == 1 else 'shows'}"
        rows = "\n".join(render_show(show) for show in year_shows)
        groups.append(
            f"""<details class=\"show-year\">
          <summary><strong>{year}</strong><span>{count_label}</span><i aria-hidden=\"true\"></i></summary>
          <ol class=\"show-list\">{rows}</ol>
        </details>"""
        )
    return "\n".join(groups)


def render_calendar(show):
    def ical_timestamp(value):
        return value.replace("-", "").replace(":", "")[:15]

    def ical_text(value):
        return (
            value.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n")
        )

    summary = ical_text(f"{show['artist']} at {show['venue']}")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Humble Chuck//Shows//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{show['artist'].lower().replace(' ', '-')}-{show['date'].replace('-', '')}@humblechuck.com",
        f"DTSTART;TZID=America/New_York:{ical_timestamp(show['start_iso'])}",
        f"DTEND;TZID=America/New_York:{ical_timestamp(show['end_iso'])}",
        f"SUMMARY:{summary}",
        f"LOCATION:{ical_text(show.get('address') or show['location'])}",
        f"DESCRIPTION:{ical_text(show['description'])} More: https://humblechuck.com/music#upcoming",
        "URL:https://humblechuck.com/music#upcoming",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)


def common_values(content):
    return {
        "name": escape(content["name"]),
        "email": escape(content["email"]),
        "email_url": escape(f"mailto:{content['email']}", quote=True),
    }


def render_template(name, values):
    template = Template((SOURCE / name).read_text(encoding="utf-8"))
    return template.substitute(values)


def build() -> Path:
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    show_history = json.loads(
        (SOURCE / "show_history.json").read_text(encoding="utf-8")
    )["shows"]
    shared = common_values(content)

    home = render_template(
        "index.html",
        {
            **shared,
            "headline": escape(content["home"]["headline"]),
            "introduction": escape(content["home"]["introduction"]),
        },
    )
    data = render_template(
        "data.html",
        {
            **shared,
            "headline": escape(content["data"]["headline"]),
            "introduction": escape(content["data"]["introduction"]),
            "cards": render_cards(content["data"]["cards"]),
        },
    )
    show = content["music"]["upcoming_show"]
    show_date = date.fromisoformat(show["date"])
    calendar_name = f"humble-chuck-{show['date']}.ics"
    has_calendar = bool(show.get("start_iso") and show.get("end_iso"))
    calendar_action = (
        f'<a class="button button-primary" href="/{calendar_name}" download>Add to calendar</a>'
        if has_calendar else ""
    )
    venue_action = (
        f'<a class="button" href="{escape(show["venue_url"], quote=True)}" target="_blank" rel="noopener noreferrer">Venue calendar <span aria-hidden="true">↗</span></a>'
        if show.get("venue_url") else ""
    )
    map_url = "https://www.google.com/maps/search/?" + urlencode(
        {"api": "1", "query": show.get("address") or f"{show['venue']}, {show['location']}"}
    )
    event_data = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": f"{show['artist']} at {show['venue']}",
        "startDate": show.get("start_iso") or show["date"],
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "MusicVenue",
            "name": show["venue"],
            "address": show.get("address") or show["location"],
        },
        "performer": {"@type": "MusicGroup", "name": show["artist"]},
        "description": show["description"],
        "image": "https://humblechuck.com/og.png",
        "url": "https://humblechuck.com/music#upcoming",
    }
    if show.get("end_iso"):
        event_data["endDate"] = show["end_iso"]
    music = render_template(
        "music.html",
        {
            **shared,
            "headline": escape(content["music"]["headline"]),
            "introduction": escape(content["music"]["introduction"]),
            "show_artist": escape(show["artist"]),
            "show_date_display": escape(show["date_display"]),
            "show_month": show_date.strftime("%b").upper(),
            "show_day": show_date.strftime("%d"),
            "show_year": str(show_date.year),
            "show_time": escape(show.get("time") or "Time TBD"),
            "show_start_iso": escape(show.get("start_iso") or show["date"], quote=True),
            "show_venue": escape(show["venue"]),
            "show_location": escape(show["location"]),
            "show_address": escape(show.get("address") or show["location"]),
            "show_description": escape(show["description"]),
            "show_calendar_action": calendar_action,
            "show_venue_action": venue_action,
            "show_map_url": escape(map_url, quote=True),
            "share_title": escape(f"{show['artist']} at {show['venue']}", quote=True),
            "share_text": escape(f"{show['artist']} at {show['venue']} — {show['date_display']}. {show.get('time') or 'Time TBD'}. {show['location']}.", quote=True),
            "event_json": json.dumps(event_data, ensure_ascii=False).replace("<", "\\u003c"),
            "past_shows": render_past_shows(show_history),
            "past_show_range": f"{show_history[-1]['date'][:4]}–{show_history[0]['date'][:4]}",
            "playlist_url": escape(content["music"]["playlist_url"], quote=True),
            "playlist_embed_url": escape(
                content["music"]["playlist_embed_url"], quote=True
            ),
            "cards": render_cards(content["music"]["cards"]),
        },
    )
    contact = render_template(
        "contact.html",
        {
            **shared,
            "headline": escape(content["contact"]["headline"]),
            "introduction": escape(content["contact"]["introduction"]),
        },
    )

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    (OUTPUT / "data").mkdir(parents=True)
    (OUTPUT / "music").mkdir(parents=True)
    (OUTPUT / "contact").mkdir(parents=True)
    (OUTPUT / "index.html").write_text(home, encoding="utf-8")
    (OUTPUT / "data" / "index.html").write_text(data, encoding="utf-8")
    (OUTPUT / "music" / "index.html").write_text(music, encoding="utf-8")
    (OUTPUT / "contact" / "index.html").write_text(contact, encoding="utf-8")
    if has_calendar:
        (OUTPUT / calendar_name).write_text(
            render_calendar(show), encoding="utf-8", newline=""
        )

    not_found = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Page not found — {escape(content['name'])}</title><link rel=\"icon\" href=\"/favicon.ico\" sizes=\"any\"><link rel=\"icon\" type=\"image/png\" sizes=\"32x32\" href=\"/favicon-32.png\"><link rel=\"stylesheet\" href=\"/styles.css\"></head>
<body><main id=\"main\"><section class=\"not-found\"><p class=\"eyebrow\">404</p><h1>That page wandered off.</h1><p><a href=\"/\">Head home</a></p></section></main></body></html>"""
    (OUTPUT / "404.html").write_text(not_found, encoding="utf-8")
    for asset in (
        "styles.css",
        "site.js",
        "og.png",
        "hc-logo.png",
        "favicon.ico",
        "favicon-32.png",
        "apple-touch-icon.png",
        "music-show-og.png",
    ):
        source_asset = SOURCE / asset
        if source_asset.exists():
            shutil.copy2(source_asset, OUTPUT / asset)
    (OUTPUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://humblechuck.com/sitemap.xml\n",
        encoding="utf-8",
    )
    (OUTPUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://humblechuck.com/</loc></url>'
        '<url><loc>https://humblechuck.com/data</loc></url>'
        '<url><loc>https://humblechuck.com/music</loc></url>'
        '<url><loc>https://humblechuck.com/contact</loc></url>'
        '</urlset>\n',
        encoding="utf-8",
    )
    return OUTPUT


if __name__ == "__main__":
    print(f"Built site in {build()}")
