# TechPulse Daily — AI Blog Engine

An AI-powered blog automation system that writes and publishes technical articles.
Trend collection → AI article generation (Gemini API) → Auto-publish to Google Blogger → Affiliate links → Performance analytics.

> **Phase 1 Goal:** Start with one Google Blogger blog, build search presence, and gain AdSense approval.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [API Key Setup](#api-key-setup)
5. [Google OAuth Setup](#google-oauth-setup)
6. [Usage](#usage)
7. [Telegram Commands](#telegram-commands)
8. [Image Modes](#image-modes)
9. [Content Sections](#content-sections)
10. [Cost Estimates](#cost-estimates)
11. [FAQ](#faq)

---

## Architecture

```
Bot Layer (Python)              AI Layer (Gemini API)
──────────────────              ─────────────────────
Collector Bot                    writer_bot.py
  └─ Trend collection             └─ Topic → Gemini → Finished article
  └─ Quality scoring
  └─ Discard rules
          │
          ▼
Publisher ── Linker ── Image Bot
  └─ Safety checks      └─ Editorial images
  └─ Blogger publish
  └─ Search Console
          │
          ▼
Analytics Bot → Telegram reports
run.py → On-demand execution (collect → write → publish)
Scheduler → Automated scheduling (cron / Task Scheduler)
```

### File Structure

```
blog-writer/
├── run.py                  ← Main entry point (collect → write → publish)
├── bots/
│   ├── collector_bot.py    ← Topic collector (GitHub, HN, Product Hunt, RSS)
│   ├── writer_bot.py       ← Article writer (Gemini API)
│   ├── publisher_bot.py    ← Publisher (Blogger API + safety checks)
│   ├── linker_bot.py       ← Affiliate link inserter
│   ├── analytics_bot.py    ← Performance analytics (5 key metrics)
│   ├── image_bot.py        ← Image manager (3 modes)
│   ├── scheduler.py        ← Scheduler + Telegram bot
│   └── article_parser.py   ← Gemini output parser
├── config/
│   ├── blogs.json          ← Blog ID configuration
│   ├── schedule.json       ← Publishing schedule
│   ├── sources.json        ← Collection source list
│   ├── affiliate_links.json← Affiliate link database
│   ├── quality_rules.json  ← Quality scoring rules
│   └── safety_keywords.json← Safety check keywords
├── data/                   ← Runtime data (gitignored)
├── scripts/
│   ├── get_token.py        ← Google OAuth token setup
│   ├── setup.sh            ← Linux/macOS install script
│   └── setup.bat           ← Windows install script
├── environment.yml         ← Conda environment config
├── .env.example            ← Environment variable template
└── requirements.txt        ← pip package list
```

---

## Prerequisites

### Required
- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com/)
- **Conda** (recommended) — [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda
- **Google Account** — For Blogger
- **Gemini API Key** — For AI article generation ([Google AI Studio](https://aistudio.google.com/))

### Optional
- **Telegram Account** — For bot notifications
- **OpenAI API Key** — For auto image generation mode

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/surfsurfmasurf/blog-writer.git
cd blog-writer
```

### 2. Run setup script

**Linux / macOS (auto-detects conda):**

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

The script automatically:
- Creates conda environment (falls back to venv if conda not found)
- Installs packages
- Creates `.env` file
- Creates `data/` and `logs/` directories
- Optionally registers cron job

### 3. Manual install (conda)

```bash
conda env create -f environment.yml
conda activate blog-writer
cp .env.example .env
```

### 4. Manual install (venv)

```bash
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
cp .env.example .env
```

---

## API Key Setup

Edit `.env` and fill in the values:

```env
# ─── Google (required) ──────────────────────────────
GOOGLE_CLIENT_ID=         # From Google Cloud Console
GOOGLE_CLIENT_SECRET=     # From Google Cloud Console
GOOGLE_REFRESH_TOKEN=     # Run scripts/get_token.py to get this
BLOG_MAIN_ID=             # From Blogger dashboard URL

# ─── Gemini API (required) ──────────────────────────
GEMINI_API_KEY=           # From Google AI Studio
GEMINI_MODEL=gemini-2.5-flash  # or gemini-2.0-flash, gemini-2.5-pro

# ─── Telegram (optional) ────────────────────────────
TELEGRAM_BOT_TOKEN=       # From @BotFather
TELEGRAM_CHAT_ID=         # From @userinfobot

# ─── Image Mode ─────────────────────────────────────
IMAGE_MODE=manual          # manual | request | auto

# ─── Search Console (optional) ──────────────────────
BLOG_SITE_URL=            # e.g., https://your-blog.blogspot.com/

# ─── OpenAI (auto mode only) ────────────────────────
OPENAI_API_KEY=
```

### Finding BLOG_MAIN_ID

Go to your Blogger dashboard and check the URL:

```
https://www.blogger.com/blog/posts/XXXXXXXXXXXXXXXXXX
                                   ↑ This number is your BLOG_MAIN_ID
```

---

## Google OAuth Setup

### 1. Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a new project
3. **APIs & Services → Library**: enable these APIs:
   - `Blogger API v3`
   - `Google Search Console API` (optional)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
5. Download `credentials.json` → save to project root (`blog-writer/`)

### 2. Generate Token

```bash
conda activate blog-writer
python scripts/get_token.py
```

Follow the on-screen instructions (works on headless servers — paste redirect URL manually).
Copy the output values to your `.env` file.

---

## Usage

### On-demand execution (recommended)

```bash
conda activate blog-writer

# Full pipeline: collect → write → publish
python run.py

# Test without publishing (write article only)
python run.py --dry-run

# Collection only
python run.py --collect

# Write only (no publishing)
python run.py --write
```

### Scheduler (background auto-publishing)

```bash
conda activate blog-writer
python bots/scheduler.py
```

### Cron setup (Linux)

```bash
crontab -e
# Run daily at 09:00
0 9 * * * source /path/to/conda/etc/profile.d/conda.sh && conda activate blog-writer && cd /path/to/blog-writer && python run.py >> logs/cron.log 2>&1
```

---

## Telegram Commands

### Text Commands

| Command | Description |
|---------|-------------|
| `stop publishing` | Pause auto-publishing |
| `resume publishing` | Resume auto-publishing |
| `show today topics` | List today's collected topics |
| `show pending articles` | List articles pending review |
| `weekly report` | Generate weekly report |
| `image list` | Image production status |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/status` | Bot status + image mode |
| `/approve [N]` | Approve and publish pending article |
| `/reject [N]` | Reject pending article |
| `/images` | Image request queue |
| `/imgpick [N]` | Get image prompt by number |
| `/imgbatch` | Manual batch send |
| `/imgcancel` | Cancel image await |

---

## Content Sections

| Section | Concept | Frequency |
|---------|---------|-----------|
| **HowTo** | Step-by-step tutorials and guides | 2-3x/week |
| **DeepDive** | Hidden gems, underrated tools | 2-3x/week |
| **CaseStudy** | Real-world implementations, lessons learned | 1-2x/week |
| **FactCheck** | Evidence-based analysis (manual review required) | ≤1x/week |
| **QuickTake** | Short, sharp commentary on tech news | 1x/week |

### Safety Checks (auto-publish blocked when)

- All FactCheck section articles
- Crypto/investment/legal risk keywords detected
- Fewer than 2 sources
- Quality score below 75

---

## Cost Estimates

### Gemini API (per article)

| Model | Input Tokens | Output Tokens | Est. Cost/Article |
|-------|-------------|---------------|-------------------|
| gemini-2.5-flash (default) | ~2,000 | ~3,000 | ~$0.002 |
| gemini-2.5-pro | ~2,000 | ~3,000 | ~$0.03 |

### Monthly Cost (1 article/day)

| Component | gemini-2.5-flash | gemini-2.5-pro |
|-----------|-----------------|----------------|
| 30 articles/month | ~$0.06 | ~$0.90 |
| Google Blogger | Free | Free |
| **Total** | **~$0.06/month** | **~$0.90/month** |

> Gemini 2.5 Flash free tier: 15 requests/min, 1,500 requests/day — more than sufficient for this use case.

---

## FAQ

**Q: Where do I get a Gemini API key?**
A: Go to [Google AI Studio](https://aistudio.google.com/) — free tier is sufficient for daily article generation.

**Q: Can I swap in a different LLM?**
A: Yes. Modify `generate_article()` in `bots/writer_bot.py`. Works with OpenAI, Claude, local LLMs, etc.

**Q: Can I use a different blogging platform?**
A: Yes. Replace `publish_to_blogger()` in `publisher_bot.py` with your platform's API (WordPress, Ghost, etc.).

**Q: How do I install on Linux?**
A: Run `./scripts/setup.sh` — it auto-detects conda (or falls back to venv) and optionally registers a cron job.

**Q: The collector isn't finding any topics.**
A: Check that RSS URLs in `config/sources.json` are valid. Google Trends may hit rate limits — check `pytrends` logs.

---

## License

MIT License — free to use, modify, and distribute.
