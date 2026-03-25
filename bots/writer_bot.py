"""
글 작성봇 (writer_bot.py)
역할: Gemini API를 사용해 수집된 글감을 완성된 블로그 글로 작성
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
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

# ─── 프롬프트 ───────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 한국어 블로그 "테크인사이더"의 전문 필자입니다.
AI/테크 분야를 일반인도 이해할 수 있도록 쉽고 친근하게 설명하는 것이 당신의 강점입니다.

## 글쓰기 규칙
- 한국어로 작성 (영어 용어는 첫 등장 시 한글 병기)
- 1인칭 시점 사용하지 않음. 객관적이고 친근한 톤
- H2/H3 소제목으로 구조화
- 각 섹션은 2~4개 문단
- 본문 전체 1,500~2,500자 (한국어 기준)
- 도입부에서 독자의 관심을 끄는 질문 또는 상황 제시
- 결론 섹션에서 핵심 요약 + 행동 유도
- 출처는 반드시 2개 이상 명시
- 과장 표현, 클릭베이트 금지
- "~입니다", "~합니다" 체 사용

## 코너별 톤
- 쉬운세상: 튜토리얼/가이드 스타일. 단계별 설명.
- 숨은보물: 발견의 즐거움. "이런 게 있었어?" 느낌.
- 바이브리포트: 실제 사례 중심. 공감과 영감.
- 팩트체크: 냉정하고 객관적. 근거 기반.
- 한컷: 짧고 임팩트 있는 논평.

## 출력 형식
반드시 아래 형식을 정확히 따라주세요. 각 섹션은 ---태그명--- 으로 시작합니다.

---TITLE---
(SEO 최적화된 제목, 30~60자)

---META---
(검색 엔진용 메타 설명, 100~160자)

---SLUG---
(URL용 영문 슬러그, 소문자-하이픈 형식)

---TAGS---
(쉼표로 구분된 태그, 3~6개)

---CORNER---
(코너명: 쉬운세상, 숨은보물, 바이브리포트, 팩트체크, 한컷 중 하나)

---BODY---
(마크다운 형식 본문)

---COUPANG_KEYWORDS---
(쿠팡 검색용 키워드, 쉼표 구분, 없으면 비워둠)

---SOURCES---
(출처 목록. 각 줄: URL | 제목 | 날짜)

---DISCLAIMER---
(면책 문구. 투자/법률 관련 글이 아니면 비워둠)
"""


def build_user_prompt(topic_data: dict) -> str:
    """글감 데이터를 기반으로 사용자 프롬프트 생성"""
    topic = topic_data.get('topic', '')
    description = topic_data.get('description', '')
    corner = topic_data.get('corner', '쉬운세상')
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

    prompt = f"""아래 글감으로 "{corner}" 코너에 맞는 블로그 글을 작성해주세요.

## 글감 정보
- 주제: {topic}
- 설명: {description}
- 코너: {corner}
- 관련 키워드: {', '.join(related_keywords) if related_keywords else '없음'}
- 쿠팡 연관 키워드: {', '.join(coupang_keywords) if coupang_keywords else '없음'}

## 참고 출처
{sources_text if sources_text else '(직접 조사 필요)'}

## 요청사항
1. 위 출력 형식(---태그명--- 형식)을 정확히 지켜주세요
2. 코너 "{corner}"의 톤에 맞게 작성
3. 출처는 실제 존재하는 URL을 사용하고, 최소 2개 이상
4. 한국 독자 관점에서 유용한 정보 위주로 작성
"""
    return prompt


# ─── Gemini API 호출 ─────────────────────────────────

def generate_article(topic_data: dict) -> str | None:
    """
    Gemini API로 블로그 글 생성.
    Returns: 원본 출력 텍스트 (article_parser로 파싱 필요)
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return None

    genai.configure(api_key=GEMINI_API_KEY)

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )

    user_prompt = build_user_prompt(topic_data)
    logger.info(f"Gemini 글 작성 요청: {topic_data.get('topic', '')}")

    try:
        response = model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=4096,
            ),
        )
        output = response.text
        logger.info(f"Gemini 글 작성 완료 ({len(output)}자)")
        return output
    except Exception as e:
        logger.error(f"Gemini API 오류: {e}")
        return None


def write_article(topic_data: dict) -> dict | None:
    """
    글감 → Gemini 작성 → 파싱된 article dict 반환.
    품질 점수는 원본 topic_data에서 가져옴.
    """
    from article_parser import parse_output

    raw_output = generate_article(topic_data)
    if not raw_output:
        return None

    article = parse_output(raw_output)
    if not article:
        logger.error("Gemini 출력 파싱 실패. 원본 저장 후 건너뜀.")
        _save_raw_output(topic_data, raw_output)
        return None

    # 원본 글감의 메타 정보 보존
    article['quality_score'] = topic_data.get('quality_score', 80)
    article['sources'] = article.get('sources', []) or topic_data.get('sources', [])

    logger.info(f"글 작성 완료: {article.get('title', '')}")
    return article


def _save_raw_output(topic_data: dict, raw_output: str):
    """파싱 실패 시 원본 출력 저장 (디버깅용)"""
    failed_dir = DATA_DIR / 'failed_outputs'
    failed_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_raw.txt"
    (failed_dir / filename).write_text(raw_output, encoding='utf-8')
    logger.info(f"파싱 실패 원본 저장: {filename}")


# ─── 테스트 ────────────────────────────────────────────

if __name__ == '__main__':
    sample_topic = {
        'topic': 'ChatGPT를 활용한 업무 자동화 방법',
        'description': 'ChatGPT를 업무에 활용하는 실전 팁',
        'corner': '쉬운세상',
        'source_url': 'https://openai.com/blog',
        'sources': [
            {'url': 'https://openai.com/blog', 'title': 'OpenAI Blog', 'date': '2026-03-25'},
        ],
        'related_keywords': ['ChatGPT', '업무자동화', 'AI활용'],
        'coupang_keywords': ['키보드', '마우스'],
        'quality_score': 85,
    }

    result = write_article(sample_topic)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("글 작성 실패")
