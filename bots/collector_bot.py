"""
Collector Bot (collector_bot.py)
Role: Collect trends/tools/case studies + calculate quality scores + apply discard rules
Execution: Daily at 07:00 (called by scheduler)
"""
import json
import logging
import os
import re
import hashlib
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'collector.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Corner types
CORNER_TYPES = {
    'easy_guide': 'HowTo',
    'hidden_gems': 'DeepDive',
    'vibe_report': 'CaseStudy',
    'fact_check': 'FactCheck',
    'one_cut': 'QuickTake',
}

# Topic type ratio: evergreen 50%, trending 30%, personality 20%
TOPIC_RATIO = {'evergreen': 0.5, 'trending': 0.3, 'personality': 0.2}

# Tech/engineering relevance keywords
TECH_RELEVANCE_KEYWORDS = [
    'ai', 'artificial intelligence', 'machine learning', 'deep learning',
    'cloud', 'devops', 'programming', 'api', 'database', 'security',
    'web', 'mobile', 'frontend', 'backend', 'fullstack', 'microservices',
    'kubernetes', 'docker', 'terraform', 'ci/cd', 'python', 'javascript',
    'typescript', 'rust', 'go', 'java', 'react', 'node', 'linux',
    'open source', 'data engineering', 'data science', 'llm', 'gpt',
    'neural network', 'nlp', 'computer vision', 'blockchain', 'crypto',
    'serverless', 'infrastructure', 'monitoring', 'observability',
    'software', 'developer', 'engineering', 'algorithm', 'framework',
    'library', 'sdk', 'cli', 'automation', 'testing', 'deployment',
    'agile', 'scrum', 'saas', 'paas', 'iaas', 'networking', 'cybersecurity',
    'encryption', 'authentication', 'oauth', 'graphql', 'rest',
    'sql', 'nosql', 'redis', 'postgresql', 'mongodb', 'elasticsearch',
    'aws', 'azure', 'gcp', 'github', 'gitlab', 'vscode',
]


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_published_titles() -> list[str]:
    """Load title list from publication history (for similarity comparison)."""
    titles = []
    published_dir = DATA_DIR / 'published'
    for f in published_dir.glob('*.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if 'title' in data:
                titles.append(data['title'])
        except Exception:
            pass
    return titles


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_duplicate(title: str, published_titles: list[str], threshold: float = 0.8) -> bool:
    for pub_title in published_titles:
        if title_similarity(title, pub_title) >= threshold:
            return True
    return False


def calc_freshness_score(published_at: datetime | None, max_score: int = 20) -> int:
    """Freshness score based on publication time (full marks within 24h, 0 after 7 days)."""
    if published_at is None:
        return max_score // 2
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = (now - published_at).total_seconds() / 3600
    if age_hours <= 24:
        return max_score
    elif age_hours >= 168:
        return 0
    else:
        ratio = 1 - (age_hours - 24) / (168 - 24)
        return int(max_score * ratio)


def calc_topic_relevance(text: str, rules: dict) -> int:
    """Tech/engineering topic relevance score."""
    max_score = rules.get('scoring', {}).get('topic_relevance', {}).get('max', 30)
    text_lower = text.lower()
    matched = sum(1 for kw in TECH_RELEVANCE_KEYWORDS if kw in text_lower)
    score = min(matched * 6, max_score)
    return score


def calc_source_trust(source_url: str, rules: dict) -> tuple[int, str]:
    """Source trust score + level."""
    trust_cfg = rules['scoring']['source_trust']
    high_src = trust_cfg.get('high_sources', [])
    low_src = trust_cfg.get('low_sources', [])
    url_lower = source_url.lower()
    for s in low_src:
        if s in url_lower:
            return trust_cfg['levels']['low'], 'low'
    for s in high_src:
        if s in url_lower:
            return trust_cfg['levels']['high'], 'high'
    return trust_cfg['levels']['medium'], 'medium'


def calc_monetization(text: str, rules: dict) -> int:
    """Monetization potential score."""
    keywords = rules['scoring']['monetization']['keywords']
    matched = sum(1 for kw in keywords if kw in text)
    return min(matched * 5, rules['scoring']['monetization']['max'])


def is_evergreen(title: str, rules: dict) -> bool:
    evergreen_kws = rules.get('evergreen_keywords', [])
    return any(kw in title for kw in evergreen_kws)


def apply_discard_rules(item: dict, rules: dict, published_titles: list[str]) -> str | None:
    """
    Apply discard rules. Returns discard reason (None if passed).
    """
    title = item.get('topic', '')
    text = title + ' ' + item.get('description', '')
    discard_rules = rules.get('discard_rules', [])

    for rule in discard_rules:
        rule_id = rule['id']

        if rule_id == 'no_topic_relevance':
            if item.get('topic_relevance_score', 0) == 0:
                return 'No tech/engineering relevance'

        elif rule_id == 'unverified_source':
            if item.get('source_trust_level') == 'unknown':
                return 'Unknown source'

        elif rule_id == 'duplicate_topic':
            threshold = rule.get('similarity_threshold', 0.8)
            if is_duplicate(title, published_titles, threshold):
                return f'Similar to previously published topic (>={threshold*100:.0f}%)'

        elif rule_id == 'stale_trend':
            if not item.get('is_evergreen', False):
                max_days = rule.get('max_age_days', 7)
                pub_at = item.get('published_at')
                if pub_at:
                    if isinstance(pub_at, str):
                        try:
                            pub_at = datetime.fromisoformat(pub_at)
                        except Exception:
                            pub_at = None
                    if pub_at:
                        if pub_at.tzinfo is None:
                            pub_at = pub_at.replace(tzinfo=timezone.utc)
                        age_days = (datetime.now(timezone.utc) - pub_at).days
                        if age_days > max_days:
                            return f'Stale trend ({age_days} days old)'

        elif rule_id == 'promotional':
            kws = rule.get('keywords', [])
            if any(kw in text for kw in kws):
                return 'Promotional/advertising content'

        elif rule_id == 'clickbait':
            patterns = rule.get('patterns', [])
            if any(p in text for p in patterns):
                return 'Clickbait topic'

    return None


def assign_corner(item: dict, topic_type: str) -> str:
    """Assign a corner to the topic."""
    title = item.get('topic', '').lower()
    source = item.get('source', 'rss').lower()

    howto_keywords = [
        'guide', 'tutorial', 'how to', 'how-to', 'getting started',
        'introduction', 'basics', 'setup', 'install', 'walkthrough',
        'step by step', 'step-by-step', 'beginner', 'learn', 'crash course',
        'cheat sheet', 'cheatsheet', 'quickstart', 'quick start',
        'best practices', 'tips', 'tricks',
    ]

    if topic_type == 'evergreen':
        if any(kw in title for kw in howto_keywords):
            return 'HowTo'
        return 'DeepDive'
    elif topic_type == 'trending':
        if source in ['github', 'product_hunt']:
            return 'DeepDive'
        return 'HowTo'
    else:  # personality
        return 'CaseStudy'


def calculate_quality_score(item: dict, rules: dict) -> int:
    """Calculate quality score (0-100)."""
    text = item.get('topic', '') + ' ' + item.get('description', '')
    source_url = item.get('source_url', '')
    pub_at_str = item.get('published_at')
    pub_at = None
    if pub_at_str:
        try:
            pub_at = datetime.fromisoformat(pub_at_str)
        except Exception:
            pass

    relevance_score = calc_topic_relevance(text, rules)
    fresh_score = calc_freshness_score(pub_at)
    # search_demand: use real value after pytrends integration (default 10 for now)
    search_score = item.get('search_demand_score', 10)
    trust_score, trust_level = calc_source_trust(source_url, rules)
    mono_score = calc_monetization(text, rules)

    item['topic_relevance_score'] = relevance_score
    item['source_trust_level'] = trust_level
    item['is_evergreen'] = is_evergreen(item.get('topic', ''), rules)

    total = relevance_score + fresh_score + search_score + trust_score + mono_score
    return min(total, 100)


# --- Collection functions per source ---

def collect_google_trends() -> list[dict]:
    """Google Trends (pytrends) -- daily trending keywords."""
    items = []
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=0, timeout=(10, 30))
        trending_df = pytrends.trending_searches(pn='united_states')
        for keyword in trending_df[0].tolist()[:20]:
            items.append({
                'topic': keyword,
                'description': f'Google Trends trending keyword: {keyword}',
                'source': 'google_trends',
                'source_url': f'https://trends.google.com/trends/explore?q={keyword}&geo=US',
                'published_at': datetime.now(timezone.utc).isoformat(),
                'search_demand_score': 15,
                'topic_type': 'trending',
            })
    except Exception as e:
        logger.warning(f"Google Trends collection failed: {e}")
    return items


