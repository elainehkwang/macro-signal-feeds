# macro-signal-feeds

Centralized Tier 2 macro signal feed repository — RSS/Substack and podcasts from analysts with skin in the game.

Built on the [AI Signal](https://github.com/Benboerba620/ai-signal) architecture, simplified for single-user use.

## Architecture

```
sources.json              — Curated RSS + podcast source list
  ↓
GitHub Action             — Daily 22:00 UTC (6 AM HKT)
  ↓
| `scripts/generate_feeds.py` | One script, RSS + podcasts |
| `scripts/transcribe_podcasts.py` | OpenAI Whisper transcription (disabled by default) |
  ↓
feeds/feed-*.json         — Public JSON (committed to repo)
  ↓
Agent-side prepare_macro.py — Reads Tier 2 JSON, remixes into macro digest
```

## Feed Files

| File | Content |
|------|---------|
| `feeds/feed-rss.json` | Latest posts from 10 RSS/Substack feeds |
| `feeds/feed-podcasts.json` | Latest episodes from 5 macro podcasts |

## Running Locally

```bash
pip install httpx
python scripts/generate_feeds.py
```

## Data Sources

### RSS/Substack (10 feeds)

Lyn Alden, Doomberg, Gavekal Research, BIS (Working Papers + All Publications), CFR Brad Setser, Michael Howell Capital Wars, Adam Tooze, SemiAnalysis, Commodity Context.

### Podcasts (5 feeds)

Macro Voices, Capital Allocators, Invest Like the Best, Macro Musings, Goldman Sachs Exchanges.

## X/Twitter

Not currently fetched. Nitter instances are unreliable. X API v2 Basic ($100/mo) is the path forward. 16 accounts are pre-configured in `sources.json` under `_x_accounts_disabled`.

## vs AI Signal — What We Stripped

| AI Signal has | We don't | Why |
|--------------|----------|-----|
| `prepare_digest.py` | Inline in prepare_macro.py | Single-user, no dedup needed |
| `deliver.py` | Cron `deliver: weixin` | Built-in delivery |
| `mark_delivered.py` | Not needed | Daily fresh snapshot |
| `generate_summaries.py` | Agent remixes directly | LLM does the work |
| `transcribe_*.py` | Agent on-demand | No API cost until needed |
| 4 generator scripts | 1 `generate_feeds.py` | Unified RSS parser |

## License

MIT
