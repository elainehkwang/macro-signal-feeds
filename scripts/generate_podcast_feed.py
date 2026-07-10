#!/usr/bin/env python3
"""
Generate feed-podcasts.json — Tier 2 macro podcast feeds.

Fetches podcast RSS feeds, extracts episode metadata.
Transcription is NOT done here — that requires an API key (Whisper/OpenAI)
and is done by the Agent on demand via web_extract or TTS transcription.

Usage:
    python scripts/generate_podcast_feed.py

Output:
    feeds/feed-podcasts.json — latest episodes from all tracked podcasts
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
OUTPUT_PATH = FEEDS_DIR / "feed-podcasts.json"

TIMEOUT = 30
MAX_EPISODES_PER_FEED = 5


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def parse_podcast_rss(xml_text):
    """Parse iTunes-compatible podcast RSS feed."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))

    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

    episodes = []
    for item in root.iter("item"):
        ep = {
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "guid": (item.findtext("guid") or item.findtext("link") or "").strip(),
            "pub_date": (item.findtext("pubDate") or "").strip(),
            "description": strip_html(item.findtext("description") or "")[:1000].strip(),
            "duration": (item.findtext("itunes:duration", "", ns) or "").strip(),
        }

        # Enclosure (audio URL)
        enclosure = item.find("enclosure")
        if enclosure is not None:
            ep["audio_url"] = enclosure.get("url", "")

        episodes.append(ep)

    # Channel metadata
    channel_title = (root.findtext("channel/title") or root.findtext("title") or "").strip()
    channel_desc = strip_html(root.findtext("channel/description") or "")[:500].strip()

    return {
        "channel": channel_title,
        "description": channel_desc,
        "episodes": episodes[:MAX_EPISODES_PER_FEED],
    }


def main():
    sources = json.loads(SOURCES_PATH.read_text())
    feeds = sources.get("podcast_feeds", [])

    results = []
    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        try:
            resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                           headers={"Accept": "application/rss+xml, application/xml, text/xml, */*",
                                    "User-Agent": "macro-signal-feeds/1.0"})
            resp.raise_for_status()
            data = parse_podcast_rss(resp.text)
            if not data["channel"]:
                data["channel"] = name
            data["feed_name"] = name
            data["domain"] = feed.get("domain", "")
            status = f"{len(data['episodes'])} episodes"
        except Exception as e:
            data = {
                "feed_name": name,
                "channel": name,
                "domain": feed.get("domain", ""),
                "episodes": [],
                "_error": str(e),
            }
            status = f"error: {e}"

        results.append(data)
        print(f"  {name}: {status}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feeds_count": len(results),
        "total_episodes": sum(len(r.get("episodes", [])) for r in results),
        "podcasts": results,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nWrote {output['total_episodes']} episodes from {output['feeds_count']} feeds to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
