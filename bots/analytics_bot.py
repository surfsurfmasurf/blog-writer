"""
Analytics Bot (analytics_bot.py)
Role: Blog performance data collection and report generation
5 Key Metrics:
1. Index Rate (Search Console)
2. Search CTR (Search Console)
3. 14-Day Post-Publish Performance
4. Affiliate Click Rate (manual input)
5. Dwell Time (Blogger statistics)
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
TOKEN_PATH = BASE_DIR / 'token.json'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'analytics.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
BLOG_MAIN_ID = os.getenv('BLOG_MAIN_ID', '')

SCOPES = [
    'https://www.googleapis.com/auth/blogger.readonly',
    'https://www.googleapis.com/auth/webmasters.readonly',
]


def get_google_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, 'w') as f:
                f.write(creds.to_json())
    return creds


def load_published_records() -> list[dict]:
    """Load all published records"""
    records = []
    published_dir = DATA_DIR / 'published'
    for f in published_dir.glob('*.json'):
        try:
            records.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return sorted(records, key=lambda x: x.get('published_at', ''), reverse=True)


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        print(text)
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    try:
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': text,
            'parse_mode': 'HTML',
        }, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# --- Search Console Data -------------------------------------------

def get_search_console_data(site_url: str, start_date: str, end_date: str,
                             creds: Credentials) -> dict:
    """Query search performance via Search Console API"""
    try:
        service = build('searchconsole', 'v1', credentials=creds)
        request_body = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['page'],
            'rowLimit': 1000,
        }
        resp = service.searchanalytics().query(
            siteUrl=site_url, body=request_body
        ).execute()
        return resp
    except Exception as e:
        logger.warning(f"Search Console API error: {e}")
        return {}


def calc_index_rate(published_records: list[dict], sc_data: dict) -> float:
    """Calculate index rate: ratio of published articles with data in Search Console"""
    if not published_records:
        return 0.0
    sc_urls = set()
    for row in sc_data.get('rows', []):
        sc_urls.add(row.get('keys', [''])[0])

    indexed = sum(1 for r in published_records if r.get('url', '') in sc_urls)
    return round(indexed / len(published_records) * 100, 1)


def calc_average_ctr(sc_data: dict) -> float:
    """Calculate average CTR"""
    rows = sc_data.get('rows', [])
    if not rows:
        return 0.0
    total_clicks = sum(r.get('clicks', 0) for r in rows)
    total_impressions = sum(r.get('impressions', 0) for r in rows)
    if total_impressions == 0:
        return 0.0
    return round(total_clicks / total_impressions * 100, 2)


def get_14day_performance(published_records: list[dict], sc_data: dict) -> list[dict]:
    """Performance of articles that are 14+ days old"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)
    sc_rows_by_url = {}
    for row in sc_data.get('rows', []):
        url = row.get('keys', [''])[0]
        sc_rows_by_url[url] = row

    results = []
    for record in published_records:
        pub_str = record.get('published_at', '')
        try:
            pub_dt = datetime.fromisoformat(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if pub_dt > cutoff:
            continue  # Less than 14 days old

        url = record.get('url', '')
        sc_row = sc_rows_by_url.get(url, {})
        clicks = sc_row.get('clicks', 0)
        impressions = sc_row.get('impressions', 0)
        results.append({
            'title': record.get('title', ''),
            'corner': record.get('corner', ''),
            'published_at': pub_str,
            'clicks_14d': clicks,
            'impressions_14d': impressions,
            'url': url,
        })
    return results


# --- Report Generation ----------------------------------------------

def format_daily_report(
    today_published: list[dict],
    index_rate: float,
    avg_ctr: float,
    total_published: int,
) -> str:
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_count = len(today_published)
    today_titles = '\n'.join(
        f"  - [{r.get('corner', '')}] {r.get('title', '')}" for r in today_published
    )
    return (
        f"<b>Daily Report — {today_str}</b>\n\n"
        f"Published today: {today_count}\n"
        f"{today_titles}\n\n"
        f"Total published: {total_published}\n"
        f"Index rate: {index_rate}%\n"
        f"Average CTR: {avg_ctr}%\n\n"
        f"Phase 1 target: Index rate 80%+, CTR 3%+"
    )


def format_weekly_report(
    index_rate: float,
    avg_ctr: float,
    by_corner: dict,
    low_performers: list[dict],
) -> str:
    today_str = datetime.now().strftime('%Y-%m-%d')
    corner_lines = '\n'.join(
        f"  - {corner}: {count}" for corner, count in by_corner.items()
    )
    low_lines = '\n'.join(
        f"  ! {r['title']} ({r['clicks_14d']} clicks)" for r in low_performers[:5]
    ) or '  None'

    return (
        f"<b>Weekly Report — {today_str}</b>\n\n"
        f"Index rate: {index_rate}%\n"
        f"Average CTR: {avg_ctr}%\n\n"
        f"Articles published by section:\n{corner_lines}\n\n"
        f"Underperforming articles at 14 days (0 clicks):\n{low_lines}\n\n"
        f"Feedback loop applied — topic adjustments for next week"
    )


def save_analytics(data: dict, filename: str):
    analytics_dir = DATA_DIR / 'analytics'
    analytics_dir.mkdir(exist_ok=True)
    with open(analytics_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_feedback_json(index_rate: float, avg_ctr: float,
                            low_performers: list[dict], by_corner: dict) -> dict:
    """Generate feedback data for the collector bot"""
    feedback = {
        'generated_at': datetime.now().isoformat(),
        'metrics': {
            'index_rate': index_rate,
            'avg_ctr': avg_ctr,
        },
        'adjustments': [],
    }

    if index_rate < 50:
        feedback['adjustments'].append({
            'type': 'warning',
            'message': 'Index rate below 50% — review article structure/Schema',
        })
    if avg_ctr < 1:
        feedback['adjustments'].append({
            'type': 'title_meta',
            'message': 'CTR below 1% — recommend changing title/meta description style',
        })

    # Expand top-performing section
    max_corner = max(by_corner, key=by_corner.get) if by_corner else None
    if max_corner:
        feedback['adjustments'].append({
            'type': 'corner_boost',
            'corner': max_corner,
            'message': f'{max_corner} section performing well — recommend increasing proportion',
        })

    # Reduce topic types with 0 clicks at 14 days
    if low_performers:
        bad_corners = list({r['corner'] for r in low_performers if r['clicks_14d'] == 0})
        for corner in bad_corners:
            feedback['adjustments'].append({
                'type': 'corner_reduce',
                'corner': corner,
                'message': f'{corner} section underperforming at 14 days — recommend reducing topic types',
            })

    return feedback


# --- Main Execution -------------------------------------------------

def daily_report():
    """Generate daily report and send via Telegram"""
    logger.info("=== Analytics bot daily report started ===")
    published_records = load_published_records()

    # Articles published today
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_published = [
        r for r in published_records
        if r.get('published_at', '').startswith(today_str)
    ]

    # Search Console data (last 7 days)
    sc_data = {}
    try:
        creds = get_google_credentials()
        if creds and creds.valid:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            # site_url is the blog URL (e.g., https://techinsider-kr.blogspot.com/)
            # Read from config or manage via environment variable
            site_url = os.getenv('BLOG_SITE_URL', '')
            if site_url:
                sc_data = get_search_console_data(site_url, start_date, end_date, creds)
    except Exception as e:
        logger.warning(f"Search Console query failed: {e}")

    index_rate = calc_index_rate(published_records, sc_data)
    avg_ctr = calc_average_ctr(sc_data)

    report_text = format_daily_report(
        today_published, index_rate, avg_ctr, len(published_records)
    )
    send_telegram(report_text)

    # Save
    save_analytics({
        'date': today_str,
        'today_published': len(today_published),
        'total_published': len(published_records),
        'index_rate': index_rate,
        'avg_ctr': avg_ctr,
    }, f'{today_str}_daily.json')

    logger.info("=== Analytics bot daily report complete ===")


def weekly_report():
    """Generate weekly report and send via Telegram"""
    logger.info("=== Analytics bot weekly report started ===")
    published_records = load_published_records()

    # Search Console data (last 28 days)
    sc_data = {}
    try:
        creds = get_google_credentials()
        if creds and creds.valid:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')
            site_url = os.getenv('BLOG_SITE_URL', '')
            if site_url:
                sc_data = get_search_console_data(site_url, start_date, end_date, creds)
    except Exception as e:
        logger.warning(f"Search Console query failed: {e}")

    index_rate = calc_index_rate(published_records, sc_data)
    avg_ctr = calc_average_ctr(sc_data)
    perf_14d = get_14day_performance(published_records, sc_data)

    # Articles published by section
    by_corner: dict[str, int] = {}
    for r in published_records:
        corner = r.get('corner', 'Other')
        by_corner[corner] = by_corner.get(corner, 0) + 1

    # Underperforming articles at 14 days
    low_performers = [r for r in perf_14d if r['clicks_14d'] == 0]

    report_text = format_weekly_report(index_rate, avg_ctr, by_corner, low_performers)
    send_telegram(report_text)

    # Generate feedback JSON
    feedback = generate_feedback_json(index_rate, avg_ctr, low_performers, by_corner)
    save_analytics(feedback, f"{datetime.now().strftime('%Y%m%d')}_feedback.json")

    logger.info("=== Analytics bot weekly report complete ===")
    return feedback


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'weekly':
        weekly_report()
    else:
        daily_report()