def collect_github_trending(sources_cfg: dict) -> list[dict]:
    """GitHub Trending scraping."""
    items = []
    cfg = sources_cfg.get('github_trending', {})
    languages = cfg.get('languages', [''])
    since = cfg.get('since', 'daily')

    for lang in languages:
        url = f"https://github.com/trending/{lang}?since={since}"
        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(resp.text, 'lxml')
            repos = soup.select('article.Box-row')
            for repo in repos[:10]:
                name_el = repo.select_one('h2 a')
                desc_el = repo.select_one('p')
                stars_el = repo.select_one('a[href*="stargazers"]')
                if not name_el:
                    continue
                repo_path = name_el.get('href', '').strip('/')
                topic = repo_path.replace('/', ' / ')
                desc = desc_el.get_text(strip=True) if desc_el else ''
                stars = stars_el.get_text(strip=True) if stars_el else '0'
                items.append({
                    'topic': topic,
                    'description': desc,
                    'source': 'github',
                    'source_url': f'https://github.com/{repo_path}',
                    'published_at': datetime.now(timezone.utc).isoformat(),
                    'search_demand_score': 12,
                    'topic_type': 'trending',
                    'extra': {'stars': stars},
                })
        except Exception as e:
            logger.warning(f"GitHub Trending collection failed ({lang}): {e}")
    return items


