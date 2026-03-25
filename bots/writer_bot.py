"""
Writer Bot (writer_bot.py)
Role: Uses the Gemini API to transform collected topics into polished blog articles.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
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
        logging.FileHandler(LOG_DIR / 'writer.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

# --- Prompt -----------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior technical writer for "TechPulse Daily," an engineering blog \
that covers software engineering, AI/ML, infrastructure, developer tools, and \
emerging technology. Your writing style sits at the intersection of clarity and \
depth — think Martin Fowler explaining architectural patterns, or the Stripe \
engineering blog breaking down a distributed-systems problem for a broad audience.

## Writing Guidelines
- Write in English. Use precise, jargon-appropriate language but always explain \
concepts on first use. Never assume the reader is an expert, but never talk down \
to them either.
- Maintain an authoritative yet conversational tone — a senior engineer sharing \
hard-won knowledge over coffee.
- Do NOT use first person ("I") excessively. Prefer "we" (inclusive) or neutral \
constructions. One or two first-person anecdotes are fine for color.
- Structure with H2/H3 subheadings. Each section should be 2-4 paragraphs.
- Target 1,500-2,500 words.
- Open with a hook: a real-world problem, a surprising observation, or a common \
misconception. Do NOT open with a rhetorical question cliche.
- Include concrete examples and, where relevant, code snippets (fenced with \
triple backticks and a language tag).
- Conclude with key takeaways (bulleted) and a brief "what to explore next" \
section pointing the reader forward.
- Cite at least 2 verified sources. Prefer primary sources (official docs, \
research papers, engineering blogs) over secondary coverage.
- No clickbait. No hype. No "You won't believe..." or "X is DEAD" headlines. \
Earn attention with substance.

## Corner-Specific Tone
- HowTo: Tutorial / step-by-step guide style. Walk the reader through the \
process methodically, with numbered steps and expected outputs.
- DeepDive: Exploratory, "hidden gem" energy. Surface underrated tools, \
overlooked features, or non-obvious design decisions worth knowing about.
- CaseStudy: Grounded in real-world experience. Present the problem, the \
approach, the trade-offs, and the outcome. Include lessons learned.
- FactCheck: Evidence-first. Dispassionate, rigorous analysis. Bust myths with \
data and citations, not opinions.
- QuickTake: Short, sharp commentary on a piece of tech news. Get to the point \
fast, add perspective the headline missed.

## Output Format
You MUST follow this format exactly. Each section starts with ---TAG--- on its \
own line.

---TITLE---
(SEO-friendly title, 40-80 characters)

---META---
(Meta description for search engines, 120-160 characters)

---SLUG---
(URL slug in lowercase-hyphen format)

---TAGS---
(Comma-separated tags, 3-6 items)

---CORNER---
(One of: HowTo, DeepDive, CaseStudy, FactCheck, QuickTake)

---BODY---
(Full article body in Markdown)

---COUPANG_KEYWORDS---
(Affiliate search keywords, comma-separated; leave blank if not applicable)

---SOURCES---
(Source list. Each line: URL | Title | Date)

---DISCLAIMER---
(Disclaimer text. Leave blank unless the article covers investing, legal, or \
medical topics)
"""


def build_user_prompt(topic_data: dict) -> str:
    """Build the user prompt from collected topic data."""
    topic = topic_data.get('topic', '')
    description = topic_data.get('description', '')
    corner = topic_data.get('corner', 'HowTo')
    source_url = topic_data.get('source_url', '')
    sources = topic_data.get('sources', [])
    related_keywords = topic_data.get('related_keywords', [])
    coupang_keywords = topic_data.get('coupang_keywords', [])

    sources_text = ''
    if sources:
        for s in sources:
            sources_text += f"- {s.get('title', '')}: {s.get('url', '')}\n"
    elif source_url:
        sources_text = f"- {topic}: {source_url}\n"

    prompt = f"""Write a blog article for the "{corner}" corner based on the topic below.

## Topic Details
- Subject: {topic}
- Description: {description}
- Corner: {corner}
- Related keywords: {', '.join(related_keywords) if related_keywords else 'None'}
- Affiliate keywords: {', '.join(coupang_keywords) if coupang_keywords else 'None'}

## Reference Sources
{sources_text if sources_text else '(Independent research required)'}

## Requirements
1. Follow the output format (---TAG--- markers) exactly as specified
2. Match the tone and style of the "{corner}" corner
3. Use real, verifiable source URLs — at least 2
4. Focus on practical, actionable information for a technical audience
"""
    return prompt


