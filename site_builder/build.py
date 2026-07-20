import json
import shutil
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
    music = render_template(
        "music.html",
        {
            **shared,
            "headline": escape(content["music"]["headline"]),
            "introduction": escape(content["music"]["introduction"]),
            "about": escape(content["music"]["about"]),
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