def collect_hacker_news(sources_cfg: dict) -> list[dict]:
    """Hacker News API top stories."""
    items = []
    cfg = sources_cfg.get('hacker_news', {})
    api_url = cfg.get('url', 'https://hacker-news.firebaseio.com/v0/topstories.json')
    top_n = cfg.get('top_n', 30)
    try:
        resp = requests.get(api_url, timeout=10)
        story_ids = resp.json()[:top_n]
        for sid in story_ids:
            story_resp = requests.get(
                f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=5
            )
            story = story_resp.json()
            if not story or story.get('type') != 'story':
                continue
            pub_ts = story.get('time')
            pub_at = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if pub_ts else None
            items.append({
                'topic': story.get('title', ''),
                'description': story.get('url', ''),
                'source': 'hacker_news',
                'source_url': story.get('url', f'https://news.ycombinator.com/item?id={sid}'),
                'published_at': pub_at,
                'search_demand_score': 8,
                'topic_type': 'trending',
            })
    except Exception as e:
        logger.warning(f"Hacker News collection failed: {e}")
    return items


def collect_product_hunt(sources_cfg: dict) -> list[dict]:
    """Product Hunt RSS."""
    items = []
    cfg = sources_cfg.get('product_hunt', {})
    rss_url = cfg.get('rss_url', 'https://www.producthunt.com/feed')
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:15]:
            pub_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            items.append({
                'topic': entry.get('title', ''),
                'description': entry.get('summary', ''),
                'source': 'product_hunt',
                'source_url': entry.get('link', ''),
                'published_at': pub_at,
                'search_demand_score': 10,
                'topic_type': 'trending',
            })
    except Exception as e:
        logger.warning(f"Product Hunt collection failed: {e}")
    return items


def collect_rss_feeds(sources_cfg: dict) -> list[dict]:
    """Collect configured RSS feeds."""
    items = []
    feeds = sources_cfg.get('rss_feeds', [])
    for feed_cfg in feeds:
        url = feed_cfg.get('url', '')
        trust = feed_cfg.get('trust_level', 'medium')
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pub_at = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                items.append({
                    'topic': entry.get('title', ''),
                    'description': entry.get('summary', '') or entry.get('description', ''),
                    'source': 'rss',
                    'source_name': feed_cfg.get('name', ''),
                    'source_url': entry.get('link', ''),
                    'published_at': pub_at,
                    'search_demand_score': 8,
                    'topic_type': 'trending',
                    '_trust_override': trust,
                })
        except Exception as e:
            logger.warning(f"RSS collection failed ({url}): {e}")
    return items


def extract_affiliate_keywords(topic: str, description: str) -> list[str]:
    """Extract affiliate search keywords from topic content."""
    product_keywords = [
        'microphone', 'webcam', 'keyboard', 'mouse', 'monitor', 'laptop',
        'earbuds', 'headset', 'external drive', 'usb hub', 'desk', 'chair',
        'book', 'speaker', 'tablet', 'charger', 'cable', 'adapter',
    ]
    text = (topic + ' ' + description).lower()
    found = [kw for kw in product_keywords if kw in text]
    if not found:
        # If it's a tools/software article, use default keywords
        if any(kw in text for kw in ['tool', 'app', 'software', 'service', 'platform']):
            found = ['keyboard', 'mouse']
    return found


