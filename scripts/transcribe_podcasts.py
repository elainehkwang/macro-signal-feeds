#!/usr/bin/env python3
"""
Transcribe podcast episodes via OpenAI Whisper API (disabled by default).

Reads feeds/feed-podcasts.json, identifies episodes without transcripts,
submits audio URLs to OpenAI Whisper, polls for completion, writes
transcripts back to the feed JSON.

Usage:
    python scripts/transcribe_podcasts.py --limit 1          # transcribe 1 episode
    python scripts/transcribe_podcasts.py --dry-run           # show candidates only
    python scripts/transcribe_podcasts.py --limit 3 --force  # skip relevance filter

Env:
    OPENAI_API_KEY — required. Set in ~/.macro-signal/.env or environment.
                     Get key at https://platform.openai.com/api-keys
    Cost: ~$0.006/minute. 1-hour podcast ≈ $0.36.

Config (in sources.json):
    "transcription": {
        "enabled": false,           # set to true to activate in GitHub Action
        "default_limit": 1,         # max episodes per run
        "poll_interval_seconds": 15,
        "max_wait_seconds": 3600,
        "relevance_keywords": [     # only transcribe episodes matching these
            "macro", "inflation", "fed", "fiscal", "liquidity",
            "oil", "energy", "china", "japan", "europe", "trade",
            "tariff", "geopolitics", "sanctions", "commodity",
            "gold", "treasury", "bond", "yield", "credit",
            "recession", "growth", "employment", "wage",
            "ai", "semiconductor", "capex", "infrastructure"
        ]
    }

Limitations:
    - Requires OPENAI_API_KEY (paid, ~$0.36/hr of audio)
    - Audio files must be publicly accessible (podcast feeds are)
    - Whisper has a 25MB file size limit; episodes >~40 min may need chunking
"""

import argparse, json, os, re, sys, time, uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent

FEED_PATH = ROOT_DIR / "feeds" / "feed-podcasts.json"
SOURCES_PATH = ROOT_DIR / "sources.json"

OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"

UA = "Mozilla/5.0 (compatible; macro-signal-feeds/1.0; +https://github.com/elaine/macro-signal-feeds)"

DEFAULT_CONFIG = {
    "enabled": False,
    "default_limit": 1,
    "poll_interval_seconds": 15,
    "max_wait_seconds": 3600,
    "relevance_keywords": [
        "macro", "inflation", "fed", "fiscal", "liquidity",
        "oil", "energy", "china", "japan", "europe", "trade",
        "tariff", "geopolitics", "commodity", "gold", "treasury",
        "bond", "yield", "credit", "recession", "growth",
    ],
}


def log(message):
    print(message, file=sys.stderr)


def load_json(path, default=None):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_audio_url(url):
    """Resolve podcast enclosure URLs through tracking redirects (Megaphone/Libsyn)."""
    try:
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
            resp = client.head(url)
            if resp.status_code >= 400:
                resp = client.get(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
            return str(resp.url)
    except Exception as exc:
        log(f"  redirect resolution failed: {exc}")
        return url


def text_blob(item):
    """Build searchable text from episode metadata for relevance matching."""
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("channel") or ""),
        str(item.get("feed_name") or ""),
        str(item.get("description") or ""),
    ]).lower()


def is_relevant(item, keywords):
    """Check if episode matches any relevance keyword with word-boundary matching."""
    blob = text_blob(item)
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", blob):
            return True
    return False


def find_candidates(podcasts, config, force=False):
    """Return list of (index, item) for episodes that should be transcribed."""
    keywords = config.get("relevance_keywords", DEFAULT_CONFIG["relevance_keywords"])
    candidates = []
    skipped = []

    for i, pd in enumerate(podcasts):
        for j, ep in enumerate(pd.get("episodes", [])):
            if ep.get("transcript"):
                skipped.append((ep, "already has transcript"))
                continue
            if not ep.get("audio_url"):
                skipped.append((ep, "missing audio_url"))
                continue
            if not force and not is_relevant(ep, keywords):
                skipped.append((ep, "not relevant"))
                continue
            candidates.append((i, j, ep, "relevant" if not force else "force"))

    return candidates, skipped


