import json
import shutil
from datetime import date
from html import escape
from pathlib import Path
from string import Template


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


def render_past_shows(shows):
    return "\n".join(
        f"""<li class=\"show-row\">
          <time datetime=\"{escape(show['date'], quote=True)}\"><span>{date.fromisoformat(show['date']).strftime('%b')}</span><strong>{date.fromisoformat(show['date']).strftime('%d')}</strong><small>{date.fromisoformat(show['date']).year}</small></time>
          <div><h3>{escape(show['venue'])}</h3><p>{escape(show['location'])}</p></div>
          <p>{escape(show['billing'])}</p>
        </li>"""
        for show in shows
    )


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
        f"LOCATION:{ical_text(show['address'])}",
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
    event_data = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": f"{show['artist']} at {show['venue']}",
        "startDate": show["start_iso"],
        "endDate": show["end_iso"],
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "MusicVenue",
            "name": show["venue"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "709 Lorimer Street",
                "addressLocality": "Brooklyn",
                "addressRegion": "NY",
                "postalCode": "11211",
                "addressCountry": "US",
            },
        },
        "performer": {"@type": "MusicGroup", "name": show["artist"]},
        "description": show["description"],
        "image": "https://humblechuck.com/music-show-og.png",
        "url": "https://humblechuck.com/music#upcoming",
    }
    music = render_template(
        "music.html",
        {
            **shared,
            "headline": escape(content["music"]["headline"]),
            "introduction": escape(content["music"]["introduction"]),
            "about": escape(content["music"]["about"]),
            "show_artist": escape(show["artist"]),
            "show_date_display": escape(show["date_display"]),
            "show_time": escape(show["time"]),
            "show_start_iso": escape(show["start_iso"], quote=True),
            "show_venue": escape(show["venue"]),
            "show_address": escape(show["address"]),
            "show_description": escape(show["description"]),
            "show_venue_url": escape(show["venue_url"], quote=True),
            "show_map_url": "https://www.google.com/maps/search/?api=1&amp;query=709%20Lorimer%20Street%20Brooklyn%20NY%2011211",
            "share_title": escape(f"{show['artist']} at {show['venue']}", quote=True),
            "share_text": escape(f"{show['artist']} at {show['venue']} — September 5, 2026 at 8 PM.", quote=True),
            "event_json": json.dumps(event_data, ensure_ascii=False).replace("<", "\\u003c"),
            "past_shows": render_past_shows(content["music"]["past_shows"]),
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
    (OUTPUT / "humble-chuck-petes-2026-09-05.ics").write_text(
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
