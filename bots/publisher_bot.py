"""
Publisher Bot (publisher_bot.py)
Role: Automatically publish AI-written articles to Blogger
- Markdown to HTML conversion
- Auto-generate table of contents
- Insert AdSense placeholders
- Schema.org Article JSON-LD
- Safety checks (FactCheck / risky keywords / insufficient sources -> manual review)
- Blogger API v3 publishing
- Search Console URL submission
- Telegram notifications
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import markdown
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
TOKEN_PATH = BASE_DIR / 'token.json'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'publisher.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
BLOG_MAIN_ID = os.getenv('BLOG_MAIN_ID', '')

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/webmasters',
]


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


# --- Google Authentication ----------------------------------------

def get_google_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, 'w') as f:
                f.write(creds.to_json())
    if not creds or not creds.valid:
        raise RuntimeError("Google authentication failed. Please run scripts/get_token.py first.")
    return creds


# --- Safety Checks ------------------------------------------------

def check_safety(article: dict, safety_cfg: dict) -> tuple[bool, str]:
    """
    Determine whether manual review is required.
    Returns: (needs_review, reason)
    """
    corner = article.get('corner', '')
    body = article.get('body', '')
    sources = article.get('sources', [])
    quality_score = article.get('quality_score', 100)

    # FactCheck corner always requires manual review
    manual_corners = safety_cfg.get('always_manual_review', ['FactCheck'])
    if corner in manual_corners:
        return True, f'Corner "{corner}" always requires manual review'

    # Risky keyword detection (case-insensitive, word-boundary match)
    all_keywords = (
        safety_cfg.get('crypto_keywords', []) +
        safety_cfg.get('criticism_keywords', []) +
        safety_cfg.get('investment_keywords', []) +
        safety_cfg.get('legal_keywords', [])
    )
    body_lower = body.lower()
    for kw in all_keywords:
        # Use word boundary regex to avoid false positives
        # e.g., "fine" should NOT match "fine-tuning" or "define"
        pattern = r'\b' + re.escape(kw.lower()) + r'\b'
        if re.search(pattern, body_lower):
            return True, f'Risky keyword detected: "{kw}"'

    # Fewer than minimum sources
    min_sources = safety_cfg.get('min_sources_required', 2)
    if len(sources) < min_sources:
        return True, f'Sources: {len(sources)} — at least {min_sources} required'

    # Quality score below threshold
    min_score = safety_cfg.get('min_quality_score_for_auto', 75)
    if quality_score < min_score:
        return True, f'Quality score {quality_score} (minimum for auto-publish: {min_score})'

    return False, ''


# --- HTML Conversion -----------------------------------------------

def markdown_to_html(md_text: str) -> str:
    """Markdown to HTML conversion (with table of contents extension)"""
    md = markdown.Markdown(
        extensions=['toc', 'tables', 'fenced_code', 'attr_list'],
        extension_configs={
            'toc': {
                'title': 'Table of Contents',
                'toc_depth': '2-3',
            }
        }
    )
    html = md.convert(md_text)
    toc = md.toc  # Table of contents HTML
    return html, toc


def insert_adsense_placeholders(html: str) -> str:
    """Insert AdSense placeholders after the second H2 and before the conclusion section"""
    AD_SLOT_1 = '\n<!-- AD_SLOT_1 -->\n'
    AD_SLOT_2 = '\n<!-- AD_SLOT_2 -->\n'

    soup = BeautifulSoup(html, 'lxml')
    h2_tags = soup.find_all('h2')

    # Insert AD_SLOT_1 after the second H2
    if len(h2_tags) >= 2:
        second_h2 = h2_tags[1]
        ad_tag = BeautifulSoup(AD_SLOT_1, 'html.parser')
        second_h2.insert_after(ad_tag)

    # Insert AD_SLOT_2 before the conclusion H2
    for h2 in soup.find_all('h2'):
        if any(kw in h2.get_text() for kw in ['conclusion', 'summary', 'wrap-up', 'final thoughts', 'key takeaways']):
            ad_tag2 = BeautifulSoup(AD_SLOT_2, 'html.parser')
            h2.insert_before(ad_tag2)
            break

    return str(soup)


def build_json_ld(article: dict, blog_url: str = '') -> str:
    """Generate Schema.org Article JSON-LD"""
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.get('title', ''),
        "description": article.get('meta', ''),
        "datePublished": datetime.now(timezone.utc).isoformat(),
        "dateModified": datetime.now(timezone.utc).isoformat(),
        "author": {
            "@type": "Person",
            "name": "TechPulse Daily"
        },
        "publisher": {
            "@type": "Organization",
            "name": "TechPulse Daily",
            "logo": {
                "@type": "ImageObject",
                "url": ""
            }
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": blog_url
        }
    }
    return f'<script type="application/ld+json">\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n</script>'


def build_full_html(article: dict, body_html: str, toc_html: str) -> str:
    """Assemble final HTML: JSON-LD + TOC + body + Korean summary + disclaimer"""
    json_ld = build_json_ld(article)
    disclaimer = article.get('disclaimer', '')
    korean_summary = article.get('korean_summary', '')

    html_parts = [json_ld]
    if toc_html:
        html_parts.append(f'<div class="toc-wrapper">{toc_html}</div>')
    html_parts.append(body_html)

    # Korean summary section
    if korean_summary:
        html_parts.append(
            '<hr style="margin:2em 0;border:none;border-top:2px solid #e0e0e0;" />'
            '<div class="korean-summary" style="background:#f8f9fa;border-left:4px solid #4285f4;'
            'padding:1.2em 1.5em;margin:1.5em 0;border-radius:0 8px 8px 0;'
            'font-family:\'Noto Sans KR\',sans-serif;line-height:1.8;">'
            f'{korean_summary}'
            '</div>'
        )

    if disclaimer:
        html_parts.append(f'<hr/><p class="disclaimer"><small>{disclaimer}</small></p>')

    return '\n'.join(html_parts)


# --- Blogger API ---------------------------------------------------

def publish_to_blogger(article: dict, html_content: str, creds: Credentials) -> dict:
    """Publish article via Blogger API v3"""
    service = build('blogger', 'v3', credentials=creds)
    blog_id = BLOG_MAIN_ID

    labels = [article.get('corner', '')]
    tags = article.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',')]
    labels.extend(tags)
    labels = list(set(filter(None, labels)))

    body = {
        'title': article.get('title', ''),
        'content': html_content,
        'labels': labels,
    }

    result = service.posts().insert(
        blogId=blog_id,
        body=body,
        isDraft=False,
    ).execute()

    return result


def submit_to_search_console(url: str, creds: Credentials):
    """Submit URL to Google Search Console for indexing"""
    try:
        service = build('searchconsole', 'v1', credentials=creds)
        # URL Inspection API (actual indexing request)
        # Note: Blogger sitemap is typically auto-submitted, so this is supplementary
        logger.info(f"Search Console submission: {url}")
        # Indexing API requires a separate service account. Only logging here.
        # Actual index acceleration relies on Blogger's built-in sitemap
    except Exception as e:
        logger.warning(f"Search Console submission failed: {e}")


# --- Telegram -----------------------------------------------------

def send_telegram(text: str, parse_mode: str = 'HTML'):
    """Send Telegram message"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