def transcribe_whisper(api_key, audio_url, timeout=600):
    """Submit audio to OpenAI Whisper, return transcript text."""
    resolved_url = resolve_audio_url(audio_url)
    log(f"  resolved URL: {resolved_url[:80]}...")

    # Download audio first (Whisper API accepts file uploads directly)
    log("  downloading audio...")
    with httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": UA}) as client:
        audio_resp = client.get(resolved_url)
        audio_resp.raise_for_status()
        log(f"  downloaded {len(audio_resp.content)} bytes")

    # Submit to Whisper
    log("  submitting to Whisper...")
    files = {
        "file": ("audio.mp3", audio_resp.content, "audio/mpeg"),
    }
    data = {
        "model": "whisper-1",
        "response_format": "text",
        "language": "en",
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(OPENAI_TRANSCRIPTION_URL, headers=headers, files=files, data=data)
        resp.raise_for_status()
        return resp.text.strip()


def main():
    parser = argparse.ArgumentParser(description="Transcribe podcast episodes via OpenAI Whisper")
    parser.add_argument("--limit", type=int, default=None, help="Max episodes to transcribe")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates, don't call API")
    parser.add_argument("--force", action="store_true", help="Skip relevance filter, transcribe all")
    args = parser.parse_args()

    # Load config
    sources = load_json(SOURCES_PATH, {})
    config = sources.get("transcription", {})

    if not config.get("enabled", False) and not args.dry_run:
        log("Transcription is disabled in sources.json. Set 'transcription.enabled: true' to enable.")
        log("Dry-run mode: use --dry-run to preview candidates.")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        log("OPENAI_API_KEY not set. Get one at https://platform.openai.com/api-keys")
        log("Cost: ~$0.006/min (~$0.36 for 1-hour episode).")
        return

    # Load feed
    feed = load_json(FEED_PATH, {"podcasts": []})
    podcasts = feed.get("podcasts", [])

    limit = args.limit or config.get("default_limit", 1)

    # Find candidates
    candidates, skipped = find_candidates(podcasts, config, force=args.force)
    log(f"Candidates: {len(candidates)}, Skipped: {len(skipped)}, Limit: {limit}")

    for pd_i, ep_i, ep, reason in candidates[:limit]:
        log(f"  {'✅' if not args.dry_run else '📋'} {ep.get('channel', '?')} | {ep.get('title', '?')[:80]} ({reason})")

    if args.dry_run:
        if skipped:
            log("\nSkipped (first 10):")
            for ep, reason in skipped[:10]:
                log(f"  ⊘ {ep.get('channel', '?')[:20]} | {ep.get('title', '?')[:60]} ({reason})")
        return

    if not candidates:
        log("No candidates to transcribe.")
        return

    # Transcribe
    changed = 0
    for pd_i, ep_i, ep, reason in candidates[:limit]:
        channel = ep.get("channel", "?")
        title = ep.get("title", "?")[:80]
        audio_url = ep.get("audio_url", "")

        log(f"Transcribing: {channel} | {title}")
        try:
            transcript = transcribe_whisper(api_key, audio_url)
        except Exception as exc:
            feed["podcasts"][pd_i]["episodes"][ep_i]["transcript_error"] = str(exc)
            log(f"  ❌ {exc}")
            continue

        feed["podcasts"][pd_i]["episodes"][ep_i]["transcript"] = transcript
        feed["podcasts"][pd_i]["episodes"][ep_i]["transcript_source"] = "openai_whisper"
        changed += 1
        log(f"  ✅ {len(transcript)} chars")

    if changed:
        write_json(FEED_PATH, feed)
        log(f"\nSaved {changed} transcript(s) to {FEED_PATH}")
    else:
        log("\nNo transcripts added.")


if __name__ == "__main__":
    main()
