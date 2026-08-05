import json
from html import escape
from pathlib import Path

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
        "humble-chuck-petes-2026-09-05.ics",
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
    assert "Saturday, September 5, 2026" in music
    assert "Pete’s Candy Store" in music
    assert 'href="/humble-chuck-petes-2026-09-05.ics"' in music
    assert 'data-share-show' in music
    assert '"@type": "MusicEvent"' in music
    assert 'content="https://humblechuck.com/music-show-og.png"' in music
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


def test_music_show_archive_and_calendar_are_rendered_from_content():
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

    build()
    calendar = (OUTPUT / "humble-chuck-petes-2026-09-05.ics").read_text(
        encoding="utf-8"
    )
    assert "SUMMARY:Humble Chuck at Pete’s Candy Store" in calendar
    assert "DTSTART;TZID=America/New_York:20260905T200000" in calendar
    assert "LOCATION:709 Lorimer Street\\, Brooklyn\\, NY 11211" in calendar
