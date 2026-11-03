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
from email.utils import parsedate_to_datetime
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
DEFAULT_MAX_AGE_DAYS = 90


def _parse_dt(raw):
    """Parse RFC-822 (RSS) or ISO-8601 (Atom/RDF) date strings. Returns aware datetime or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def newest_age_days(entries):
    """Days since the newest entry. None if no parseable dates.

    This is the guard that would have caught CSIS: it returns HTTP 200 with
    well-formed XML, but every item is dated 2016. HTTP status alone can't
    detect that — only the newest timestamp can.
    """
    stamps = [dt for dt in (_parse_dt(e.get("published")) for e in entries) if dt]
    if not stamps:
        return None
    return (datetime.now(timezone.utc) - max(stamps)).days

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


# Macro-relevance keywords for title/description filtering.
# An entry must match at least one keyword to be tagged relevant=true.
# Entries tagged false are still included in feeds but can be skipped by Agent.
MACRO_KEYWORDS = [
    "inflation", "deflation", "cpi", "pce", "ppi",
    "fed", "fomc", "federal reserve", "powell", "ecb", "boj", "boe", "pboc",
    "rate hike", "rate cut", "interest rate", "monetary policy", "tightening", "easing",
    "gdp", "recession", "growth", "employment", "unemployment", "payroll", "nfo",
    "fiscal", "deficit", "debt", "treasury", "auction", "tga", "budget",
    "bond", "yield", "spread", "credit", "oas", "ig ", "hy ",
    "dollar", "dxy", "fx", "currency", "yen", "euro", "rmb", "cny",
    "oil", "crude", "energy", "gas", "petroleum", "eia", "opec",
    "gold", "copper", "commodity", "supply chain", "inventory",
    "china", "chinese", "beijing", "xi ",
    "japan", "japanese", "tokyo",
    "europe", "european", "eu ", "brussels",
    "trade", "tariff", "sanction", "export control",
    "geopolitic", "war", "conflict", "houthi", "hormuz", "taiwan",
    "liquidity", "balance sheet", "qt", "qe", "repo", "sofr",
    "semiconductor", "chip", "tsmc", "nvidia", "capex",
    "ai ", "artificial intelligence", "data center", "infrastructure",
    "housing", "real estate", "property",
    "carry trade", "volatility", "vix",
    "regulation", "policy", "legislation",
    "bank", "financial stability", "systemic",
]
NON_MACRO_PATTERNS = [
    r"(?i)\b(fiction|novel|book review|movie|film|sci-fi|science fiction)\b",
    r"(?i)\b(personal update|life update|announcement|podcast episode)\b",
    r"(?i)\b(sponsor|sponsored|advertisement|promo)\b",
]


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def tag_relevance(entries):
    """Tag each entry with relevant=true/false based on title+description keyword match.
    Also removes entries that match NON_MACRO_PATTERNS (false positives)."""
    for entry in entries:
        text = f"{entry.get('title', '')} {entry.get('description', '')}".lower()

        # Check non-macro patterns first (exclusion)
        for pattern in NON_MACRO_PATTERNS:
            if re.search(pattern, text):
                entry["relevant"] = False
                entry["_skip_reason"] = "non_macro_pattern"
                break
        else:
            # Check macro keywords (inclusion)
            entry["relevant"] = any(kw in text for kw in MACRO_KEYWORDS)
            if not entry["relevant"]:
                entry["_skip_reason"] = "no_macro_keyword"
    return entries


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


def fetch_feed(name, url, feed_type="rss", max_age_days=DEFAULT_MAX_AGE_DAYS):
    """Fetch and parse a single feed. Returns result dict with a health status.

    status is one of: ok | stale | empty | error
      - error : fetch/parse blew up
      - empty : HTTP 200 but zero entries (dead or empty feed)
      - stale : entries exist but newest is older than max_age_days (e.g. CSIS)
      - ok    : entries exist and are recent
    """
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
        resp.raise_for_status()
        entries, channel, desc = parse_feed(resp.text, feed_type)
        age = newest_age_days(entries)
        if not entries:
            status = "empty"
        elif age is not None and age > max_age_days:
            status = "stale"
        else:
            status = "ok"
        return {
            "name": name,
            "url": url,
            "channel": channel or name,
            "description": desc,
            "entries": entries,
            "count": len(entries),
            "newest_age_days": age,
            "max_age_days": max_age_days,
            "status": status,
            "_stale": status in ("stale", "empty"),
        }
    except Exception as e:
        return {
            "name": name,
            "url": url,
            "channel": name,
            "entries": [],
            "count": 0,
            "newest_age_days": None,
            "max_age_days": max_age_days,
            "status": "error",
            "_stale": True,
            "_error": str(e),
        }


def main():
    sources = json.loads(SOURCES_PATH.read_text())
    now = datetime.now(timezone.utc).isoformat()
    default_age = sources.get("default_max_age_days", DEFAULT_MAX_AGE_DAYS)
    failures = []

    def report(kind, feed, result):
        """Print one human-readable line + collect any unhealthy source."""
        age = result.get("newest_age_days")
        age_s = "?" if age is None else f"{age}d"
        if result["status"] == "ok":
            print(f"  {kind} {feed['name']}: {result['count']} entries (newest {age_s})")
        elif result["status"] == "stale":
            print(f"  {kind} {feed['name']}: STALE {result['count']} entries, newest {age_s} "
                  f"> {result['max_age_days']}d  <<< 需替换")
            failures.append((kind, feed["name"], f"stale {age_s}"))
        elif result["status"] == "empty":
            print(f"  {kind} {feed['name']}: EMPTY (0 entries)  <<< 需替换")
            failures.append((kind, feed["name"], "empty"))
        else:
            print(f"  {kind} {feed['name']}: ERROR {result.get('_error', 'unknown')[:80]}  <<< 需替换")
            failures.append((kind, feed["name"], result.get("_error", "error")[:80]))

    # ── RSS / Substack ────────────────────────────────────────────────
    rss_feeds = sources.get("rss_feeds", [])
    rss_results = []
    for feed in rss_feeds:
        result = fetch_feed(
            feed["name"], feed["url"], "rss",
            max_age_days=feed.get("max_age_days", default_age),
        )
        result["domain"] = feed.get("domain", "")
        result["tier"] = feed.get("tier", 2)
        result["entries"] = tag_relevance(result["entries"])
        result["relevant_count"] = sum(1 for e in result["entries"] if e.get("relevant"))
        rss_results.append(result)
        report("RSS", feed, result)

    unhealthy = [r for r in rss_results if r["status"] != "ok"]
    rss_output = {
        "generated_at": now,
        "source": "rss",
        "feeds_count": len(rss_results),
        "total_entries": sum(r["count"] for r in rss_results),
        "unhealthy_count": len(unhealthy),
        "unhealthy": [
            {"name": r["name"], "status": r["status"], "newest_age_days": r.get("newest_age_days")}
            for r in unhealthy
        ],
        "feeds": rss_results,
    }
    OUTPUT_RSS.write_text(json.dumps(rss_output, ensure_ascii=False, indent=2))

    # ── Podcasts ──────────────────────────────────────────────────────
    pod_feeds = sources.get("podcast_feeds", [])
    pod_results = []
    for feed in pod_feeds:
        result = fetch_feed(
            feed["name"], feed["url"], "podcast",
            max_age_days=feed.get("max_age_days", default_age),
        )
        result["domain"] = feed.get("domain", "")
        pod_results.append({
            "feed_name": feed["name"],
            "channel": result["channel"],
            "domain": feed.get("domain", ""),
            "description": result.get("description", ""),
            "status": result["status"],
            "newest_age_days": result.get("newest_age_days"),
            "episodes": result["entries"],
        })
        report("POD", feed, result)

    pod_output = {
        "generated_at": now,
        "source": "podcast_rss",
        "feeds_count": len(pod_results),
        "total_episodes": sum(len(r["episodes"]) for r in pod_results),
        "unhealthy": [r["feed_name"] for r in pod_results if r["status"] != "ok"],
        "podcasts": pod_results,
    }
    OUTPUT_PODCASTS.write_text(json.dumps(pod_output, ensure_ascii=False, indent=2))

    # ── Summary ───────────────────────────────────────────────────────
    rss_total = rss_output["total_entries"]
    pod_total = pod_output["total_episodes"]
    print(f"\nRSS: {rss_total} entries from {len(rss_feeds)} feeds")
    print(f"Podcasts: {pod_total} episodes from {len(pod_feeds)} feeds")
    print(f"Output: {OUTPUT_RSS}, {OUTPUT_PODCASTS}")

    # ── Health gate: 死源/停更源必须显式失败，不能静默 ────────────────
    if failures:
        print(f"\n⚠️  {len(failures)} 个源不健康（stale/empty/error）：")
        for kind, name, why in failures:
            print(f"    - [{kind}] {name}: {why}")
        print("    → 这些源在 digest 里必须标注缺口，并尽快替换（见 sources.json _removed）")
        return 1
    print("\n✅ 全部源健康")
    return 0


if __name__ == "__main__":
    sys.exit(main())
