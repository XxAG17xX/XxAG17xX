#!/usr/bin/env python3
"""Rewrite the Daily Picks section of the profile README: four matching tiles a day.

    ANIME   AniList, drawn from the most popular 500 (TV, movie, ONA)
    READ    AniList, rotating by date: manga, manhwa, manhua, light/web novel
    BOOK    Open Library, English, drawn from the most-read in a rotating genre
    QUOTE   ZenQuotes' quote of the day, drawn by this script as a neon card

Every tile has the same shape: a 180x260 image, a label, a title, one line of facts. The
quote has no picture of its own, so it is rendered to assets/daily/quote-<date>.svg in the
banner style; the date in the filename stops browsers showing yesterday's cached card.

Every choice is seeded by the date, so a re-run on the same day changes nothing and makes
no commit. Each tile fails on its own: a dead source drops that tile, not the section, and
if every source is down the section keeps yesterday's picks. All sources are keyless.
Adult and ecchi titles are filtered out: this is a profile page recruiters read.

Local checks, write nothing:
    python update_picks.py --self-check
    python update_picks.py --dry-run
"""

import argparse
import datetime
import glob
import html
import json
import os
import random
import sys
import textwrap
import urllib.parse
import urllib.request

from update_space import TIMEOUT, UA, esc, get_json, guard, splice, trim

START = "<!-- PICKS:START -->"
END = "<!-- PICKS:END -->"
DAILY_DIR = "assets/daily"
W, H = 180, 260  # every tile image is forced to this, so the row lines up

READS = [
    ("MANGA", {"country": "JP", "format": ["MANGA", "ONE_SHOT"]}, 400),
    ("MANHWA", {"country": "KR", "format": ["MANGA", "ONE_SHOT"]}, 250),
    ("MANHUA", {"country": "CN", "format": ["MANGA", "ONE_SHOT"]}, 150),
    ("NOVEL", {"format": ["NOVEL"]}, 300),
]
BOOK_GENRES = ["science_fiction", "fantasy", "mystery", "thriller", "horror", "historical_fiction"]

QUERY = """query($page:Int,$type:MediaType,$country:CountryCode,$format:[MediaFormat]){
Page(page:$page,perPage:1){media(type:$type,countryOfOrigin:$country,format_in:$format,
isAdult:false,genre_not_in:["Ecchi","Hentai"],sort:POPULARITY_DESC){siteUrl
title{romaji english} coverImage{extraLarge} averageScore genres episodes chapters startDate{year}}}}"""


def rng(day, what):
    return random.Random(f"{day.isoformat()}/{what}")


