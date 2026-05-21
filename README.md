# Carmen Briefing

A fully automated daily audio news briefing delivered as a podcast-style MP3 every morning.
Built with GitHub Actions, Google Gemini, and edge-tts. No server required.

---

## Episode structure

| Segment | Duration | Content |
|---|---|---|
| Intro jingle | ~5–10 s | Audio asset from Freesound |
| Carmen's intro | ~30 s | Greeting + story preview |
| Geopolitical segment | ~4–6 min | 2–3 stories: what happened, why it matters, what to watch |
| Markets segment | ~4 min | Watchlist company news, prioritised by tier |
| Closing | ~30 s | Sign-off |
| **Total** | **~10 min** | |

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

## Timezone adjustment

The cron schedule runs at **06:00 UTC**:

| Season | UTC offset | Local time | Action needed |
|---|---|---|---|
| CET (winter) | UTC+1 | 07:00 ✓ | None — default cron `0 6 * * *` |
| CEST (summer) | UTC+2 | 08:00 | Change cron to `0 5 * * *` |

**When to change:**
- **Last Sunday of March** (CEST begins) → edit `.github/workflows/daily_briefing.yml`, change cron to `0 5 * * *`
- **Last Sunday of October** (CET begins) → revert cron to `0 6 * * *`

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

## Architecture

```
GitHub Actions (cron 06:00 UTC)
  ├── fetch_geo_news.py    → tmp/geo_stories.json
  ├── fetch_market_news.py → tmp/market_stories.json
  ├── generate_script.py   → tmp/script.txt + tmp/segments.json
  ├── synthesise_audio.py  → tmp/segments/segment_NN.mp3
  ├── stitch_audio.py      → episodes/YYYY-MM-DD.mp3
  └── manage_archive.py    → episodes/index.json (keeps 3 newest)
         ↓
    git push → GitHub Pages
         ↓
    iPhone PWA at github.io/carmen-briefing/web/
```
