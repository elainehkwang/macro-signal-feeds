#!/usr/bin/env python3
"""
Generate feed-x.json — Tier 2 X/Twitter feed via Nitter RSS.

Nitter is a free, privacy-respecting Twitter frontend that provides RSS
feeds for any public account. We try multiple Nitter instances for redundancy.

Usage:
    python scripts/generate_x_feed.py

Output:
    feeds/feed-x.json — latest tweets from all tracked accounts
"""

import json, sys, os, re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import xml.etree.ElementTree as ET

ROOT_DIR = Path(__file__).parent.parent
SOURCES_PATH = ROOT_DIR / "sources.json"
FEEDS_DIR = ROOT_DIR / "feeds"
FEEDS_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = FEEDS_DIR / "feed-x.json"

TIMEOUT = 20
MAX_TWEETS_PER_ACCOUNT = 10


def load_sources():
    with open(SOURCES_PATH) as f:
        return json.load(f)


def fetch_nitter_rss(handle, instances):
    """Try each Nitter instance in order. Returns list of tweet dicts or None.

    NOTE: Nitter is increasingly unreliable as X restricts access. All
    instances may return empty or CAPTCHA pages. This is a best-effort
    fallback — if ALL instances fail, the Tier 2 X feed will be empty.
    For reliable X access, use X API v2 (Basic: $100/mo, 10K tweets/mo).
    """
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "User-Agent": "Mozilla/5.0 (compatible; macro-signal-feeds/1.0; +https://github.com/elaine/macro-signal-feeds)",
    }
    for base in instances:
        url = f"{base}/{handle}/rss"
        try:
            resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=headers)
            if resp.status_code != 200 or not resp.text.strip():
                continue

            # Check if it's actual RSS (not a CAPTCHA or HTML page)
            if not resp.text.strip().startswith("<?xml") and "<rss" not in resp.text[:200].lower():
                continue

            root = ET.fromstring(resp.content)
            tweets = []
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = (item.findtext("description") or "")[:1000].strip()

                # Nitter RSS titles are like "username: tweet text"
                if title.startswith(f"{handle}:"):
                    text = title[len(f"{handle}:"):].strip()
                else:
                    text = title

                # Extract tweet ID from link (nitter URL format: /handle/status/ID)
                tweet_id = ""
                if "/status/" in link:
                    tweet_id = link.split("/status/")[-1].split("#")[0].split("?")[0]

                tweets.append({
                    "id": tweet_id or link,
                    "text": text,
                    "description": desc,
                    "url": link.replace("https://nitter.net/", "https://x.com/")
                              .replace("https://nitter.poast.org/", "https://x.com/")
                              .replace("https://nitter.privacydev.net/", "https://x.com/"),
                    "published": pub_date,
                })

            if tweets:
                return tweets[:MAX_TWEETS_PER_ACCOUNT]
        except Exception:
            continue

    return None


def main():
    sources = load_sources()
    accounts = sources.get("x_accounts", [])
    instances = sources.get("nitter_instances", [
        "https://nitter.net",
        "https://nitter.poast.org",
    ])

    results = []
    for account in accounts:
        handle = account["handle"]
        tweets = fetch_nitter_rss(handle, instances)

        entry = {
            "handle": handle,
            "name": account.get("name", handle),
            "domain": account.get("domain", ""),
            "note": account.get("note", ""),
        }

        if tweets:
            entry["tweets"] = tweets
            entry["count"] = len(tweets)
        else:
            entry["tweets"] = []
            entry["count"] = 0
            entry["_error"] = "all_nitter_instances_failed"

        results.append(entry)
        print(f"  {handle}: {entry['count']} tweets" if entry['count'] > 0 else f"  {handle}: FAILED")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "nitter_rss",
        "accounts_count": len(results),
        "total_tweets": sum(r["count"] for r in results),
        "accounts_with_tweets": sum(1 for r in results if r["count"] > 0),
        "x": results,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nWrote {output['total_tweets']} tweets from {output['accounts_with_tweets']}/{output['accounts_count']} accounts to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
