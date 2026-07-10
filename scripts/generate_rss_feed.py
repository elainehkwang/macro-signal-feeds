#!/usr/bin/env python3
"""
Generate feed-rss.json — Tier 2 RSS/Substack feeds.

Covers Substack newsletters, BIS publications, Gavekal, CFR, and other
free RSS feeds from Tier 2 macro sources.

Usage:
    python scripts/generate_rss_feed.py

Output:
    feeds/feed-rss.json — latest posts from all RSS feeds
"""

import json, sys, os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import xml.etree.ElementTree as ET

ROOT_DIR = Path(__file__).parent.parent
SOURCES_PATH = ROOT_DIR / "sources.json"
FEEDS_DIR = ROOT_DIR / "feeds"
FEEDS_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = FEEDS_DIR / "feed-rss.json"

TIMEOUT = 20
MAX_ENTRIES_PER_FEED = 10

# XML namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss1": "http://purl.org/rss/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def parse_feed(xml_text):
    """Parse RSS 2.0, RSS 1.0/RDF, or Atom feed. Returns list of entry dicts."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        # Try cleaning the text
        clean = xml_text.encode("utf-8", errors="replace")
        root = ET.fromstring(clean)

    entries = []

    # RSS 2.0
    for item in root.iter("item"):
        entries.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
            "description": strip_html(item.findtext("description") or "")[:800].strip(),
        })

    # RSS 1.0 (RDF)
    if not entries:
        for item in root.findall(".//{" + NS["rss1"] + "}item"):
            link_el = item.find("{" + NS["rss1"] + "}link")
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            entries.append({
                "title": (item.findtext("{" + NS["rss1"] + "}title") or "").strip(),
                "link": link,
                "published": (item.findtext("{" + NS["dc"] + "}date") or "").strip(),
                "description": strip_html(item.findtext("{" + NS["rss1"] + "}description") or "")[:800].strip(),
            })

    # Atom
    if not entries:
        for entry in root.findall("atom:entry", NS):
            link_el = entry.find("atom:link", NS)
            href = link_el.get("href", "") if link_el is not None else ""
            entries.append({
                "title": (entry.findtext("atom:title", "", NS) or "").strip(),
                "link": href,
                "published": (entry.findtext("atom:published", "", NS) or entry.findtext("atom:updated", "", NS) or "").strip(),
                "description": strip_html((entry.findtext("atom:summary", "", NS) or "")[:800]).strip(),
            })

    return entries[:MAX_ENTRIES_PER_FEED]


def strip_html(text):
    """Remove HTML tags, keep plain text."""
    import re
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def main():
    sources = json.loads(SOURCES_PATH.read_text())
    feeds = sources.get("rss_feeds", [])

    results = []
    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        try:
            resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                           headers={"Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, */*"})
            resp.raise_for_status()
            entries = parse_feed(resp.text)
            status = f"{len(entries)} entries"
        except Exception as e:
            entries = []
            status = f"error: {e}"

        results.append({
            "name": name,
            "url": url,
            "domain": feed.get("domain", ""),
            "entries": entries,
            "count": len(entries),
        })
        print(f"  {name}: {status}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feeds_count": len(results),
        "total_entries": sum(r["count"] for r in results),
        "feeds": results,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nWrote {output['total_entries']} entries from {output['feeds_count']} feeds to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
