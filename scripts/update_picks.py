#!/usr/bin/env python3
"""Rewrite the Daily Picks section of the profile README: four matching tiles a day.

    ANIME   AniList: a random title from the 100 most popular that pass the taste filter
    READ    AniList, same filter, rotating by date: manga, manhwa, manhua, light/web novel
    BOOK    a random line of scripts/books.txt (hand-picked), cover from Open Library
    QUOTE   a line of scripts/quotes.txt (hand-picked), drawn by this script as a card
            whose look rotates daily through six calm themes (THEMES)

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
Books and quotes walk their lists in a shuffled order, so neither repeats until the list
has gone all the way round.

Local checks, write nothing:
    python update_picks.py --self-check
    python update_picks.py --dry-run
"""

import argparse
import datetime
import glob
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
QUOTES = os.path.join(HERE, "quotes.txt")
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
    for i in cycle(books, day, "books")[:3]:  # a book Open Library has no cover for is skipped, not shown blank
        cat, title, author = books[i]
        q = urllib.parse.urlencode({"title": title, "author": author, "limit": 5,
                                    "fields": "key,title,cover_i,first_publish_year,ratings_average"})
        for attempt in range(3):  # Open Library is slow and drops the odd request; retry it
            try:
                docs = get_json(f"https://openlibrary.org/search.json?{q}")["docs"]
                break
            except OSError as e:
                print(f"Open Library attempt {attempt + 1} failed: {e}", file=sys.stderr)
                if attempt == 2:
                    raise
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


def _stars(seed, n=40):
    r = random.Random(seed)
    return "".join(f'<circle cx="{r.uniform(15, 345):.0f}" cy="{r.uniform(15, 505):.0f}" r="{r.choice([0.6, 0.9, 1.3])}" '
                   f'fill="#dfe8ff" opacity="{r.uniform(0.15, 0.55):.2f}"/>' for _ in range(n))


def _bamboo():
    out = []
    for x, h, o in ((34, 520, 0.10), (58, 460, 0.07), (318, 520, 0.09), (296, 430, 0.06)):
        out.append(f'<rect x="{x}" y="{520 - h}" width="7" height="{h}" rx="3" fill="#8fbf9f" opacity="{o}"/>')
        out += [f'<rect x="{x - 1}" y="{y}" width="9" height="2" fill="#8fbf9f" opacity="{o + 0.05:.2f}"/>'
                for y in range(520 - h + 60, 520, 90)]
    return "".join(out)


def _waves():
    arcs = []
    for row, y in enumerate(range(400, 560, 22)):
        for x in range(-20 + (row % 2) * 22, 400, 44):
            arcs += [f'<path d="M{x - rr},{y} a{rr},{rr} 0 0 1 {2 * rr},0" fill="none" stroke="#9fc4d6" '
                     f'stroke-width="1.2" opacity="0.13"/>' for rr in (20, 14, 8)]
    return "".join(arcs)


# Six calm looks, one per day in turn. Each: background top/bottom, quote text, accent,
# name line, work line, and a motif drawn behind the words (given the text's centre y).
THEMES = [
    ("ink", "#16171d", "#211d24", "#ece6da", "#c9a96e", "#d8d2c4", "#9c968a",
     lambda cy: f'<circle cx="180" cy="{cy}" r="132" fill="none" stroke="#c9a96e" stroke-width="14" stroke-linecap="round" '
                f'stroke-dasharray="760 70" transform="rotate(-70 180 {cy})" opacity="0.09"/>'),
    ("midnight", "#0b1224", "#17203a", "#e6ecf7", "#9db4d8", "#cfd8ea", "#8793ab",
     lambda cy: _stars(7) + '<circle cx="282" cy="78" r="30" fill="#e8eefc" opacity="0.85"/>'
                            '<circle cx="294" cy="70" r="27" fill="#0f1830"/>'),
    ("dusk", "#2a1c2e", "#4a2a38", "#f6e9dc", "#e7b98f", "#f0dccb", "#b89a92",
     lambda cy: '<circle cx="180" cy="560" r="150" fill="#e7b98f" opacity="0.13"/>'
                '<circle cx="180" cy="560" r="105" fill="#f0c9a0" opacity="0.12"/>'),
    ("washi", "#f1ebdf", "#e6ddcd", "#2b2724", "#b0413e", "#3a3431", "#7d746b",
     lambda cy: '<rect x="296" y="428" width="38" height="38" rx="4" fill="none" stroke="#b0413e" stroke-width="3" opacity="0.8"/>'
                '<text x="315" y="455" text-anchor="middle" font-family="\'Yu Mincho\', \'MS Mincho\', serif" font-size="22" fill="#b0413e" opacity="0.85">言</text>'),
    ("bamboo", "#0f1f1a", "#18302a", "#e8f0ea", "#8fbf9f", "#d3e2d7", "#8aa596",
     lambda cy: _bamboo()),
    ("tide", "#132028", "#1d3440", "#e6f0f4", "#9fc4d6", "#d0e2ea", "#88a3b0",
     lambda cy: _waves()),
]


