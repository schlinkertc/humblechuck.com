import json
from pathlib import Path

from site_builder.build import OUTPUT, SOURCE, build, render_cards, render_past_shows


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
    assert "Charlie Schlinkert" in index
    assert "$headline" not in index
    assert 'id="main"' in index
    assert 'href="/data"' in index
    assert 'href="/music"' in index
    assert 'href="/contact"' in index
    assert 'href="/favicon.ico"' in index
    assert 'src="/hc-logo.png"' in index
    assert "Useful systems for messy questions." in data
    assert "Music is a present-tense practice." in music
    assert "something I used to do" not in music
    assert "Songs I’ve" in music
    assert "open.spotify.com/embed/playlist/4XeFzR948Yyk1X4SsXXogr" in music
    assert 'title="Spotify playlist: Songs Charlie Schlinkert has played on"' in music
    assert 'id="upcoming"' in music
    assert "Humble Chuck" in music
    assert "Saturday, September 5, 2026" in music
    assert "Pete’s Candy Store" in music
    assert 'href="/humble-chuck-petes-2026-09-05.ics"' in music
    assert 'data-share-show' in music
    assert '"@type": "MusicEvent"' in music
    assert 'content="https://humblechuck.com/music-show-og.png"' in music
    assert "Recent history" in music
    assert music.count('class="show-row"') == 10
    assert "schlinkertc@gmail.com" in contact
    assert 'href="mailto:schlinkertc@gmail.com"' in contact
    assert 'aria-current="page" href="/contact"' in contact


def test_content_has_valid_card_links():
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    cards = content["data"]["cards"] + content["music"]["cards"]
    html = render_cards(cards)
    assert html.count("<article") == 4
    assert all(card["url"] in html for card in cards)


def test_music_show_archive_and_calendar_are_rendered_from_content():
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    music = content["music"]
    archive = render_past_shows(music["past_shows"])
    assert archive.count('class="show-row"') == len(music["past_shows"])
    assert "May" in archive
    assert "Pete’s Candy Store" in archive

    build()
    calendar = (OUTPUT / "humble-chuck-petes-2026-09-05.ics").read_text(
        encoding="utf-8"
    )
    assert "SUMMARY:Humble Chuck at Pete’s Candy Store" in calendar
    assert "DTSTART;TZID=America/New_York:20260905T200000" in calendar
    assert "LOCATION:709 Lorimer Street\\, Brooklyn\\, NY 11211" in calendar
