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


def build() -> Path:
    content = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    template = Template((SOURCE / "index.html").read_text(encoding="utf-8"))
    html = template.substitute(
        name=escape(content["name"]),
        headline=escape(content["headline"]),
        introduction=escape(content["introduction"]),
        about=escape(content["about"]),
        email=escape(content["email"]),
        email_url=escape(f"mailto:{content['email']}", quote=True),
        cards=render_cards(content["cards"]),
    )

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    not_found = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Page not found — {escape(content['name'])}</title><link rel=\"stylesheet\" href=\"/styles.css\"></head>
<body><main id=\"main\"><section class=\"not-found\"><p class=\"eyebrow\">404</p><h1>That page wandered off.</h1><p><a href=\"/\">Head home</a></p></section></main></body></html>"""
    (OUTPUT / "404.html").write_text(not_found, encoding="utf-8")
    shutil.copy2(SOURCE / "styles.css", OUTPUT / "styles.css")
    shutil.copy2(SOURCE / "site.js", OUTPUT / "site.js")
    (OUTPUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://humblechuck.com/sitemap.xml\n",
        encoding="utf-8",
    )
    (OUTPUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://humblechuck.com/</loc></url></urlset>\n',
        encoding="utf-8",
    )
    return OUTPUT


if __name__ == "__main__":
    print(f"Built site in {build()}")