def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def anilist(variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", body, {
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        media = json.load(r)["data"]["Page"]["media"]
    if not media:
        raise ValueError(f"AniList returned nothing for {variables}")
    m = media[0]
    facts = []
    if m.get("averageScore"):
        facts.append(f'⭐ {m["averageScore"] / 10:.1f}')
    if (m.get("startDate") or {}).get("year"):
        facts.append(str(m["startDate"]["year"]))
    if m.get("episodes"):
        facts.append(plural(m["episodes"], "ep"))
    elif m.get("chapters"):
        facts.append(plural(m["chapters"], "ch"))
    facts += (m.get("genres") or [])[:2]
    return {"img": m["coverImage"]["extraLarge"], "url": m["siteUrl"],
            "title": m["title"].get("english") or m["title"]["romaji"], "facts": facts}


def pick_anime(day):
    page = rng(day, "anime").randint(1, 500)
    return dict(anilist({"page": page, "type": "ANIME", "format": ["TV", "MOVIE", "ONA"]}),
                label="\U0001F3AC ANIME")


def pick_read(day):
    kind, filters, pool = READS[day.toordinal() % len(READS)]
    page = rng(day, "read").randint(1, pool)
    return dict(anilist(dict(filters, page=page, type="MANGA")), label=f"\U0001F4D6 {kind}")


def latin(s):
    # Open Library files some works under their original title (e.g. 三体); skip those
    return all(ord(c) < 0x250 or not c.isalpha() for c in s)


def pick_book(day):
    r = rng(day, "book")
    genre = BOOK_GENRES[day.toordinal() % len(BOOK_GENRES)]
    q = urllib.parse.urlencode({
        "q": f"subject_key:{genre}", "language": "eng", "sort": "readinglog", "limit": 20,
        "offset": r.randint(0, 200), "fields": "title,author_name,cover_i,first_publish_year,key,ratings_average"})
    for attempt in range(2):  # Open Library drops the odd connection; one retry covers it
        try:
            docs = get_json(f"https://openlibrary.org/search.json?{q}")["docs"]
            break
        except OSError:
            if attempt:
                raise
    docs = [d for d in docs if d.get("cover_i") and latin(d["title"])]
    if not docs:
        raise ValueError(f"no usable book in {genre}")
    d = r.choice(docs)
    facts = [d["author_name"][0]] if d.get("author_name") else []
    if d.get("first_publish_year"):
        facts.append(str(d["first_publish_year"]))
    if d.get("ratings_average"):
        facts.append(f'⭐ {d["ratings_average"] * 2:.1f}')  # out of 5 there, out of 10 like the others
    return {"img": f'https://covers.openlibrary.org/b/id/{d["cover_i"]}-L.jpg',
            "url": f'https://openlibrary.org{d["key"]}', "title": d["title"], "facts": facts,
            "label": "\U0001F4DA " + genre.replace("_", " ").upper()}


def quote_svg(text, author):
    """A 360x520 neon card (shown at 180x260), same look as the banners."""
    n = len(text)
    size = 30 if n <= 70 else 25 if n <= 120 else 21 if n <= 180 else 18
    lines = textwrap.wrap(text, width=int(560 / size))
    lh = size * 1.3
    y0 = 250 - lh * (len(lines) - 1) / 2
    tspans = "".join(f'<tspan x="180" y="{y0 + i * lh:.0f}">{esc(l)}</tspan>' for i, l in enumerate(lines))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="360" height="520" viewBox="0 0 360 520">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b0322"/><stop offset="1" stop-color="#2a0838"/></linearGradient>
<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#000" opacity="0.3"/></pattern></defs>
<rect width="360" height="520" rx="18" fill="url(#bg)"/>
<text x="40" y="150" font-family="Georgia, serif" font-size="180" fill="#ff2bd6" opacity="0.18">“</text>
<text text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="{size}" font-weight="600" fill="#f4f7ff">{tspans}</text>
<rect x="150" y="{y0 + lh * (len(lines) - 1) + 30:.0f}" width="60" height="3" fill="#7df9ff" filter="url(#glow)"/>
<text x="180" y="{y0 + lh * (len(lines) - 1) + 66:.0f}" text-anchor="middle" font-family="Consolas, 'Courier New', monospace" font-size="17" letter-spacing="2" fill="#7df9ff">{esc(author.upper())}</text>
<text x="180" y="490" text-anchor="middle" font-family="'Yu Gothic', 'Meiryo', sans-serif" font-size="14" letter-spacing="8" fill="#ff4fd8" opacity="0.8">今日の言葉</text>
<rect width="360" height="520" rx="18" fill="url(#scan)"/>
<g stroke="#7df9ff" stroke-width="2.5" fill="none" opacity="0.8"><path d="M14,40 V14 H40"/><path d="M320,14 H346 V40"/><path d="M14,480 V506 H40"/><path d="M320,506 H346 V480"/></g>
</svg>
'''


def pick_quote(day):
    q = get_json("https://zenquotes.io/api/today")[0]
    text, author = html.unescape(q["q"]).strip(), html.unescape(q["a"]).strip()
    if not text or "too many requests" in text.lower():
        raise ValueError(f"ZenQuotes gave no quote: {text!r}")
    return {"svg": quote_svg(text, author), "img": f"{DAILY_DIR}/quote-{day.isoformat()}.svg",
            "url": "https://zenquotes.io/", "title": author, "facts": ["via ZenQuotes"],
            "label": "\U0001F4AC QUOTE", "alt": f"“{text}” — {author}"}


def tile(p):
    url = guard(p["url"])
    return (
        '<td width="25%" valign="top" align="center">\n'
        f'<a href="{url}"><img src="{guard(p["img"])}" alt="{esc(p.get("alt", p["title"]))}" width="{W}" height="{H}" /></a>\n'
        f'<br/><sub><b>{p["label"]}</b></sub>\n'
        # trimmed so one long title does not make its tile taller than the other three
        f'<br/><b><a href="{url}">{esc(trim(p["title"], 42))}</a></b>\n'
        f'<br/><sub>{esc(" · ".join(p["facts"]))}</sub>\n'
        "</td>"
    )


def render(picks):
    return "<table>\n<tr>\n" + "\n".join(tile(p) for p in picks) + "\n</tr>\n</table>"


def build(day):
    picks = []
    for fn in (pick_anime, pick_read, pick_book, pick_quote):
        try:
            picks.append(fn(day))
        except Exception as e:                  # noqa: BLE001
            print(f"picks source unavailable ({fn.__name__}): {e}", file=sys.stderr)
    return picks


def _self_check():
    d = datetime.date(2026, 9, 21)
    assert rng(d, "a").random() == rng(d, "a").random() != rng(d, "b").random()
    assert len({READS[(d.toordinal() + i) % len(READS)][0] for i in range(4)}) == 4
    assert latin("The Martian") and latin("Don Quijote de la Mancha") and not latin("三体")
    assert plural(1, "ep") == "1 ep" and plural(12, "ch") == "12 chs"

    svg = quote_svg('Be "bold" & <kind>' + " word" * 40, "Someone")
    assert "&quot;bold&quot; &amp; &lt;kind&gt;" in svg and "SOMEONE" in svg and svg.count("<tspan") > 3

    p = {"img": "https://s4.anilist.co/c.jpg", "url": "https://anilist.co/anime/1", "title": 'A "B"',
         "facts": ["⭐ 8.1", "2009"], "label": "\U0001F3AC ANIME"}
    out = render([p, dict(p, img="assets/daily/quote-2026-09-21.svg", alt="“q”")])
    assert out.count("<td") == 2 and out.count(f'width="{W}" height="{H}"') == 2
    assert "A &quot;B&quot;" in out and "api_key" not in out
    try:
        tile(dict(p, img="https://x.com/c.jpg?api_key=1"))
    except ValueError:
        pass
    else:
        raise AssertionError("tile let a key through")

    body = f"a\n{START}\nold\n{END}\nb"
    assert splice(body, "new", START, END) == f"a\n{START}\nnew\n{END}\nb"
    print("self-check passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args()
    if a.self_check:
        _self_check()
        return

    day = datetime.date.today()
    picks = build(day)
    if not picks:
        print("every picks source failed; keeping yesterday's section", file=sys.stderr)
        return
    block = render(picks)
    if a.dry_run:
        print(block)
        return

    quote = next((p for p in picks if "svg" in p), None)
    if quote:
        # only today's card is kept; the old ones are dead links once the README moves on
        for old in glob.glob(f"{DAILY_DIR}/quote-*.svg"):
            if os.path.basename(old) != os.path.basename(quote["img"]):
                os.remove(old)
        os.makedirs(DAILY_DIR, exist_ok=True)
        with open(quote["img"], "w", encoding="utf-8", newline="\n") as f:
            f.write(quote["svg"])

    with open(a.readme, encoding="utf-8") as f:
        old = f.read()
    new = splice(old, block, START, END)
    if new == old:
        print("no change")
        return
    with open(a.readme, "w", encoding="utf-8") as f:
        f.write(new)
    print("README updated")


if __name__ == "__main__":
    main()
