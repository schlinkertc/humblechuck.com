import json
from pathlib import Path

from site_builder.build import OUTPUT, SOURCE, build, render_cards


def test_build_creates_deployable_site():
    output = build()
    expected = {"index.html", "404.html", "styles.css", "site.js", "robots.txt", "sitemap.xml"}
    assert expected.issubset({path.name for path in output.iterdir()})
    index = (OUTPUT / "index.html").read_text(encoding="utf-8")
    assert "Charlie Schlinkert" in index
    assert "$headline" not in index
    assert 'id="main"' in index


def test_content_has_valid_card_links():
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    html = render_cards(content["cards"])
    assert html.count("<article") == 3
    assert all(card["url"] in html for card in content["cards"])

