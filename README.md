# macro-signal-feeds

Centralized Tier 2 macro signal feed repository — X/Twitter, RSS/Substack, and podcasts from analysts with skin in the game.

Built on the [AI Signal](https://github.com/Benboerba620/ai-signal) architecture.

## Architecture

```
sources.json          — Curated source list (X accounts, RSS feeds, podcasts)
  ↓
GitHub Action         — Runs daily at 22:00 UTC (6 AM HKT)
  ↓
scripts/generate_*.py — Fetch each source type, output structured JSON
  ↓
feeds/feed-*.json     — Public JSON feeds (committed to repo)
  ↓
Agent-side prepare_macro.py — Reads feed JSON, remixes into macro signal digest
```

## Feed Files

| File | Content | Update |
|------|---------|--------|
| `feeds/feed-x.json` | Latest tweets from 16 macro analysts | Daily |
| `feeds/feed-rss.json` | Latest posts from 10 RSS/Substack feeds | Daily |
| `feeds/feed-podcasts.json` | Latest episodes from 5 macro podcasts | Daily |

## Running Locally

```bash
pip install httpx
python scripts/generate_x_feed.py
python scripts/generate_rss_feed.py
python scripts/generate_podcast_feed.py
```

## Data Sources

### X/Twitter (16 accounts)

- **US Fiscal**: Luke Gromen, Lyn Alden, Robin Brooks
- **Japan**: Jesper Koll, Richard Katz
- **China Delever**: Michael Pettis, Adam Wolfe
- **Energy**: Rory Johnston, Arjun Murti, Josh Young, Doomberg
- **Global Liquidity**: Brad Setser, Michael Howell
- **AI CAPEX**: Dylan Patel, Pierre Ferragu
- **Europe**: Erik Nielsen

X fetching uses [Nitter](https://github.com/zedeus/nitter) RSS (free, no API key).

### RSS/Substack (10 feeds)

Lyn Alden, Doomberg, Gavekal, BIS, CFR, Capital Wars, Adam Tooze, SemiAnalysis, Commodity Context.

### Podcasts (5 feeds)

Macro Voices, Capital Allocators, Invest Like the Best, Macro Musings, Goldman Sachs Exchanges.

## Limitations

- **Nitter instability**: Nitter instances can be slow or blocked. Multiple instances are tried as fallback, but some accounts may fail.
- **No podcast transcription**: Podcast feeds include metadata + descriptions only. Full transcription requires an API key (OpenAI Whisper) and is left to the Agent on-demand.
- **No DMs/private accounts**: Only public X accounts via Nitter RSS.
- **Paywalled content**: Some Substack posts may be truncated (free tier only).

## License

MIT