# --- Gemini API Call --------------------------------------------------

def generate_article(topic_data: dict) -> str | None:
    """
    Generate a blog article via the Gemini API.
    Returns: raw output text (needs parsing via article_parser)
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set. Check your .env file.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)

    user_prompt = build_user_prompt(topic_data)
    logger.info(f"Requesting article from Gemini: {topic_data.get('topic', '')}")

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.7,
                max_output_tokens=8192,
            ),
        )
        output = response.text
        logger.info(f"Article generation complete ({len(output)} chars)")
        return output
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return None


def write_article(topic_data: dict) -> dict | None:
    """
    Topic data -> Gemini generation -> parsed article dict.
    Quality score is carried over from the original topic_data.
    """
    from article_parser import parse_output

    raw_output = generate_article(topic_data)
    if not raw_output:
        return None

    article = parse_output(raw_output)
    if not article:
        logger.error("Failed to parse Gemini output. Saving raw output for debugging.")
        _save_raw_output(topic_data, raw_output)
        return None

    # Preserve metadata from the original topic
    article['quality_score'] = topic_data.get('quality_score', 80)
    article['sources'] = article.get('sources', []) or topic_data.get('sources', [])

    # Generate Korean summary for comment
    korean_summary = generate_korean_summary(article)
    if korean_summary:
        article['korean_summary'] = korean_summary

    logger.info(f"Article written successfully: {article.get('title', '')}")
    return article


def generate_korean_summary(article: dict) -> str | None:
    """
    Generate a Korean summary of the article for posting as a comment.
    Uses the same Gemini API with a separate prompt.
    """
    if not GEMINI_API_KEY:
        return None

    title = article.get('title', '')
    body = article.get('body', '')

    # Truncate body to avoid token limits
    body_truncated = body[:6000] if len(body) > 6000 else body

    prompt = f"""아래 영문 기술 블로그 글을 한국어로 요약해주세요.

## 출력 형식 (HTML, 정확히 이 구조를 따를 것)

<b style="font-size:1.1em;">◼ TL;DR — 한국어 요약</b><br><br>

<b>▸ 핵심 포인트</b><br>
• [핵심1]<br>
• [핵심2]<br>
• [핵심3]<br>
• [핵심4 — 필요시]<br>
• [핵심5 — 필요시]<br><br>

<b>▸ 한 줄 정리</b><br>
[전체 글의 핵심을 한 문장으로]<br><br>

<b>▸ 이런 분에게 추천</b><br>
[대상 독자 1~2줄]

## 규칙
- 한국어로 작성 (영문 기술 용어는 그대로 유지: API, SDK, Docker 등)
- 핵심 포인트 3~5개
- 전체 분량: 400~700자
- 톤: 시니어 개발자가 후배에게 설명하듯 (~입니다/합니다 체)
- 위 HTML 형식을 정확히 따를 것. 마크다운 사용 금지.
- 절대 원문을 그대로 번역하지 말고, 핵심만 추출해서 재구성

## 원문 제목
{title}

## 원문 내용
{body_truncated}
"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
                max_output_tokens=4096,
            ),
        )
        summary = response.text.strip()
        logger.info(f"Korean summary generated ({len(summary)} chars)")
        return summary
    except Exception as e:
        logger.warning(f"Korean summary generation failed: {e}")
        return None


def _save_raw_output(topic_data: dict, raw_output: str):
    """Save raw output on parse failure for debugging."""
    failed_dir = DATA_DIR / 'failed_outputs'
    failed_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_raw.txt"
    (failed_dir / filename).write_text(raw_output, encoding='utf-8')
    logger.info(f"Raw output saved for debugging: {filename}")


# --- Test -------------------------------------------------------------

if __name__ == '__main__':
    sample_topic = {
        'topic': 'Building Reliable Distributed Cron with Go and etcd',
        'description': 'How to design a distributed task scheduler that '
                       'handles leader election, consistency, and failure '
                       'recovery using Go and etcd.',
        'corner': 'HowTo',
        'source_url': 'https://etcd.io/docs/',
        'sources': [
            {'url': 'https://etcd.io/docs/', 'title': 'etcd Documentation', 'date': '2026-03-25'},
        ],
        'related_keywords': ['distributed systems', 'cron', 'Go', 'etcd', 'leader election'],
        'coupang_keywords': ['mechanical keyboard', 'monitor arm'],
        'quality_score': 85,
    }

    result = write_article(sample_topic)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Article generation failed")
