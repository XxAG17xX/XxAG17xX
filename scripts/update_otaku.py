#!/usr/bin/env python3
"""Rewrite the otaku section of the profile README: one random pick a day from AniList.

The kind rotates by date (anime, manga, manhwa, manhua, web/light novel) and the title is
drawn at random from that kind's most popular few hundred on AniList, so it is always
something people actually read or watch. Adult and ecchi titles are filtered out: this is
a profile page recruiters read. The choice is seeded by the date: re-running on
the same day picks the same title, so a manual re-run never produces a second commit.

AniList's GraphQL API is public and keyless, so nothing secret ever touches this script.
If AniList is down the section is left as it was (yesterday's pick) rather than blanked.

Local checks, write nothing:
    python update_otaku.py --self-check
    python update_otaku.py --dry-run
"""

import argparse
import datetime
import html
import json
import random
import re
import sys
import urllib.request

from update_space import TIMEOUT, UA, esc, guard, splice, trim

START = "<!-- OTAKU:START -->"
END = "<!-- OTAKU:END -->"

# (label, AniList filters, how many of the most popular to draw from)
KINDS = [
    ("ANIME", {"type": "ANIME", "format": ["TV", "MOVIE", "ONA"]}, 500),
    ("MANGA", {"type": "MANGA", "country": "JP", "format": ["MANGA", "ONE_SHOT"]}, 400),
    ("MANHWA", {"type": "MANGA", "country": "KR", "format": ["MANGA", "ONE_SHOT"]}, 250),
    ("MANHUA", {"type": "MANGA", "country": "CN", "format": ["MANGA", "ONE_SHOT"]}, 150),
    ("NOVEL", {"type": "MANGA", "format": ["NOVEL"]}, 300),
]

QUERY = """query($page:Int,$type:MediaType,$country:CountryCode,$format:[MediaFormat]){
Page(page:$page,perPage:1){media(type:$type,countryOfOrigin:$country,format_in:$format,
isAdult:false,genre_not_in:["Ecchi","Hentai"],sort:POPULARITY_DESC){siteUrl countryOfOrigin title{romaji english native}
coverImage{extraLarge} averageScore genres episodes chapters startDate{year}
description(asHtml:false)}}}"""


def choose(day):
    """(label, filters, page) for a date; same date, same answer."""
    label, filters, pool = KINDS[day.toordinal() % len(KINDS)]
    return label, filters, random.Random(day.isoformat()).randint(1, pool)


def fetch(filters, page):
    body = json.dumps({"query": QUERY, "variables": dict(filters, page=page)}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", body, {
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        media = json.load(r)["data"]["Page"]["media"]
    if not media:
        raise ValueError(f"AniList returned nothing for page {page}")
    return media[0]


def clean(desc):
    """AniList descriptions carry <br>/<i> tags and ~!spoiler!~ blocks; drop both."""
    desc = re.sub(r"~!.*?!~", "", desc or "", flags=re.S)
    return trim(html.unescape(re.sub(r"<[^>]+>", " ", desc)), 260)


def render(label, m):
    t = m["title"]
    name = t.get("english") or t["romaji"]
    alt = t["romaji"] if t.get("english") and t["romaji"] != t["english"] else ""
    url = guard(m["siteUrl"])
    facts = []
    if m.get("averageScore"):
        facts.append(f'⭐ <b>{m["averageScore"] / 10:.1f}</b>/10')
    if (m.get("startDate") or {}).get("year"):
        facts.append(str(m["startDate"]["year"]))
    if m.get("episodes"):
        facts.append(f'{m["episodes"]} episode{"s" * (m["episodes"] != 1)}')
    elif m.get("chapters"):
        facts.append(f'{m["chapters"]} chapter{"s" * (m["chapters"] != 1)}')
    genres = " · ".join(m.get("genres") or [])
    subtitle = " · ".join(x for x in (alt, t.get("native")) if x)
    return (
        "<table>\n<tr>\n"
        f'<td width="32%" valign="top"><a href="{url}"><img src="{guard(m["coverImage"]["extraLarge"])}" '
        f'alt="{esc(name)}" width="100%" /></a></td>\n'
        '<td valign="top">\n'
        f"<sub>\U0001F3B4 <b>{label}</b> · pick of the day</sub>\n"
        f'<h3><a href="{url}">{esc(name)}</a></h3>\n'
        + (f"<sub>{esc(subtitle)}</sub>\n<br/><br/>\n" if subtitle else "")
        + " · ".join(facts) + "\n<br/>\n"
        + (f"<sub>{esc(genres)}</sub>\n<br/><br/>\n" if genres else "<br/>\n")
        + f"{esc(clean(m.get('description')))}\n<br/><br/>\n"
        f'<sub><i>Drawn at random from AniList\'s most popular · <a href="{url}">open on AniList →</a></i></sub>\n'
        "</td>\n</tr>\n</table>"
    )


def _self_check():
    d = datetime.date(2026, 9, 21)
    assert choose(d) == choose(d)
    assert len({choose(d + datetime.timedelta(i))[0] for i in range(5)}) == 5  # every kind in 5 days

    assert clean("A <i>b</i>~!secret!~<br>c &amp; d") == "A b c & d"
    m = {"siteUrl": "https://anilist.co/manga/1", "title": {"romaji": "Jeonjijeok", "english": "ORV", "native": "전지"},
         "coverImage": {"extraLarge": "https://s4.anilist.co/c.jpg"}, "averageScore": 88,
         "genres": ["Action", "Fantasy"], "episodes": None, "chapters": 200,
         "startDate": {"year": 2020}, "description": 'He <b>read</b> "it" all'}
    out = render("MANHWA", m)
    assert "ORV" in out and "Jeonjijeok" in out and "8.8" in out and "200 chapters" in out
    assert "&quot;it&quot;" in out and out.count("<img") == 1 and "api_key" not in out
    bare = render("ANIME", dict(m, averageScore=None, genres=[], chapters=None, startDate=None,
                                title={"romaji": "X", "english": None, "native": None}))
    assert "⭐" not in bare and "<h3>" in bare
    assert "1 episode\n" in render("ANIME", dict(m, episodes=1))

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

    label, filters, page = choose(datetime.date.today())
    try:
        block = render(label, fetch(filters, page))
    except Exception as e:                      # noqa: BLE001
        # keep yesterday's pick on the page rather than an empty box; the log says why
        print(f"otaku source unavailable ({label} page {page}): {e}", file=sys.stderr)
        return
    print(f"otaku pick: {label}, page {page}", file=sys.stderr)
    if a.dry_run:
        print(block)
        return

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
