# Carmen Briefing

A fully automated daily audio news briefing hosted by Carmen — a daily morning podcast covering
global strategic affairs, AI & tech, and company markets news.
Episodes are generated on the Hetzner VPS at 06:00 CEST (Denmark local time), Monday–Friday.

---

## Episode schedule

Episodes run **Monday–Friday only**. No episodes are generated on weekends.

| Day | Runs | Fetch window | Duration | Special rules |
|---|---|---|---|---|
| Monday | Yes | **72 hours** | Full (~10 min) | Extended window covers Fri–Mon news gap |
| Tuesday | Yes | 24 hours | **Short (~6 min)** | Shortened format |
| Wednesday | Yes | 24 hours | **Short (~6 min)** | Shortened format + reduced Tier 2/3 debuff |
| Thursday | Yes | 24 hours | **Short (~6 min)** | Shortened format |
| Friday | Yes | 24 hours | **Short (~6 min)** | Shortened format |
| Saturday | No | — | — | |
| Sunday | No | — | — | |

### Monday: 72-hour fetch window

Both `fetch_geo_news.py` and `fetch_market_news.py` detect Monday at runtime and extend
the article lookback window from 24h to **72 hours**, covering Friday through Monday morning
so no weekend news is missed.

### Tuesday–Friday: 6-minute shortened episodes

On these days, `generate_script.py` applies the following limits before generating the script:

- **Global Strategic Affairs**: max 2 stories
- **AI & Tech**: max 2 stories
- **Markets**: candidate pool capped at 7 (vs 15 on Mondays)

The time budget passed to the LLM:

```
Total target: 6 minutes (360 seconds)
  Intro + closing:          ~60 s  (fixed)
  Global Strategic Affairs: N stories × ~90 s
  AI & Tech:                N stories × ~90 s
  Markets:                  remaining budget (minimum 60 s)
```

Carmen is instructed to write tighter sentences and stop when the budget is spent.
Story counts are capped; no padding is added.

### Wednesday: reduced tier debuff in the markets segment

On Wednesdays, the tier penalty for Tier 2 and Tier 3 companies is reduced by a
`tier_debuff_multiplier = 0.4`, allowing strong lower-tier stories to compete with
quieter Tier 1 stories.

**Tier bonus values (used in `watchlist.prioritise_stories`):**

| Tier | Normal | Wednesday (0.4×) |
|---|---|---|
| Tier 1 | 30 | 30 (unchanged) |
| Tier 2 | 20 | 26 |
| Tier 3 | 10 | 22 |

The `0.4` multiplier is tunable. If Wednesday episodes show too many or too few
Tier 2/3 stories, adjust the value in `generate_script.py`:

```python
tier_debuff = 0.4 if is_wednesday else 1.0
market_stories_sorted = prioritise_stories(market_stories, tier_debuff_multiplier=tier_debuff)
```

This debuff applies to the **markets segment only**. Macro and tech segment tier
priorities are unaffected on Wednesdays.

---

## Episode structure

**Monday (full):**

| Segment | Duration | Content |
|---|---|---|
| Intro jingle | ~5–10 s | Audio asset from Freesound |
| Carmen's intro | ~30 s | Greeting + story preview |
| Global Strategic Affairs | ~3–5 min | 2–3 stories |
| AI & Tech | ~3–5 min | 2–3 stories |
| Markets | ~4 min | Watchlist company news, prioritised by tier |
| Closing | ~30 s | Sign-off |
| **Total** | **~10 min** | |

**Tuesday–Friday (short):**

| Segment | Duration | Content |
|---|---|---|
| Intro jingle | ~5–10 s | Audio asset from Freesound |
| Carmen's intro | ~20 s | Brief preview |
| Global Strategic Affairs | ~90 s | 1–2 stories |
| AI & Tech | ~90 s | 1–2 stories |
| Markets | ~60–120 s | 1–3 companies |
| Closing | ~20 s | Brief sign-off |
| **Total** | **~6 min** | |

---

## One-time setup

### 1. Create the GitHub repository

```
git init
git remote add origin https://github.com/Stefannormann/carmen-briefing.git
git add .
git commit -m "Initial setup"
git push -u origin main
```

### 2. Add GitHub Secrets

In your repository: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `FREESOUND_API_KEY` | *(Optional)* Freesound API key for full-quality downloads |

### 3. Set Freesound sound IDs

Edit `scripts/download_audio_assets.py` and replace the two placeholder values:

```python
JINGLE_SOUND_ID     = "YOUR_JINGLE_ID_HERE"
TRANSITION_SOUND_ID = "YOUR_TRANSITION_ID_HERE"
```

