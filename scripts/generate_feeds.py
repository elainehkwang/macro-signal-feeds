#!/usr/bin/env python3
"""
Generate feed-rss.json — unified RSS/Substack + Podcast feed generator.

Handles:
  - RSS 2.0, RSS 1.0 (RDF), Atom (standard feeds)
  - Podcast RSS with iTunes namespace (enclosure, duration)
  - Substack newsletters

Usage:
    python scripts/generate_feeds.py

Output:
    feeds/feed-rss.json     — all RSS + Substack entries
    feeds/feed-podcasts.json — podcast episodes (metadata only, no transcription)
"""

import json, re, sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import xml.etree.ElementTree as ET

ROOT_DIR = Path(__file__).parent.parent
SOURCES_PATH = ROOT_DIR / "sources.json"
FEEDS_DIR = ROOT_DIR / "feeds"
FEEDS_DIR.mkdir(exist_ok=True)

OUTPUT_RSS = FEEDS_DIR / "feed-rss.json"
OUTPUT_PODCASTS = FEEDS_DIR / "feed-podcasts.json"

TIMEOUT = 30
MAX_ENTRIES = 10

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss1": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}

HEADERS = {
    "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, */*",
    "User-Agent": "macro-signal-feeds/1.0 (+https://github.com/elaine/macro-signal-feeds)",
}


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def parse_feed(xml_text, feed_type="rss"):
    """Parse any RSS/Atom feed. Returns (entries, channel_meta)."""
    try:
        raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))

    entries = []

    # ── RSS 2.0 ──
    for item in root.iter("item"):
        entry = {
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
            "description": strip_html(item.findtext("description") or "")[:800].strip(),
        }

        # Podcast-specific fields
        if feed_type == "podcast":
            enclosure = item.find("enclosure")
            if enclosure is not None:
                entry["audio_url"] = enclosure.get("url", "")
            entry["duration"] = (item.findtext("itunes:duration", "", NS) or "").strip()

        entries.append(entry)

    # ── RSS 1.0 (RDF) ──
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

    # ── Atom ──
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

    # Channel metadata
    channel_title = ""
    channel_desc = ""
    channel_el = root.find("channel")
    if channel_el is not None:
        channel_title = (channel_el.findtext("title") or "").strip()
        channel_desc = strip_html(channel_el.findtext("description") or "")[:500].strip()

    return entries[:MAX_ENTRIES], channel_title, channel_desc


def fetch_feed(name, url, feed_type="rss"):
    """Fetch and parse a single feed. Returns result dict."""
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
        resp.raise_for_status()
        entries, channel, desc = parse_feed(resp.text, feed_type)
        return {
            "name": name,
            "url": url,
            "channel": channel or name,
            "description": desc,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {
            "name": name,
            "url": url,
            "channel": name,
            "entries": [],
            "count": 0,
            "_error": str(e),
        }


def main():
    sources = json.loads(SOURCES_PATH.read_text())
    now = datetime.now(timezone.utc).isoformat()

    # ── RSS / Substack ────────────────────────────────────────────────
    rss_feeds = sources.get("rss_feeds", [])
    rss_results = []
    for feed in rss_feeds:
        result = fetch_feed(feed["name"], feed["url"], "rss")
        result["domain"] = feed.get("domain", "")
        rss_results.append(result)
        status = f"{result['count']} entries" if result["count"] > 0 else f"error: {result.get('_error', 'unknown')}"
        print(f"  RSS {feed['name']}: {status}")

    rss_output = {
        "generated_at": now,
        "source": "rss",
        "feeds_count": len(rss_results),
        "total_entries": sum(r["count"] for r in rss_results),
        "feeds": rss_results,
    }
    OUTPUT_RSS.write_text(json.dumps(rss_output, ensure_ascii=False, indent=2))

    # ── Podcasts ──────────────────────────────────────────────────────
    pod_feeds = sources.get("podcast_feeds", [])
    pod_results = []
    for feed in pod_feeds:
        result = fetch_feed(feed["name"], feed["url"], "podcast")
        result["domain"] = feed.get("domain", "")
        # Add episodes with enclosure
        pod_results.append({
            "feed_name": feed["name"],
            "channel": result["channel"],
            "domain": feed.get("domain", ""),
            "description": result.get("description", ""),
            "episodes": result["entries"],
        })
        status = f"{result['count']} episodes" if result["count"] > 0 else f"error: {result.get('_error', 'unknown')}"
        print(f"  POD {feed['name']}: {status}")

    pod_output = {
        "generated_at": now,
        "source": "podcast_rss",
        "feeds_count": len(pod_results),
        "total_episodes": sum(len(r["episodes"]) for r in pod_results),
        "podcasts": pod_results,
    }
    OUTPUT_PODCASTS.write_text(json.dumps(pod_output, ensure_ascii=False, indent=2))

    # ── Summary ───────────────────────────────────────────────────────
    rss_total = rss_output["total_entries"]
    pod_total = pod_output["total_episodes"]
    print(f"\nRSS: {rss_total} entries from {len(rss_feeds)} feeds")
    print(f"Podcasts: {pod_total} episodes from {len(pod_feeds)} feeds")
    print(f"Output: {OUTPUT_RSS}, {OUTPUT_PODCASTS}")


if __name__ == "__main__":
    main()
