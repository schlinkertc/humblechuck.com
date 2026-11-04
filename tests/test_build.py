import json
import re
import shutil
from datetime import date
from html import escape
from importlib import import_module

from site_builder.build import (
    OUTPUT,
    SOURCE,
    build,
    render_cards,
    render_past_shows,
    show_artist_and_note,
)


def test_build_creates_deployable_site():
    output = build()
    expected = {
        "index.html",
        "404.html",
        "styles.css",
        "site.js",
        "og.png",
        "hc-logo.png",
        "favicon.ico",
        "favicon-32.png",
        "apple-touch-icon.png",
        "music-show-og.png",
        "robots.txt",
        "sitemap.xml",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    index = (OUTPUT / "index.html").read_text(encoding="utf-8")
    data = (OUTPUT / "data" / "index.html").read_text(encoding="utf-8")
    music = (OUTPUT / "music" / "index.html").read_text(encoding="utf-8")
    contact = (OUTPUT / "contact" / "index.html").read_text(encoding="utf-8")
    robots = (OUTPUT / "robots.txt").read_text(encoding="utf-8")
    sitemap = (OUTPUT / "sitemap.xml").read_text(encoding="utf-8")
    assert "Charlie Schlinkert" in index
    assert "$headline" not in index
    assert 'id="main"' in index
    assert 'href="/data"' in index
    assert 'href="/music"' in index
    assert 'href="/contact"' in index
    assert 'href="/favicon.ico"' in index
    assert 'src="/hc-logo.png"' in index
    assert "Useful systems for messy questions." in data
    assert '<meta name="robots" content="index, follow">' in data
    assert '<link rel="canonical" href="https://humblechuck.com/data">' in data
    assert 'id="overview"' in data
    assert 'id="projects"' in data
    assert "Music is a present-tense practice." in music
    assert '<meta name="robots" content="index, follow">' in music
    assert '<link rel="canonical" href="https://humblechuck.com/music">' in music
    assert "something I used to do" not in music
    assert "Songs I’ve" in music
    assert "open.spotify.com/embed/playlist/4XeFzR948Yyk1X4SsXXogr" in music
    assert 'title="Spotify playlist: Songs Charlie Schlinkert has played on"' in music
    assert 'id="upcoming"' in music
    assert 'id="overview"' in music
    assert 'id="recordings"' in music
    assert 'id="listen-connect"' in music
    assert 'id="past-shows"' in music
    assert "Still playing" not in music
    assert "The work keeps moving" not in music
    assert "co-founded Del Water Gap" not in music
    assert "Humble Chuck" in music
    assert "Wednesday, December 9, 2026" in music
    assert "The Delancey" in music
    assert "Pete’s Candy Store" in music
    assert "Time TBD" not in music
    assert "6:00 PM" in music
    assert "Add to calendar" not in music
    assert not list(output.glob("*.ics"))
    event = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', music).group(1))
    assert event["startDate"] == "2026-12-09T18:00:00-05:00"
    assert "endDate" not in event
    show = json.loads((SOURCE / "content.json").read_text())["music"]["upcoming_show"]
    assert set(show) == {"artist", "date", "date_display", "venue", "location", "description", "time", "start_iso"}
    assert 'data-share-show' in music
    assert '"@type": "MusicEvent"' in music
    assert 'content="https://humblechuck.com/og.png"' in music
    assert "A curated selection of shows I’ve played over the years" in music
    assert "not a complete list" in music
    assert "111 dated performances" not in music
    assert "master" not in music.lower()
    assert music.count('class="show-row"') == 111
    assert music.count('class="show-year"') == 12
    assert music.count('<span class="eyebrow">Artist</span>') == 111
    assert music.count('<span class="eyebrow">Venue</span>') == 111
    assert "Purgatory" in music
    assert "Purgagory" not in music
    assert "Brooklyn, NY" in music
    assert music.index('id="upcoming"') < music.index('class="playlist"')
    assert music.index('class="playlist"') < music.index('class="work"')
    assert music.index('class="work"') < music.index('class="show-archive"')
    assert music.index('class="show-archive"') < music.index('class="cross-link ')
    assert "schlinkertc@gmail.com" in contact
    assert 'href="mailto:schlinkertc@gmail.com"' in contact
    assert 'aria-current="page" href="/contact"' in contact
    assert "User-agent: *\nAllow: /" in robots
    assert "<loc>https://humblechuck.com/data</loc>" in sitemap
    assert "<loc>https://humblechuck.com/music</loc>" in sitemap


def test_content_has_valid_card_links():
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    cards = content["data"]["cards"] + content["music"]["cards"]
    html = render_cards(cards)
    assert html.count("<article") == 4
    assert all(escape(card["url"], quote=True) in html for card in cards)
    assert (
        "https://www.youtube.com/watch?v=yAkc_BCY258&amp;list=RDyAkc_BCY258&amp;start_radio=1"
        in html
    )


def test_music_show_archive_is_rendered_from_content():
    history = json.loads(
        (SOURCE / "show_history.json").read_text(encoding="utf-8")
    )["shows"]
    archive = render_past_shows(history)
    assert len(history) == 111
    assert archive.count('class="show-row"') == len(history)
    assert archive.count('class="show-year"') == 12
    assert "May" in archive
    assert "Pete’s Candy Store" in archive
    assert "Purgatory" in archive
    assert "Wilby" in archive
    assert show_artist_and_note("Humble Chuck — 9:30 PM") == (
        "Humble Chuck",
        "9:30 PM",
    )
    assert show_artist_and_note("With Clara Hannigan") == ("Clara Hannigan", "")


def test_missing_show_details_are_not_invented(tmp_path, monkeypatch):
    builder = import_module("site_builder.build")
    source = tmp_path / "site_src"
    shutil.copytree(SOURCE, source)
    content = json.loads((source / "content.json").read_text(encoding="utf-8"))
    show = content["music"]["upcoming_show"]
    for key in ("time", "start_iso", "end_iso", "address", "venue_url"):
        show.pop(key, None)
    show["description"] = "Humble Chuck at The Delancey on Wednesday, December 9, 2026. Lower East Side, NYC. Time TBD."
    (source / "content.json").write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(builder, "SOURCE", source)
    monkeypatch.setattr(builder, "OUTPUT", tmp_path / "dist")
    output = builder.build()
    music = (output / "music" / "index.html").read_text(encoding="utf-8")
    announcement = music.split('<section class="upcoming-show"', 1)[1].split("</section>", 1)[0]
    metadata = music.split("</head>", 1)[0]
    for text in (announcement, metadata):
        assert "The Delancey" in text
        assert "Wednesday, December 9, 2026" in text
        assert "Lower East Side" in text
        assert "Time TBD" in text
        for stale in ("Pete’s", "September", "Brooklyn", "709", "8 PM", "8:00", "music-show-og.png"):
            assert stale not in text
    assert '<span>DEC</span><strong>09</strong><small>2026</small>' in announcement
    assert '<time datetime="2026-12-09">' in announcement
    assert "The+Delancey%2C+Lower+East+Side%2C+NYC" in announcement
    assert "Venue calendar" not in announcement
    assert 'data-share-text="Humble Chuck at The Delancey — Wednesday, December 9, 2026. Time TBD. Lower East Side, NYC."' in announcement
    assert not list(output.glob("*.ics"))
    assert "$show_" not in music
    event = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', music).group(1))
    assert event["startDate"] == "2026-12-09"
    assert date.fromisoformat(event["startDate"]).strftime("%A") == "Wednesday"
    assert "endDate" not in event
    assert "offers" not in event
    assert event["location"] == {
        "@type": "MusicVenue",
        "name": "The Delancey",
        "address": "Lower East Side, NYC",
    }
    assert event["performer"] == {"@type": "MusicGroup", "name": "Humble Chuck"}


def test_confirmed_times_enable_calendar_without_old_venue_details(tmp_path, monkeypatch):
    builder = import_module("site_builder.build")
    source = tmp_path / "site_src"
    shutil.copytree(SOURCE, source)
    content = json.loads((source / "content.json").read_text(encoding="utf-8"))
    # Synthetic confirmed details exercise the existing timed-show path only.
    content["music"]["upcoming_show"].update({
        "time": "7:30 PM",
        "start_iso": "2026-12-09T19:30:00-05:00",
        "end_iso": "2026-12-09T20:30:00-05:00",
        "address": "Test address, New York, NY",
        "venue_url": "https://example.com/calendar",
    })
    (source / "content.json").write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(builder, "SOURCE", source)
    monkeypatch.setattr(builder, "OUTPUT", tmp_path / "dist")
    output = builder.build()
    calendar = (output / "humble-chuck-2026-12-09.ics").read_text(encoding="utf-8")
    music = (output / "music" / "index.html").read_text(encoding="utf-8")
    assert "SUMMARY:Humble Chuck at The Delancey" in calendar
    assert "DTSTART;TZID=America/New_York:20261209T193000" in calendar
    assert "DTEND;TZID=America/New_York:20261209T203000" in calendar
    assert "LOCATION:Test address\\, New York\\, NY" in calendar
    assert 'href="/humble-chuck-2026-12-09.ics"' in music
    assert 'href="https://example.com/calendar"' in music
    assert '"endDate": "2026-12-09T20:30:00-05:00"' in music
    assert '"address": "Test address, New York, NY"' in music