Browse [freesound.org](https://freesound.org), filter by **CC0** licence, and paste the
numeric ID from the sound's URL (e.g. `freesound.org/s/636051/` → ID is `636051`).

### 4. Enable GitHub Pages

In your repository: **Settings → Pages**
- Source: **GitHub Actions**
- Click **Save**

### 5. Trigger the first run

In your repository: **Actions → Generate Daily Briefing → Run workflow**

The first run downloads audio assets, generates today's episode, commits it, and deploys the web app.

---

## Adding the app to your iPhone home screen

1. Open Safari and go to your GitHub Pages URL:
   `https://Stefannormann.github.io/carmen-briefing/web/`
2. Tap the **Share** button (box with arrow)
3. Tap **Add to Home Screen**
4. Tap **Add**

The Carmen icon will appear on your home screen for one-tap morning listening.

---

## Triggering a manual test run

Go to **Actions → Generate Daily Briefing → Run workflow** and click **Run workflow**.
This is useful for testing after configuration changes.

### Dry-run mode (local testing, no API quota used)

```bash
pip install -r requirements.txt

python scripts/fetch_geo_news.py --dry-run
python scripts/fetch_market_news.py --dry-run
python scripts/generate_script.py --dry-run
python scripts/synthesise_audio.py --dry-run
python scripts/stitch_audio.py --dry-run
```

---

## Updating the stock watchlist

Edit `scripts/watchlist.py`. The `WATCHLIST` dict has three tiers:

```python
WATCHLIST = {
    "tier1": [  # Always covered first
        {"name": "NVIDIA", "ticker": "NVDA", "exchange": "NASDAQ"},
        ...
    ],
    "tier2": [...],   # Covered after tier 1
    "tier3": [...],   # Covered if time allows
}
```

**Prioritisation rules:**
- Tier 1 companies always appear first in the markets segment
- Tier 2/3 companies with a Gemini newsworthiness score ≥ 8 are promoted above
  quiet Tier 1 companies (score ≤ 5) — the "traffic exception"
- If the markets segment fills up, the lowest-priority companies are cut first

---

## Cron schedule (VPS — Europe/Helsinki, EEST = UTC+3)

```cron
# Main run: 07:00 EEST = 06:00 CEST (Denmark local time), Mon–Fri only
0 7 * * 1-5 /opt/carmen/run_briefing.sh

# Catch-up: 09:00 EEST (08:00 Denmark), Mon–Fri, only if today's episode is missing
0 9 * * 1-5 [ -f /opt/carmen/episodes/$(date +\%Y-\%m-\%d).mp3 ] || /opt/carmen/run_briefing.sh
```

---

## Geopolitical topic tiers

| Tier | Topics |
|---|---|
| **Tier 1** (always covered) | USA–China, USA–Europe, Tech & AI |
| **Tier 2** (fill-in on quiet days) | USA–Denmark, Europe–China, Supply chains, Energy geopolitics |

---

## Audio asset attribution

| Asset | Freesound ID | Licence | Link |
|---|---|---|---|
| Intro jingle | 273159 — "Podcast Jingle" by plasterbrain | CC0 | https://freesound.org/s/273159/ |
| Transition tone | 333694 — "Thin Bell Ding 3" by Khrinx | CC0 | https://freesound.org/s/333694/ |

---

## Audio quality tuning

All audio parameters are defined as named constants — no magic numbers buried in logic.

### SSML and speech synthesis (`synthesise_audio.py`)

| Constant | Default | Effect |
|---|---|---|
| `CARMEN_RATE` | `-6%` | Speech speed. Increase toward `0%` if too slow, `-10%` for more deliberate pacing. |
| `CARMEN_PITCH` | `+0Hz` | Voice pitch. Leave at `0` unless the voice sounds unnatural. |
| `TRANSITION_BREAK_MS` | `800` | `<break>` pause (ms) injected for any `---TRANSITION---` markers surviving into a segment. |
| `PARAGRAPH_BREAK_MS` | `400` | `<break>` pause (ms) injected at `\n\n` paragraph breaks within a segment. |

### EQ and compression (`stitch_audio.py`)

| Constant | Default | Effect |
|---|---|---|
| `EQ_FREQUENCY` | `100` Hz | Centre frequency of the bass-boost EQ band. |
| `EQ_WIDTH` | `2` octaves | Bandwidth of the boost. Narrower = more focused; wider = broader warmth. |
| `EQ_GAIN_DB` | `+3` dB | Boost amount. Reduce to `1` if the output sounds too muddy. |

### Punctuation formatting (`generate_script.py`)

The `format_for_tts()` function post-processes the LLM script before segmenting:
- Commas after 4+ character words are replaced with em-dashes for longer natural pauses.
- Reveal-style verbs (`is`, `are`, `was`, `means`, `signals`, `suggests`) gain an ellipsis before capitalized words for dramatic effect.
- Sentences longer than 20 words are broken at the first conjunction (`and`, `but`, `which`, `because`, `however`).

These rules run automatically on every episode. To disable one, comment out the relevant `re.sub` call in `format_for_tts()`.

---

## Architecture

```
Hetzner VPS cron (07:00 EEST, Mon–Fri)
  ├── fetch_geo_news.py    --segment strategic  → tmp/strategic_stories.json
  ├── fetch_geo_news.py    --segment tech       → tmp/tech_stories.json
  ├── fetch_market_news.py                      → tmp/market_stories.json
  ├── generate_script.py                        → tmp/script.txt + tmp/segments.json
  ├── synthesise_audio.py                       → tmp/segments/segment_NN.mp3
  ├── stitch_audio.py                           → episodes/YYYY-MM-DD.mp3
  ├── manage_archive.py                         → episodes/index.json (keeps 3 newest)
  └── post_to_dashboard.py                      → dash.stefannormann.com/api/news
         ↓
    nginx serves episodes directly at carmen.stefannormann.com
         ↓
    iPhone PWA
```