def send_pending_review_alert(article: dict, reason: str):
    """Send manual review pending alert (Telegram)"""
    title = article.get('title', '(No title)')
    corner = article.get('corner', '')
    preview = article.get('body', '')[:300].replace('<', '&lt;').replace('>', '&gt;')
    msg = (
        f"🔍 <b>[Manual Review Required]</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"Corner: {corner}\n"
        f"Reason: {reason}\n\n"
        f"Preview:\n{preview}...\n\n"
        f"Command: <code>approve</code> or <code>reject</code>"
    )
    send_telegram(msg)


# --- Publish History -----------------------------------------------

def log_published(article: dict, post_result: dict):
    """Save publish history"""
    published_dir = DATA_DIR / 'published'
    published_dir.mkdir(exist_ok=True)
    record = {
        'title': article.get('title', ''),
        'corner': article.get('corner', ''),
        'url': post_result.get('url', ''),
        'post_id': post_result.get('id', ''),
        'published_at': datetime.now(timezone.utc).isoformat(),
        'quality_score': article.get('quality_score', 0),
        'tags': article.get('tags', []),
        'sources': article.get('sources', []),
    }
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{record['post_id']}.json"
    with open(published_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def save_pending_review(article: dict, reason: str):
    """Save article pending manual review"""
    pending_dir = DATA_DIR / 'pending_review'
    pending_dir.mkdir(exist_ok=True)
    record = {**article, 'pending_reason': reason, 'created_at': datetime.now().isoformat()}
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pending.json"
    with open(pending_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return pending_dir / filename


def load_pending_review_file(filepath: str) -> dict:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# --- Main Publish Function -----------------------------------------

def publish(article: dict) -> bool:
    """
    article: Parsed article dict output by OpenClaw blog-writer
    {
        title, meta, slug, tags, corner, body (markdown),
        coupang_keywords, sources, disclaimer, quality_score
    }
    Returns: True (published successfully) / False (pending manual review)
    """
    logger.info(f"Attempting to publish: {article.get('title', '')}")
    safety_cfg = load_config('safety_keywords.json')

    # Safety check
    needs_review, review_reason = check_safety(article, safety_cfg)
    if needs_review:
        logger.warning(f"Pending manual review: {review_reason}")
        save_pending_review(article, review_reason)
        send_pending_review_alert(article, review_reason)
        return False

    # Markdown to HTML
    body_html, toc_html = markdown_to_html(article.get('body', ''))

    # AdSense placeholders
    body_html = insert_adsense_placeholders(body_html)

    # Assemble final HTML
    full_html = build_full_html(article, body_html, toc_html)

    # Google authentication
    try:
        creds = get_google_credentials()
    except RuntimeError as e:
        logger.error(str(e))
        return False

    # Publish to Blogger
    try:
        post_result = publish_to_blogger(article, full_html, creds)
        post_url = post_result.get('url', '')
        logger.info(f"Published successfully: {post_url}")
    except Exception as e:
        logger.error(f"Blogger publish failed: {e}")
        return False

    # Submit to Search Console
    if post_url:
        submit_to_search_console(post_url, creds)

    # Save publish history
    log_published(article, post_result)

    # Telegram notification
    title = article.get('title', '')
    corner = article.get('corner', '')
    send_telegram(
        f"✅ <b>Published successfully!</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"Corner: {corner}\n"
        f"URL: {post_url}"
    )

    return True


def approve_pending(filepath: str) -> bool:
    """Approve and publish a manually reviewed article"""
    try:
        article = load_pending_review_file(filepath)
        article.pop('pending_reason', None)
        article.pop('created_at', None)

        # Force publish bypassing safety checks
        body_html, toc_html = markdown_to_html(article.get('body', ''))
        body_html = insert_adsense_placeholders(body_html)
        full_html = build_full_html(article, body_html, toc_html)

        creds = get_google_credentials()
        post_result = publish_to_blogger(article, full_html, creds)
        post_url = post_result.get('url', '')
        log_published(article, post_result)

        # Delete pending file
        Path(filepath).unlink(missing_ok=True)

        send_telegram(
            f"✅ <b>[Manual Approval] Published successfully!</b>\n\n"
            f"📌 {article.get('title', '')}\n"
            f"URL: {post_url}"
        )
        logger.info(f"Manual approval published: {post_url}")
        return True
    except Exception as e:
        logger.error(f"Approval publish failed: {e}")
        return False


def reject_pending(filepath: str):
    """Reject a manually reviewed article (delete file)"""
    try:
        article = load_pending_review_file(filepath)
        Path(filepath).unlink(missing_ok=True)
        send_telegram(f"🗑 <b>[Rejected]</b> {article.get('title', '')} — discarded")
        logger.info(f"Manual review rejected: {filepath}")
    except Exception as e:
        logger.error(f"Rejection processing failed: {e}")


def get_pending_list() -> list[dict]:
    """Return list of articles pending manual review"""
    pending_dir = DATA_DIR / 'pending_review'
    pending_dir.mkdir(exist_ok=True)
    result = []
    for f in sorted(pending_dir.glob('*_pending.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            data['_filepath'] = str(f)
            result.append(data)
        except Exception:
            pass
    return result


if __name__ == '__main__':
    # Test: attempt to publish a sample article
    sample = {
        'title': 'Test Article',
        'meta': 'Test meta description',
        'slug': 'test-article',
        'tags': ['test', 'AI'],
        'corner': 'EasyWorld',
        'body': '## Title\n\nBody content here.\n\n## Conclusion\n\nWrapping up.',
        'coupang_keywords': ['keyboard'],
        'sources': [
            {'url': 'https://example.com/1', 'title': 'Source 1', 'date': '2026-03-24'},
            {'url': 'https://example.com/2', 'title': 'Source 2', 'date': '2026-03-24'},
        ],
        'disclaimer': '',
        'quality_score': 80,
    }
    result = publish(sample)
    print('Publish result:', result)
