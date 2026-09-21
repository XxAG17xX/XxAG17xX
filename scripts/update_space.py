#!/usr/bin/env python3
"""Rewrite the space section of the profile README: two pictures side by side, plus the
day's spaceflight headline underneath.

Layout
------
The headline is the <summary> of a <details open> block; the pictures sit inside it,
open by default; one click folds it to a single line. Inside: a two-column HTML table, so
each picture keeps its own caption. GitHub allows table, details, summary, img, a, b, br
and sub in Markdown, so this renders on the profile. The Earth cell holds up to four EPIC
frames from the same day (a 2x2 grid), the APOD caption ends with a "more" link to the APOD
page. If only one picture can be fetched, it falls back to a single centred image rather
than a lopsided table. If none can, the headline alone carries the section.
The "From orbit today" heading lives in README.md, outside the markers, and is not touched.

Picture sources, tried in order until two DIFFERENT ones succeed
---------------------------------------------------------------
  1. APOD      NASA's curated picture of the day, or its thumbnail when the entry is a
               video (about one day in ten).
  2. EPIC      Full-disc Earth from DSCOVR at L1, a million miles out. Updated most days.
  3. Library   NASA Image and Video Library. Keyless, enormous, and the search term
               rotates by day so it does not repeat. Used twice with different terms if
               both APOD and EPIC are unavailable.

KEY SAFETY
----------
A README is world-readable, so every URL written into it is public. NASA's image endpoints
under api.nasa.gov require ?api_key=, which would publish the key on the profile page. Only
keyless image hosts are ever embedded: apod.nasa.gov, epic.gsfc.nasa.gov and
images-assets.nasa.gov. `guard` enforces this at write time and the self-check covers it,
so a later edit cannot leak a key by accident.

Local checks, write nothing:
    python update_space.py --self-check
    python update_space.py --dry-run

In CI:
    python update_space.py --readme README.md
"""

import argparse
import datetime
import html
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

START = "<!-- SPACE:START -->"
END = "<!-- SPACE:END -->"
TIMEOUT = 25
UA = "XxAG17xX-profile-readme (+https://github.com/XxAG17xX)"

