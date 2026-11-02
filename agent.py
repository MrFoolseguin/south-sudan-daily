"""
Daily South Sudan briefing agent.
Free stack: RSS feeds + Gemini API free tier + GitHub Actions + GitHub Pages.

What it does each run:
  1. Pulls the last ~3 days of headlines from local, regional and international sources
  2. Sends them (plus your prompt.txt) to Gemini in ONE request
  3. Writes the briefing to docs/index.html and docs/archive/YYYY-MM-DD.html
"""
import os
import re
import sys
import time
import glob
import html
import datetime as dt
from urllib.parse import quote

import requests
import feedparser
import markdown

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    sys.exit("GEMINI_API_KEY is missing. Add it as a repository secret.")

# The script tries these in order and uses the first one that works.
# Google renames and retires models, so this list is the thing you edit if one stops working.
MODELS = [m for m in [os.environ.get("GEMINI_MODEL")] if m] + [
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

UA = "Mozilla/5.0 (compatible; SouthSudanBriefing/1.0)"
NOW = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
CUTOFF = NOW - dt.timedelta(days=3)
TODAY = NOW.strftime("%Y-%m-%d")


def gnews(query):
    """Google News RSS search: one of the most reliable free feeds there is."""
    q = quote(query + " when:3d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# (label, tier, url). Local sources first. If a feed fails it is skipped and
# listed at the bottom of the page so you know which one to fix or replace.
FEEDS = [
    ("Sudans Post", "local", "https://www.sudanspost.com/feed/"),
    ("Eye Radio", "local", "https://www.eyeradio.org/feed/"),
    ("Radio Tamazuj", "local", "https://www.radiotamazuj.org/en/rss.xml"),
    ("Sudan Tribune", "regional", "https://sudantribune.com/feed/"),
    ("Google News: South Sudan", "aggregator", gnews("South Sudan")),
    ("Google News: economy", "aggregator", gnews("South Sudan economy OR inflation OR salaries OR oil")),
    ("Google News: exchange rate", "aggregator", gnews("South Sudanese pound dollar exchange rate")),
    ("Google News: land", "aggregator", gnews("South Sudan land OR property OR investment")),
    ("Google News: US relations", "aggregator", gnews("South Sudan United States visa OR sanctions OR ban")),
    ("Google News: neighbors", "aggregator", gnews("South Sudan Uganda OR Kenya OR Ethiopia OR Sudan trade OR border")),
    ("Dinka / Jonglei / Bor", "aggregator", gnews("Dinka OR Bor OR Jonglei OR Awiel OR Rumbek OR Aweil")),
    ("BBC Africa", "international", "https://feeds.bbci.co.uk/news/world/africa/rss.xml"),
]


def fetch(label, tier, url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries[:15]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t and dt.datetime(*t[:6]) < CUTOFF:
            continue
        title = (e.get("title") or "").strip()
        if not title:
            continue
        summary = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
        summary = " ".join(html.unescape(summary).split())[:300]
        items.append({"source": label, "tier": tier, "title": title,
                      "summary": summary, "link": e.get("link", "")})
    return items


def collect():
    items, failed, seen = [], [], set()
    for label, tier, url in FEEDS:
        try:
            got = fetch(label, tier, url)
            print(f"OK    {label}: {len(got)} items")
        except Exception as ex:
            print(f"FAIL  {label}: {ex}")
            failed.append(label)
            continue
        for it in got:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
    return items[:160], failed


def ask(system, user):
    last = None
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.4},
        }
        for attempt in range(4):
            r = requests.post(
                url,
                headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
                json=body,
                timeout=240,
            )
            if r.status_code == 200:
                data = r.json()
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts).strip()
                    if text:
                        print(f"Model used: {model}")
                        return model, text
                    last = f"{model}: empty text"
                except (KeyError, IndexError):
                    last = f"{model}: unexpected response {str(data)[:300]}"
                break
            if r.status_code in (429, 500, 503):
                last = f"{model}: HTTP {r.status_code}"
                print(f"{last}, waiting before retry")
                time.sleep(30 * (attempt + 1))
                continue
            last = f"{model}: HTTP {r.status_code} {r.text[:300]}"
            print(last)
            break
    sys.exit(f"All models failed. Last error: {last}")


CSS = """
:root{--bg:#fafaf7;--fg:#1c1c1a;--mut:#6b6b66;--card:#fff;--line:#e4e2da;--acc:#9a3412}
@media(prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ecebe6;--mut:#9a9990;--card:#1c1c1a;--line:#2e2d29;--acc:#fb923c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 Georgia,'Times New Roman',serif}
main{max-width:720px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:1.7rem;line-height:1.25;margin:.2em 0}
h2{font-size:1.2rem;margin:2em 0 .4em;padding-top:.8em;border-top:1px solid var(--line);color:var(--acc)}
h3{font-size:1.05rem;margin:1.2em 0 .2em}
p,li{margin:.5em 0}
a{color:var(--acc)}
.meta{color:var(--mut);font-size:.9rem}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:2em;font-size:.9rem}
summary{cursor:pointer;font-weight:bold}
.warn{color:var(--mut);font-size:.85rem}
nav a{margin-right:14px;font-size:.9rem}
"""


def page(title, body, extra=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><main>
<nav><a href="{{ROOT}}index.html">Latest</a><a href="{{ROOT}}archive.html">Past briefings</a></nav>
{body}{extra}
</main></body></html>"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "prompt.txt"), encoding="utf-8") as f:
        system = f.read()

    items, failed = collect()
    if len(items) < 5:
        sys.exit(f"Only {len(items)} headlines collected. Not writing a briefing from that.")

    lines = [f"[{i['tier']}] {i['source']} | {i['title']}"
             + (f" - {i['summary']}" if i["summary"] and i["summary"] != i["title"] else "")
             for i in items]
    user = (
        f"Today is {TODAY}. Below are {len(items)} headlines from the last 3 days. "
        "Each line starts with the source tier (local, regional, aggregator, international). "
        "Write today's briefing using ONLY this material plus the stable background knowledge "
        "your instructions allow.\n\n" + "\n".join(lines)
    )

    model, text = ask(system, user)
    body_html = markdown.markdown(text, extensions=["extra", "sane_lists"])

    srcs = "".join(
        f'<li><a href="{html.escape(i["link"])}">{html.escape(i["title"])}</a> '
        f'<span class="meta">({html.escape(i["source"])})</span></li>'
        for i in items if i["link"]
    )
    extra = f'<details><summary>Headlines this briefing was built from ({len(items)})</summary><ul>{srcs}</ul></details>'
    notes = f"Generated {TODAY} with {model}."
    if failed:
        notes += " Sources that did not load: " + ", ".join(failed) + "."
    extra += f'<p class="warn">{html.escape(notes)} AI-written summary: check anything important at the original source.</p>'

    os.makedirs("docs/archive", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page(f"Briefing {TODAY}", body_html, extra).replace("{ROOT}", ""))
    with open(f"docs/archive/{TODAY}.html", "w", encoding="utf-8") as f:
        f.write(page(f"Briefing {TODAY}", body_html, extra).replace("{ROOT}", "../"))

    days = sorted((os.path.basename(p)[:-5] for p in glob.glob("docs/archive/*.html")), reverse=True)
    lis = "".join(f'<li><a href="archive/{d}.html">{d}</a></li>' for d in days)
    with open("docs/archive.html", "w", encoding="utf-8") as f:
        f.write(page("Past briefings", f"<h1>Past briefings</h1><ul>{lis}</ul>").replace("{ROOT}", ""))
    print("Done.")


if __name__ == "__main__":
    main()
