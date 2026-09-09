#!/usr/bin/env python3
"""Rewrite the space section of the profile README with something current.

Primary source is NASA's Astronomy Picture of the Day, because a picture is the point.
Falls back to the Spaceflight News API, which needs no key, if APOD is unavailable for
any reason: a missing key, the shared DEMO_KEY rate limit, or the service being down.
Something is always written, so the profile never shows a stale placeholder or a hole.

Local check, writes nothing:
    python update_space.py --dry-run

In CI:
    python update_space.py --readme README.md
"""

import argparse
import json
import os
import sys
import urllib.request

START = "<!-- SPACE:START -->"
END = "<!-- SPACE:END -->"
TIMEOUT = 20
UA = "XxAG17xX-profile-readme (+https://github.com/XxAG17xX)"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def trim(text, limit=260):
    """One sentence if it fits, otherwise a clean truncation at a word boundary."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "..."


def from_apod():
    """NASA APOD. DEMO_KEY works but is rate-limited per IP, and CI shares IPs, so a
    real key in the NASA_API_KEY secret is what makes this reliable. Free from
    api.nasa.gov, takes about a minute."""
    key = os.environ.get("NASA_API_KEY", "").strip() or "DEMO_KEY"
    d = get_json("https://api.nasa.gov/planetary/apod?api_key=" + key)

    # APOD is a video roughly one day in ten. Videos cannot be embedded in a README, so
    # use the thumbnail when there is one and skip to the news source when there is not.
    if d.get("media_type") == "image":
        img = d.get("url")
    else:
        img = d.get("thumbnail_url")
    if not img:
        raise ValueError("APOD entry has no usable image")

    title = d.get("title", "Astronomy Picture of the Day")
    date = d.get("date", "")
    why = trim(d.get("explanation", ""))
    link = d.get("hdurl") or d.get("url") or "https://apod.nasa.gov/apod/"

    return (
        f'<a href="{link}"><img src="{img}" alt="{title}" width="420" /></a>\n\n'
        f"**{title}**  \n"
        f"{why}\n\n"
        f"<sub>NASA Astronomy Picture of the Day, {date}</sub>"
    )


def from_news():
    d = get_json("https://api.spaceflightnewsapi.net/v4/articles/?limit=1")
    a = d["results"][0]
    title = a.get("title", "").strip()
    url = a.get("url", "")
    site = a.get("news_site", "")
    when = (a.get("published_at") or "")[:10]
    return (
        f"**[{title}]({url})**\n\n"
        f"<sub>{site}, {when}</sub>"
    )


def build():
    try:
        return from_apod()
    except Exception as e:                      # noqa: BLE001 - any failure falls back
        print(f"APOD unavailable ({e}); falling back to Spaceflight News", file=sys.stderr)
        return from_news()


def splice(readme, block):
    """Replace only what sits between the markers. Raises if they are missing, rather
    than silently appending and quietly doing nothing useful for months."""
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
    assert trim("word " * 200).endswith("...")
    assert len(trim("word " * 200)) <= 264
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