LIBRARY_TERMS = [
    "nebula", "galaxy", "aurora", "saturn", "jupiter", "supernova remnant",
    "star cluster", "solar eclipse", "spacewalk", "hubble deep field",
    "mars surface", "andromeda",
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def guard(url):
    """Refuse to publish anything carrying a credential."""
    if not url:
        raise ValueError("empty url")
    low = url.lower()
    if "api_key" in low or "apikey" in low:
        raise ValueError(f"refusing to write a URL containing a key: {url[:60]}...")
    return url


def trim(text, limit=150):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def key():
    return os.environ.get("NASA_API_KEY", "").strip() or "DEMO_KEY"


def esc(text):
    """Escape text going into HTML, so a quote or & in a title cannot break the tag."""
    return html.escape(text or "")


# --------------------------------------------------------------------- sources
# Each returns {"img", "title", "caption", "link"} or raises.

def src_apod():
    # thumbs=true: without it the API sends no thumbnail_url, so video days always failed
    d = get_json(f"https://api.nasa.gov/planetary/apod?api_key={key()}&thumbs=true")
    img = d.get("url") if d.get("media_type") == "image" else d.get("thumbnail_url")
    if not img:
        raise ValueError("APOD entry has no usable image")
    day = d.get("date", "")
    return {
        "img": img,
        "title": d.get("title", "Astronomy Picture of the Day"),
        "caption": trim(d.get("explanation", "")),
        "link": d.get("hdurl") or d.get("url"),
        # the caption is a trailer, this is the film: apod.nasa.gov/apod/ap260920.html
        "more": datetime.date.fromisoformat(day).strftime("https://apod.nasa.gov/apod/ap%y%m%d.html") if day else None,
        "credit": f"NASA APOD, {day}",
    }


def epic_img(it):
    # jpg is the half-resolution copy, much lighter than the full-resolution png
    day = it["date"].split(" ")[0].replace("-", "/")
    return f'https://epic.gsfc.nasa.gov/archive/natural/{day}/jpg/{it["image"]}.jpg'


def epic_facts(it):
    """(distance in million km, lat, lon) of one frame, or None if the metadata is not what
    we expect. Never guess: on None the caller falls back to the generic caption."""
    try:
        p = it["dscovr_j2000_position"]
        km = (p["x"] ** 2 + p["y"] ** 2 + p["z"] ** 2) ** 0.5
        lat, lon = it["centroid_coordinates"]["lat"], it["centroid_coordinates"]["lon"]
    except (KeyError, TypeError) as e:
        print(f"EPIC metadata not as expected: {e!r}", file=sys.stderr)
        return None
    if not 1e6 < km < 2e6:  # DSCOVR sits at L1, about 1.5 million km out; anything else = wrong units
        print(f"EPIC distance out of range: {km:.0f}", file=sys.stderr)
        return None
    return km / 1e6, lat, lon


def age_label(age):
    return "Earth today" if age == 0 else "Earth yesterday" if age == 1 else f"Earth, {age} days ago"


def src_epic():
    items = get_json(f"https://api.nasa.gov/EPIC/api/natural?api_key={key()}")
    if not items:
        raise ValueError("EPIC returned no frames")
    items = sorted(items, key=lambda i: i["date"])  # "YYYY-MM-DD HH:MM:SS" sorts as time
    n = len(items)
    # first, two in between, last; the set drops duplicates when there are fewer than 4 frames
    picks = [items[i] for i in sorted({0, n // 3, 2 * n // 3, n - 1})]
    it = items[-1]
    day = it["date"].split(" ")[0]
    age = (datetime.date.today() - datetime.date.fromisoformat(day)).days
    facts = epic_facts(it)
    if facts:
        mkm, lat, lon = facts
        where = f'{abs(lat):.0f}\u00b0{"N" if lat >= 0 else "S"} {abs(lon):.0f}\u00b0{"E" if lon >= 0 else "W"}'
        caption = (f"Full-disc Earth from DSCOVR, {mkm:.2f} million km out. "
                   f"{len(picks)} frames from {day}; the latest is centred on {where}.")
    else:
        caption = trim(it.get("caption", "Taken by NASA's EPIC camera aboard the NOAA DSCOVR spacecraft."))
    return {
        # epic.gsfc.nasa.gov is keyless; the api.nasa.gov archive path 403s without a key.
        "img": epic_img(it),
        "imgs": [epic_img(x) for x in picks],
        "title": age_label(age),
        "caption": caption,
        "link": "https://epic.gsfc.nasa.gov/",
        "credit": f"NASA EPIC aboard DSCOVR, {day}",
    }


def src_library(offset=0):
    """Keyless end to end, so it still works with no key or a rate-limited one."""
    today = datetime.date.today()
    term = LIBRARY_TERMS[(today.timetuple().tm_yday + offset) % len(LIBRARY_TERMS)]
    q = urllib.parse.quote(term)
    d = get_json(f"https://images-api.nasa.gov/search?q={q}&media_type=image&page_size=20")
    items = d.get("collection", {}).get("items", [])
    if not items:
        raise ValueError(f"no library results for {term}")
    it = items[(today.day + offset) % len(items)]
    meta = it["data"][0]
    return {
        "img": it["links"][0]["href"],
        "title": meta.get("title", term.title()),
        "caption": trim(meta.get("description", "")),
        "link": None,
        "credit": f'NASA Image Library, "{term}"',
    }


def src_news():
    """The headline. Two independent sources, because one of them is failing in CI.

    The Spaceflight News API works from a normal connection but produced no headline on
    three consecutive GitHub Actions runs (2026-09-10 and 2026-09-11), while APOD and EPIC
    succeeded in the same runs. The likely cause is that it rejects datacentre IP ranges,
    which is what GitHub-hosted runners use. NASA's own RSS is the fallback because NASA
    endpoints demonstrably reach the runner already.

    The workflow log carries the reason: each failure prints "news source unavailable".
    """
    errors = []

    try:
        d = get_json("https://api.spaceflightnewsapi.net/v4/articles/?limit=1")
        a = d["results"][0]
        return {
            "title": a.get("title", "").strip(),
            "url": a.get("url", ""),
            "site": a.get("news_site", ""),
            "date": (a.get("published_at") or "")[:10],
        }
    except Exception as e:                      # noqa: BLE001
        errors.append(f"spaceflightnewsapi: {e}")
        print(f"news source unavailable, {errors[-1]}", file=sys.stderr)

    try:
        req = urllib.request.Request(
            "https://www.nasa.gov/news-release/feed/", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            root = ET.fromstring(r.read())
        item = root.find("./channel/item")
        if item is None:
            raise ValueError("RSS had no items")
        pub = (item.findtext("pubDate") or "").strip()
        # "Thu, 11 Sep 2026 14:02:00 +0000" -> "2026-09-11"
        try:
            date = datetime.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
        except ValueError:
            date = datetime.date.today().isoformat()
        return {
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "site": "NASA",
            "date": date,
        }
    except Exception as e:                      # noqa: BLE001
        errors.append(f"nasa rss: {e}")
        print(f"news source unavailable, {errors[-1]}", file=sys.stderr)

    raise RuntimeError("; ".join(errors))


# --------------------------------------------------------------------- render

def cell(p):
    imgs = p.get("imgs") or [p["img"]]
    w = "100%" if len(imgs) == 1 else "48%"  # 48% so two fit per row with the gap between them
    inner = "\n".join(f'<img src="{guard(u)}" alt="{esc(p["title"])}" width="{w}" />' for u in imgs)
    if p.get("link"):
        inner = f'<a href="{guard(p["link"])}">{inner}</a>'
    more = f' <a href="{guard(p["more"])}">more \u2192</a>' if p.get("more") else ""
    return (
        '<td width="50%" valign="top" align="center">\n'
        f"{inner}\n<br/><br/>\n"
        f'<b>{esc(p["title"])}</b>\n<br/>\n'
        f'<sub>{esc(p["caption"])}{more}</sub>\n<br/><br/>\n'
        f'<sub><i>{esc(p["credit"])}</i></sub>\n'
        "</td>"
    )


def render(pics, news):
    parts = []
    if len(pics) >= 2:
        parts.append("<table>\n<tr>\n" + cell(pics[0]) + "\n" + cell(pics[1]) + "\n</tr>\n</table>")
    elif len(pics) == 1:
        p = pics[0]
        img = f'<img src="{guard(p["img"])}" alt="{esc(p["title"])}" width="440" />'
        if p.get("link"):
            img = f'<a href="{guard(p["link"])}">{img}</a>'
        parts.append(f'<p align="center">{img}<br/><b>{esc(p["title"])}</b><br/>'
                     f'<sub>{esc(p["caption"])}</sub><br/><sub><i>{esc(p["credit"])}</i></sub></p>')
    headline = ""
    if news:
        headline = (f'\U0001F4F0 <b><a href="{news["url"]}">{esc(news["title"])}</a></b> '
                    f'<sub>{esc(news["site"])}, {news["date"]}</sub>')
    if not parts and not headline:
        raise SystemExit("every source failed")
    if not parts:
        return f"<p>{headline}</p>"
    body = "\n\n".join(parts)
    if not headline:
        return body
    # summary = headline; open by default, a click folds it to one line
    return f"<details open>\n<summary>{headline}</summary>\n\n{body}\n\n</details>"


def build():
    # A silent fall back to DEMO_KEY is the failure mode to avoid: say which one ran (never the key).
    print("NASA_API_KEY set" if os.environ.get("NASA_API_KEY", "").strip()
          else "NASA_API_KEY missing, using DEMO_KEY", file=sys.stderr)
    pics, seen = [], set()
    for fn in (src_apod, src_epic, lambda: src_library(0), lambda: src_library(5)):
        if len(pics) == 2:
            break
        try:
            p = fn()
            if p["img"] in seen:
                continue
            seen.add(p["img"])
            pics.append(p)
        except Exception as e:                  # noqa: BLE001 - fall through on anything
            print(f"picture source unavailable: {e}", file=sys.stderr)
    try:
        news = src_news()
    except Exception as e:                      # noqa: BLE001
        # Do NOT drop this quietly. Both runs on 2026-09-10 and 2026-09-11 succeeded with
        # two pictures and no headline, and nothing on the page said a third element was
        # meant to be there. A section that silently loses a piece and still reports
        # success is the exact failure this profile's owner writes about.
        print(f"ALL news sources failed: {e}", file=sys.stderr)
        news = {"title": "Headline unavailable today", "url": "https://www.nasa.gov/news/",
                "site": "both news sources unreachable", "date": datetime.date.today().isoformat()}
    return render(pics, news)


def splice(readme, block):
    i, j = readme.find(START), readme.find(END)
    if i == -1 or j == -1 or j < i:
        raise SystemExit(f"markers not found in README: expected {START} ... {END}")
    return readme[: i + len(START)] + "\n" + block + "\n" + readme[j:]


def _self_check():
    body = f"before\n{START}\nOLD\n{END}\nafter"
    out = splice(body, "NEW")
    assert "OLD" not in out and "NEW" in out
    assert out.startswith("before") and out.endswith("after")

    assert trim("a b c", 100) == "a b c"
    assert trim("word " * 200).endswith("...") and len(trim("word " * 200)) <= 154

    guard("https://epic.gsfc.nasa.gov/archive/natural/x.png")
    for bad in ("https://api.nasa.gov/EPIC/archive/x.png?api_key=abc",
                "https://example.com/i.png?apiKey=abc", ""):
        try:
            guard(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"guard let through: {bad!r}")

    p = {"img": "https://epic.gsfc.nasa.gov/a.jpg", "title": "T",
         "caption": "C", "link": None, "credit": "X"}
    n = {"title": "H", "url": "https://e.com", "site": "S", "date": "2026-01-01"}

    two = render([p, dict(p, img="https://epic.gsfc.nasa.gov/b.jpg")], n)
    assert two.count("<td") == 2 and "<table>" in two and "\U0001F4F0" in two
    assert two.startswith("<details open>") and "<summary>" in two and two.endswith("</details>")

    four = dict(p, imgs=[f"https://epic.gsfc.nasa.gov/{i}.jpg" for i in range(4)])
    assert render([p, four], n).count("<img") == 5

    one = render([p], n)
    assert "<table>" not in one and 'width="440"' in one

    none_ = render([], n)
    assert "<img" not in none_ and "\U0001F4F0" in none_ and "<details" not in none_

    assert "more \u2192" in cell(dict(p, more="https://apod.nasa.gov/apod/ap260920.html"))
    assert "&quot;" in cell(dict(p, title='A "quoted" title')) and '"quoted"' not in cell(dict(p, title='A "quoted" title'))

    good = {"dscovr_j2000_position": {"x": -1293750.0, "y": 656193.0, "z": 306840.0},
            "centroid_coordinates": {"lat": 12.3, "lon": -34.6}}
    mkm, lat, lon = epic_facts(good)
    assert 1.4 < mkm < 1.6 and lat == 12.3
    assert epic_facts({}) is None
    assert epic_facts(dict(good, dscovr_j2000_position={"x": 1.0, "y": 1.0, "z": 1.0})) is None
    assert age_label(0) == "Earth today" and age_label(1) == "Earth yesterday" and "4 days" in age_label(4)
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

    block = build()
    if a.dry_run:
        print(block)
        return

    with open(a.readme, encoding="utf-8") as f:
        old = f.read()
    new = splice(old, block)
    if new == old:
        print("no change")
        return
    with open(a.readme, "w", encoding="utf-8") as f:
        f.write(new)
    print("README updated")


if __name__ == "__main__":
    main()
