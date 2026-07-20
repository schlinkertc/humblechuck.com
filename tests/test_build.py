import json
from pathlib import Path

from site_builder.build import OUTPUT, SOURCE, build, render_cards


def test_build_creates_deployable_site():
    output = build()
    expected = {
        "index.html",
        "404.html",
        "styles.css",
        "site.js",
        "og.png",
        "robots.txt",
        "sitemap.xml",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    index = (OUTPUT / "index.html").read_text(encoding="utf-8")
    data = (OUTPUT / "data" / "index.html").read_text(encoding="utf-8")
    music = (OUTPUT / "music" / "index.html").read_text(encoding="utf-8")
    assert "Charlie Schlinkert" in index
    assert "$headline" not in index
    assert 'id="main"' in index
    assert 'href="/data"' in index
    assert 'href="/music"' in index
    assert "Useful systems for messy questions." in data
    assert "Music is a present-tense practice." in music
    assert "something I used to do" not in music


def test_content_has_valid_card_links():
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    cards = content["data"]["cards"] + content["music"]["cards"]
    html = render_cards(cards)
    assert html.count("<article") == 4
    assert all(card["url"] in html for card in cards)