def theme_for(day):
    return THEMES[day.toordinal() % len(THEMES)]


def quote_svg(text, who, work, theme=THEMES[0]):
    """A 360x520 card (shown at 180x260). Deliberately NOT neon: calm, so the words carry
    it. The look rotates daily through THEMES; the layout is the same in all of them."""
    _, top, bottom, ink, accent, name, sub, motif = theme
    n = len(text)
    size = 32 if n <= 50 else 27 if n <= 100 else 24 if n <= 150 else 21
    lines = textwrap.wrap(text, width=int(520 / size))
    lh = size * 1.35
    y0 = 240 - lh * (len(lines) - 1) / 2
    yend = y0 + lh * (len(lines) - 1)
    cy = round((y0 + yend) / 2)
    tspans = "".join(f'<tspan x="180" y="{y0 + i * lh:.0f}">{esc(l)}</tspan>' for i, l in enumerate(lines))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="360" height="520" viewBox="0 0 360 520">
<defs><linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
<filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.06 0"/></filter>
<clipPath id="card"><rect width="360" height="520" rx="18"/></clipPath></defs>
<g clip-path="url(#card)">
<rect width="360" height="520" fill="url(#bg)"/>
{motif(cy)}
<text x="180" y="{y0 - size - 34:.0f}" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="64" fill="{accent}" opacity="0.6">“</text>
<text text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-style="italic" font-size="{size}" fill="{ink}">{tspans}</text>
<rect x="160" y="{yend + 30:.0f}" width="40" height="1.5" fill="{accent}" opacity="0.8"/>
<text x="180" y="{yend + 60:.0f}" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="14" letter-spacing="3" fill="{name}">{esc(who.upper())}</text>
<text x="180" y="{yend + 82:.0f}" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-style="italic" font-size="14" fill="{sub}">{esc(work)}</text>
<text x="180" y="492" text-anchor="middle" font-family="'Yu Gothic', 'Meiryo', 'Hiragino Sans', sans-serif" font-size="12" letter-spacing="6" fill="{sub}">今日の言葉</text>
<rect x="10" y="10" width="340" height="500" rx="12" fill="none" stroke="{ink}" stroke-opacity="0.07"/>
<rect width="360" height="520" filter="url(#grain)"/>
</g>
</svg>
"""


def cycle(items, day, salt):
    """items[k] for today, walking a fixed shuffled order one step per day, so nothing
    repeats until the whole list has been shown (a plain daily random pick would)."""
    order = list(range(len(items)))
    random.Random(salt).shuffle(order)
    return order[day.toordinal() % len(items):] + order[:day.toordinal() % len(items)]


def load_quotes(path=QUOTES):
    return [tuple(x.strip() for x in row.split("|")) for row in load_lines(path)]


def pick_quote(day):
    text, who, work = load_quotes()[cycle(load_quotes(), day, "quotes")[0]]
    img = f"{DAILY_DIR}/quote-{day.isoformat()}.svg"
    return {"svg": quote_svg(text, who, work, theme_for(day)), "img": img, "url": img,
            "title": who, "facts": [work], "label": "\U0001F4AC QUOTE",
            "alt": f"“{text}” — {who}, {work}"}


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

    svg = quote_svg('Be "bold" & <kind>' + " word" * 30, "Someone", "A Work")
    assert "&quot;bold&quot; &amp; &lt;kind&gt;" in svg and "SOMEONE" in svg and "A Work" in svg
    assert svg.count("<tspan") > 3 and "#ff2bd6" not in svg  # the calm card, not the neon one
    looks = {theme_for(d + datetime.timedelta(i))[0] for i in range(len(THEMES))}
    assert len(looks) == len(THEMES)  # every look turns up within one lap of days
    for t in THEMES:
        assert "<svg" in quote_svg("Arise.", "Sung Jinwoo", "Solo Leveling", t)
    quotes = load_quotes()
    assert len(quotes) >= 40 and all(len(q) == 3 and all(q) and len(q[0].split()) <= 40 for q in quotes)
    seen = {cycle(quotes, d + datetime.timedelta(i), "quotes")[0] for i in range(len(quotes))}
    assert len(seen) == len(quotes)  # a full lap shows every quote exactly once

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
