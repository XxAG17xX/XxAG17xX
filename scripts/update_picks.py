#!/usr/bin/env python3
"""Rewrite the Daily Picks section of the profile README: four matching tiles a day.

    ANIME   AniList: a random title from the 100 most popular that pass the taste filter
    READ    AniList, same filter, rotating by date: manga, manhwa, manhua, light/web novel
    BOOK    a random line of scripts/books.txt (hand-picked), cover from Open Library
    QUOTE   ZenQuotes' quote of the day, drawn by this script as a neon card

Taste filter, for a 22-year-old engineer's profile that recruiters also read: scored at
least ~7/10 on AniList, at least one of the genres in COOL, nothing ecchi, adult,
romance-led, magical-girl, harem, fan-service or kids, and nothing in picks_skip.txt. Books are not filtered by an API at all: Open Library's
popular shelves are full of YA and explicit "dark romance", so the pool is a curated list.

Every tile has the same shape: a 180x260 image, a label, a title, one line of facts. The
quote has no picture of its own, so it is rendered to assets/daily/quote-<date>.svg in the
banner style; the date in the filename stops browsers showing yesterday's cached card.

Every choice is seeded by the date, so a re-run on the same day changes nothing and makes
no commit. Each tile fails on its own: a dead source drops that tile, not the section, and
if every source is down the section keeps yesterday's picks. All sources are keyless.

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
HERE = os.path.dirname(os.path.abspath(__file__))
BOOKS = os.path.join(HERE, "books.txt")
SKIP = os.path.join(HERE, "picks_skip.txt")
W, H = 180, 260  # every tile image is forced to this, so the row lines up

# AniList's genre_in means "has ALL of these", so "has ANY of these" is checked here instead
COOL = {"Action", "Sci-Fi", "Psychological", "Thriller", "Mystery", "Mecha", "Sports",
        "Adventure", "Supernatural"}
ANIME = {"type": "ANIME", "format": ["TV", "MOVIE", "ONA"], "score": 72}
READS = [
    ("MANGA", {"type": "MANGA", "country": "JP", "format": ["MANGA", "ONE_SHOT"], "score": 72}),
    ("MANHWA", {"type": "MANGA", "country": "KR", "format": ["MANGA", "ONE_SHOT"], "score": 70}),
    ("MANHUA", {"type": "MANGA", "country": "CN", "format": ["MANGA", "ONE_SHOT"], "score": 68}),
    ("NOVEL", {"type": "MANGA", "format": ["NOVEL"], "score": 72}),
]

QUERY = """query($page:Int,$type:MediaType,$country:CountryCode,$format:[MediaFormat],$score:Int){
Page(page:$page,perPage:50){media(type:$type,countryOfOrigin:$country,format_in:$format,
averageScore_greater:$score,genre_not_in:["Ecchi","Hentai","Romance","Mahou Shoujo"],
tag_not_in:["Harem","Reverse Harem","Fan Service","Kids"],
isAdult:false,sort:POPULARITY_DESC){siteUrl title{romaji english} coverImage{extraLarge}
averageScore genres episodes chapters startDate{year}}}}"""


def rng(day, what):
    return random.Random(f"{day.isoformat()}/{what}")


def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def top100(filters):
    """The 100 most popular titles for these filters that also have a COOL genre."""
    media = []
    for page in (1, 2):
        body = json.dumps({"query": QUERY, "variables": dict(filters, page=page)}).encode()
        req = urllib.request.Request("https://graphql.anilist.co", body, {
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            media += json.load(r)["data"]["Page"]["media"]
    skip = load_lines(SKIP)
    media = [m for m in media if COOL & set(m.get("genres") or []) and not skipped(m, skip)]
    if not media:
        raise ValueError(f"AniList returned nothing for {filters}")
    return media


def tile_from(m, label):
    facts = []
    if m.get("averageScore"):
        facts.append(f'⭐ {m["averageScore"] / 10:.1f}')
    if (m.get("startDate") or {}).get("year"):
        facts.append(str(m["startDate"]["year"]))
    if m.get("episodes"):
        facts.append(plural(m["episodes"], "ep"))
    elif m.get("chapters"):
        facts.append(plural(m["chapters"], "ch"))
    facts += [g for g in m["genres"] if g in COOL][:2]
    return {"img": m["coverImage"]["extraLarge"], "url": m["siteUrl"], "label": label,
            "title": m["title"].get("english") or m["title"]["romaji"], "facts": facts}


def pick_anime(day):
    return tile_from(rng(day, "anime").choice(top100(ANIME)), "\U0001F3AC ANIME")


def pick_read(day):
    kind, filters = READS[day.toordinal() % len(READS)]
    return tile_from(rng(day, "read").choice(top100(filters)), f"\U0001F4D6 {kind}")


def load_lines(path):
    """Non-blank, non-comment lines of a text file; missing file = empty list."""
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except FileNotFoundError:
        return []


def skipped(m, skip):
    names = " / ".join(filter(None, (m["title"].get("english"), m["title"].get("romaji")))).lower()
    return any(s.lower() in names for s in skip)


def load_books(path=BOOKS):
    return [tuple(x.strip() for x in row.split("|")) for row in load_lines(path)]


def pick_book(day):
    books = load_books()
    order = list(range(len(books)))
    rng(day, "book").shuffle(order)
    for i in order[:3]:  # a book Open Library has no cover for is skipped, not shown blank
        cat, title, author = books[i]
        q = urllib.parse.urlencode({"title": title, "author": author, "limit": 5,
                                    "fields": "key,title,cover_i,first_publish_year,ratings_average"})
        docs = get_json(f"https://openlibrary.org/search.json?{q}")["docs"]
        d = next((d for d in docs if d.get("cover_i")), None)
        if not d:
            print(f"no Open Library cover for {title!r}", file=sys.stderr)
            continue
        facts = [author]
        if d.get("first_publish_year"):
            facts.append(str(d["first_publish_year"]))
        if d.get("ratings_average"):
            facts.append(f'⭐ {d["ratings_average"] * 2:.1f}')  # out of 5 there, out of 10 like the others
        return {"img": f'https://covers.openlibrary.org/b/id/{d["cover_i"]}-L.jpg',
                "url": f'https://openlibrary.org{d["key"]}', "title": title, "facts": facts,
                "label": f"\U0001F4DA {cat}"}
    raise ValueError("no cover found for three books in a row")


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
    books = load_books()
    assert len(books) >= 100 and all(len(b) == 3 and all(b) for b in books), "books.txt malformed"
    m = {"siteUrl": "https://anilist.co/anime/1", "title": {"romaji": "R", "english": None},
         "coverImage": {"extraLarge": "https://s4.anilist.co/c.jpg"}, "averageScore": 85,
         "genres": ["Drama", "Action", "Sci-Fi", "Mystery"], "episodes": 1, "startDate": {"year": 2020}}
    t = tile_from(m, "X")
    cote = {"title": {"english": "Classroom of the Elite II", "romaji": "Youkoso Jitsuryoku"}}
    assert skipped(cote, ["classroom of the elite"]) and not skipped(m, ["classroom of the elite"])
    assert "Classroom of the Elite" in load_lines(SKIP)
    assert t["title"] == "R" and t["facts"] == ["⭐ 8.5", "2020", "1 ep", "Action", "Sci-Fi"]
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
