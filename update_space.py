#!/usr/bin/env python3
"""Rewrite the space section of the profile README with something current, and preferably
with a picture.

Sources are tried in order of how good they look, falling through on any failure, so the
section is never empty and is almost always an image:

  1. APOD, when it is an image        NASA's picture of the day. Curated, has an
                                      explanation. About nine days in ten.
  2. APOD video thumbnail             APOD is a video roughly one day in ten; a still
                                      is better than nothing.
  3. EPIC                             Full-disc Earth from DSCOVR at L1, a million miles
                                      out. Updated most days and always an image.
  4. NASA Image and Video Library     Enormous archive, needs no key at all. The search
                                      term rotates by day so it does not repeat.
  5. Spaceflight News                 Text headline. Keyless, and the last resort so that
                                      something is always written.

KEY SAFETY, the important part
------------------------------
A README is public, so any URL written into it is public. NASA's own image endpoints under
api.nasa.gov require ?api_key=, which would publish the key on the profile page. The image
hosts used here are the keyless ones instead: apod.nasa.gov, epic.gsfc.nasa.gov and
images-assets.nasa.gov. `guard` enforces that at write time and refuses anything carrying a
key, so a future edit cannot leak one by accident.

Local check, writes nothing:
    python update_space.py --self-check
    python update_space.py --dry-run

In CI:
    python update_space.py --readme README.md
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request

START = "<!-- SPACE:START -->"
END = "<!-- SPACE:END -->"
TIMEOUT = 25
UA = "XxAG17xX-profile-readme (+https://github.com/XxAG17xX)"

# Rotated by day of year so the archive pick is not the same picture every morning.
LIBRARY_TERMS = [
    "nebula", "galaxy", "aurora", "saturn", "jupiter", "supernova remnant",
    "star cluster", "solar eclipse", "spacewalk", "hubble deep field",
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def guard(url):
    """Refuse to publish anything carrying a credential. A README is world-readable."""
    if not url:
        raise ValueError("empty image url")
    low = url.lower()
    if "api_key" in low or "apikey" in low:
        raise ValueError(f"refusing to write a URL containing a key: {url[:60]}...")
    return url


def trim(text, limit=260):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def card(img, title, caption, link=None):
    img = guard(img)
    inner = f'<img src="{img}" alt="{title}" width="440" />'
    if link:
        inner = f'<a href="{guard(link)}">{inner}</a>'
    return f"{inner}\n\n**{title}**  \n{caption}"


def key():
    return os.environ.get("NASA_API_KEY", "").strip() or "DEMO_KEY"


def from_apod():
    d = get_json(f"https://api.nasa.gov/planetary/apod?api_key={key()}")
    img = d.get("url") if d.get("media_type") == "image" else d.get("thumbnail_url")
    if not img:
        raise ValueError("APOD entry has no usable image")
    return card(
        img,
        d.get("title", "Astronomy Picture of the Day"),
        f'{trim(d.get("explanation", ""))}\n\n<sub>NASA Astronomy Picture of the Day, {d.get("date", "")}</sub>',
        link=d.get("hdurl") or d.get("url"),
    )


def from_epic():
    """Full-disc Earth from a million miles away. Metadata needs the key; the image itself
    is served keyless from epic.gsfc.nasa.gov, which is why that host is used and not the
    api.nasa.gov archive path (that one 403s without a key)."""
    items = get_json(f"https://api.nasa.gov/EPIC/api/natural?api_key={key()}")
    if not items:
        raise ValueError("EPIC returned no frames")
    it = items[-1]
    d = it["date"].split(" ")[0].replace("-", "/")
    img = f'https://epic.gsfc.nasa.gov/archive/natural/{d}/png/{it["image"]}.png'
    caption = trim(it.get("caption", "Earth from the DSCOVR satellite at L1."))
    return card(
        img,
        "Earth today",
        f'{caption}\n\n<sub>NASA EPIC aboard DSCOVR, {it["date"].split(" ")[0]}</sub>',
        link="https://epic.gsfc.nasa.gov/",
    )


def from_library():
    """Keyless end to end, so this still works if the key is missing or rate-limited."""
    term = LIBRARY_TERMS[datetime.date.today().timetuple().tm_yday % len(LIBRARY_TERMS)]
    q = urllib.parse.quote(term)
    d = get_json(f"https://images-api.nasa.gov/search?q={q}&media_type=image&page_size=20")
    items = d.get("collection", {}).get("items", [])
    if not items:
        raise ValueError(f"no library results for {term}")
    it = items[datetime.date.today().day % len(items)]
    img = it["links"][0]["href"]
    meta = it["data"][0]
    return card(
        img,
        meta.get("title", term.title()),
        f'{trim(meta.get("description", ""), 200)}\n\n<sub>NASA Image and Video Library, searched "{term}"</sub>',
    )


def from_news():
    d = get_json("https://api.spaceflightnewsapi.net/v4/articles/?limit=1")
    a = d["results"][0]
    return (
        f'**[{a.get("title", "").strip()}]({a.get("url", "")})**\n\n'
        f'<sub>{a.get("news_site", "")}, {(a.get("published_at") or "")[:10]}</sub>'
    )


def build():
    for fn in (from_apod, from_epic, from_library, from_news):
        try:
            return fn()
        except Exception as e:                  # noqa: BLE001 - fall through on anything
            print(f"{fn.__name__} unavailable: {e}", file=sys.stderr)
    raise SystemExit("every source failed")


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
    assert trim("word " * 200).endswith("...") and len(trim("word " * 200)) <= 264

    # the guard is the part that must never regress
    guard("https://epic.gsfc.nasa.gov/archive/natural/x.png")
    for bad in (
        "https://api.nasa.gov/EPIC/archive/natural/x.png?api_key=abc123",
        "https://example.com/i.png?apiKey=abc",
        "",
    ):
        try:
            guard(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"guard let through: {bad!r}")

    assert 'src="https://epic.gsfc.nasa.gov/a.png"' in card(
        "https://epic.gsfc.nasa.gov/a.png", "T", "C")
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
    import urllib.parse  # noqa: E402 - only needed by from_library
    main()
