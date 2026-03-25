"""
Linker Bot (linker_bot.py)
Role: Automatically insert Coupang Partners and affiliate links into article body
"""
import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'linker.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

COUPANG_ACCESS_KEY = os.getenv('COUPANG_ACCESS_KEY', '')
COUPANG_SECRET_KEY = os.getenv('COUPANG_SECRET_KEY', '')
COUPANG_API_BASE = 'https://api-gateway.coupang.com'


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


# --- Coupang Partners API ------------------------------------------

def _generate_coupang_hmac(method: str, url: str, query: str) -> dict:
    """Generate Coupang HMAC signature"""
    datetime_str = datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    path = url.split(COUPANG_API_BASE)[-1].split('?')[0]
    message = datetime_str + method + path + query
    signature = hmac.new(
        COUPANG_SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        'Authorization': f'CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, '
                         f'signed-date={datetime_str}, signature={signature}',
        'Content-Type': 'application/json;charset=UTF-8',
    }


def search_coupang_products(keyword: str, limit: int = 3) -> list[dict]:
    """Search products via Coupang Partners API"""
    if not COUPANG_ACCESS_KEY or not COUPANG_SECRET_KEY:
        logger.warning("Coupang API keys not set — skipping link insertion")
        return []

    path = '/v2/providers/affiliate_api/apis/openapi/products/search'
    params = {
        'keyword': keyword,
        'limit': limit,
        'subId': 'blog-writer',
    }
    query_string = urlencode(params)
    url = f'{COUPANG_API_BASE}{path}?{query_string}'

    try:
        headers = _generate_coupang_hmac('GET', url, query_string)
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        products = data.get('data', {}).get('productData', [])
        return [
            {
                'name': p.get('productName', keyword),
                'price': p.get('productPrice', 0),
                'url': p.get('productUrl', ''),
                'image': p.get('productImage', ''),
            }
            for p in products[:limit]
        ]
    except Exception as e:
        logger.warning(f"Coupang API error ({keyword}): {e}")
        return []


def build_coupang_link_html(product: dict) -> str:
    """Generate Coupang product link HTML"""
    name = product.get('name', '')
    url = product.get('url', '')
    price = product.get('price', 0)
    price_str = f"{int(price):,}원" if price else ''
    return (
        f'<p class="coupang-link">'
        f'🛒 <a href="{url}" target="_blank" rel="nofollow">{name}</a>'
        f'{" — " + price_str if price_str else ""}'
        f'</p>\n'
    )


# --- Body Link Insertion -------------------------------------------

def insert_links_into_html(html_content: str, coupang_keywords: list[str],
                            fixed_links: list[dict]) -> str:
    """Insert Coupang links and fixed links into HTML body"""
    soup = BeautifulSoup(html_content, 'lxml')

    # Fixed links (if keyword text exists in body, link at first occurrence)
    for fixed in fixed_links:
        kw = fixed.get('keyword', '')
        link_url = fixed.get('url', '')
        label = fixed.get('label', kw)
        if not kw or not link_url:
            continue
        for p in soup.find_all(['p', 'li']):
            text = p.get_text()
            if kw in text:
                # Skip if link already exists
                if p.find('a', string=re.compile(re.escape(kw))):
                    break
                new_html = p.decode_contents().replace(
                    kw,
                    f'<a href="{link_url}" target="_blank">{kw}</a>',
                    1
                )
                p.clear()
                p.append(BeautifulSoup(new_html, 'lxml'))
                break

    # Coupang links: insert product box before conclusion/recommendation section
    if coupang_keywords and (COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY):
        coupang_block_parts = []
        for kw in coupang_keywords[:3]:  # max 3 keywords
            products = search_coupang_products(kw, limit=2)
            for product in products:
                coupang_block_parts.append(build_coupang_link_html(product))

        if coupang_block_parts:
            coupang_block_html = (
                '<div class="coupang-products">\n'
                '<p><strong>Related Products</strong></p>\n'
                + ''.join(coupang_block_parts) +
                '</div>\n'
            )
            # Insert before conclusion H2
            for h2 in soup.find_all('h2'):
                if any(kw in h2.get_text() for kw in ['conclusion', 'summary', 'wrap-up', 'final thoughts', 'key takeaways']):
                    block = BeautifulSoup(coupang_block_html, 'lxml')
                    h2.insert_before(block)
                    break
            else:
                # If no conclusion section, append to end of body
                body_tag = soup.find('body') or soup
                block = BeautifulSoup(coupang_block_html, 'lxml')
                body_tag.append(block)

    return str(soup)


def add_disclaimer(html_content: str, disclaimer_text: str) -> str:
    """Add Coupang required disclaimer (skip if already present)"""
    if disclaimer_text in html_content:
        return html_content
    disclaimer_html = (
        f'\n<hr/>\n'
        f'<p class="affiliate-disclaimer"><small>⚠️ {disclaimer_text}</small></p>\n'
    )
    return html_content + disclaimer_html


# --- Main Function --------------------------------------------------

def process(article: dict, html_content: str) -> str:
    """
    Linker bot main: insert Coupang/affiliate links into HTML body and return
    """
    logger.info(f"Link insertion started: {article.get('title', '')}")
    affiliate_cfg = load_config('affiliate_links.json')

    coupang_keywords = article.get('coupang_keywords', [])
    fixed_links = affiliate_cfg.get('fixed_links', [])
    disclaimer_text = affiliate_cfg.get('disclaimer_text', '')

    # Insert links
    html_content = insert_links_into_html(html_content, coupang_keywords, fixed_links)

    # Add disclaimer if Coupang keywords are present
    if coupang_keywords and disclaimer_text:
        html_content = add_disclaimer(html_content, disclaimer_text)

    logger.info("Link insertion complete")
    return html_content


if __name__ == '__main__':
    sample_html = '''
    <h2>ChatGPT Introduction</h2>
    <p>Using ChatGPT Plus gives you faster responses.</p>
    <h2>Keyboard Recommendations</h2>
    <p>A good keyboard improves productivity.</p>
    <h2>Conclusion</h2>
    <p>Make good use of AI tools.</p>
    '''
    sample_article = {
        'title': 'Test Article',
        'coupang_keywords': ['keyboard', 'mouse'],
    }
    result = process(sample_article, sample_html)
    print(result[:500])