def save_discarded(item: dict, reason: str):
    """Save discarded topic to log."""
    discard_dir = DATA_DIR / 'discarded'
    discard_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    log_file = discard_dir / f'{today}_discarded.jsonl'
    record = {**item, 'discard_reason': reason, 'discarded_at': datetime.now().isoformat()}
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def save_topic(item: dict):
    """Save a passing topic to data/topics/."""
    topics_dir = DATA_DIR / 'topics'
    topics_dir.mkdir(exist_ok=True)
    topic_id = hashlib.md5(item['topic'].encode()).hexdigest()[:8]
    filename = f"{datetime.now().strftime('%Y%m%d')}_{topic_id}.json"
    with open(topics_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(item, f, ensure_ascii=False, indent=2)


def run():
    logger.info("=== Collector bot started ===")
    rules = load_config('quality_rules.json')
    sources_cfg = load_config('sources.json')
    published_titles = load_published_titles()
    min_score = rules.get('min_score', 70)

    # Collect from all sources
    all_items = []
    all_items += collect_google_trends()
    all_items += collect_github_trending(sources_cfg)
    all_items += collect_product_hunt(sources_cfg)
    all_items += collect_hacker_news(sources_cfg)
    all_items += collect_rss_feeds(sources_cfg)

    logger.info(f"Collection complete: {len(all_items)} items")

    passed = []
    discarded_count = 0

    for item in all_items:
        if not item.get('topic'):
            continue

        # Trust level override (per RSS feed config)
        trust_override = item.pop('_trust_override', None)
        if trust_override:
            trust_levels = rules['scoring']['source_trust']['levels']
            item['source_trust_level'] = trust_override
            item['_trust_score'] = trust_levels.get(trust_override, trust_levels['medium'])

        # Calculate quality score
        score = calculate_quality_score(item, rules)
        item['quality_score'] = score

        # Apply discard rules
        discard_reason = apply_discard_rules(item, rules, published_titles)
        if discard_reason:
            save_discarded(item, discard_reason)
            discarded_count += 1
            logger.debug(f"Discarded: [{score}pts] {item['topic']} -- {discard_reason}")
            continue

        if score < min_score:
            save_discarded(item, f'Quality score too low ({score}pts < {min_score}pts)')
            discarded_count += 1
            logger.debug(f"Discarded: [{score}pts] {item['topic']}")
            continue

        # Assign corner
        topic_type = item.get('topic_type', 'trending')
        corner = assign_corner(item, topic_type)
        item['corner'] = corner

        # Extract affiliate keywords
        item['affiliate_keywords'] = extract_affiliate_keywords(
            item.get('topic', ''), item.get('description', '')
        )

        # Trending age display
        pub_at_str = item.get('published_at')
        if pub_at_str:
            try:
                pub_at = datetime.fromisoformat(pub_at_str)
                if pub_at.tzinfo is None:
                    pub_at = pub_at.replace(tzinfo=timezone.utc)
                hours_ago = int((datetime.now(timezone.utc) - pub_at).total_seconds() / 3600)
                item['trending_since'] = f'{hours_ago}h ago' if hours_ago < 24 else f'{hours_ago // 24}d ago'
            except Exception:
                item['trending_since'] = 'unknown'

        # Clean up sources field
        item['sources'] = [{'url': item.get('source_url', ''), 'title': item.get('topic', ''),
                             'date': item.get('published_at', '')}]
        item['related_keywords'] = item.get('topic', '').split()[:5]

        passed.append(item)

    # Balance evergreen/trending/personality ratio
    total_target = len(passed)
    evergreen = [i for i in passed if i.get('is_evergreen')]
    trending = [i for i in passed if not i.get('is_evergreen') and i.get('topic_type') == 'trending']
    personality = [i for i in passed if i.get('topic_type') == 'personality']

    logger.info(
        f"Passed: {len(passed)} items (evergreen {len(evergreen)}, trending {len(trending)}, "
        f"personality {len(personality)}) / Discarded: {discarded_count} items"
    )

    # Save topics
    for item in passed:
        save_topic(item)
        logger.info(f"[{item['quality_score']}pts][{item['corner']}] {item['topic']}")

    logger.info("=== Collector bot finished ===")
    return passed


if __name__ == '__main__':
    run()
