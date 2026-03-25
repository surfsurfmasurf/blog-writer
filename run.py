"""
run.py — 블로그 엔진 즉시 실행
실행할 때마다: 글감 수집 → 최적 글감 선택 → Gemini로 글 작성 → Blogger 발행

사용법:
    python run.py              # 수집 → 작성 → 발행 (전체 파이프라인)
    python run.py --collect    # 수집만
    python run.py --write      # 수집된 글감 중 작성만 (발행 안 함)
    python run.py --dry-run    # 발행 없이 테스트 (글 작성까지만)
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / 'bots'))

from dotenv import load_dotenv
load_dotenv()

LOG_DIR = BASE_DIR / 'logs'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'run.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def step_collect() -> list[dict]:
    """1단계: 글감 수집"""
    logger.info("=" * 50)
    logger.info("1단계: 글감 수집 시작")
    logger.info("=" * 50)

    import collector_bot
    topics = collector_bot.run()

    if not topics:
        logger.warning("수집된 글감이 없습니다.")
        return []

    logger.info(f"수집 완료: {len(topics)}개 글감")
    return topics


def step_pick_best_topic(topics: list[dict] | None = None) -> dict | None:
    """2단계: 최적 글감 선택 (품질 점수 기준)"""
    logger.info("=" * 50)
    logger.info("2단계: 최적 글감 선택")
    logger.info("=" * 50)

    # 인자로 전달된 글감 또는 저장된 글감에서 선택
    if not topics:
        topics = _load_today_topics()

    if not topics:
        logger.warning("선택할 글감이 없습니다.")
        return None

    # 이미 작성된 글감 제외
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    drafted_topics = set()
    for f in drafts_dir.glob('*.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            drafted_topics.add(data.get('topic', ''))
        except Exception:
            pass

    available = [t for t in topics if t.get('topic', '') not in drafted_topics]
    if not available:
        logger.info("모든 글감이 이미 작성되었습니다. 전체 목록에서 최고 점수 선택.")
        available = topics

    # 품질 점수 기준 정렬
    available.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    best = available[0]

    logger.info(f"선택된 글감: [{best.get('quality_score', 0)}점][{best.get('corner', '')}] {best.get('topic', '')}")
    return best


def step_write(topic_data: dict) -> dict | None:
    """3단계: Gemini로 글 작성"""
    logger.info("=" * 50)
    logger.info("3단계: Gemini 글 작성")
    logger.info("=" * 50)

    import writer_bot
    article = writer_bot.write_article(topic_data)

    if not article:
        logger.error("글 작성 실패")
        return None

    # 드래프트 저장
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    draft_path = drafts_dir / f'{timestamp}_draft.json'
    draft_path.write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    logger.info(f"드래프트 저장: {draft_path.name}")

    _print_article_preview(article)
    return article


def step_publish(article: dict) -> bool:
    """4단계: Blogger 발행"""
    logger.info("=" * 50)
    logger.info("4단계: Blogger 발행")
    logger.info("=" * 50)

    import publisher_bot
    import linker_bot
    import markdown as md_lib

    # body가 이미 HTML이 아니면 변환
    if not article.get('_body_is_html'):
        body_html = md_lib.markdown(
            article.get('body', ''),
            extensions=['toc', 'tables', 'fenced_code']
        )
        body_html = linker_bot.process(article, body_html)
        article['body'] = body_html
        article['_body_is_html'] = True

    success = publisher_bot.publish(article)

    if success:
        logger.info("발행 성공!")
    else:
        logger.warning("자동 발행 실패 또는 수동 검토 대기. 로그를 확인하세요.")

    return success


def _load_today_topics() -> list[dict]:
    """오늘 수집된 글감 로드"""
    topics_dir = DATA_DIR / 'topics'
    topics_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    topics = []
    for f in sorted(topics_dir.glob(f'{today}_*.json')):
        try:
            topics.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass

    # 오늘 글감 없으면 최근 글감 전체 로드
    if not topics:
        logger.info("오늘 수집된 글감 없음 → 기존 글감에서 검색")
        for f in sorted(topics_dir.glob('*.json'), reverse=True):
            try:
                topics.append(json.loads(f.read_text(encoding='utf-8')))
            except Exception:
                pass
            if len(topics) >= 50:
                break

    return topics


def _print_article_preview(article: dict):
    """작성된 글 미리보기 출력"""
    print("\n" + "=" * 60)
    print(f"  제목: {article.get('title', '')}")
    print(f"  코너: {article.get('corner', '')}")
    print(f"  태그: {', '.join(article.get('tags', []))}")
    print(f"  메타: {article.get('meta', '')[:80]}...")
    body = article.get('body', '')
    print(f"  본문: {len(body)}자")
    print(f"  출처: {len(article.get('sources', []))}개")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='블로그 엔진 즉시 실행')
    parser.add_argument('--collect', action='store_true', help='수집만 실행')
    parser.add_argument('--write', action='store_true', help='수집된 글감으로 글 작성만 (발행 안 함)')
    parser.add_argument('--dry-run', action='store_true', help='발행 없이 테스트')
    args = parser.parse_args()

    logger.info("=== 블로그 엔진 실행 ===")
    start_time = datetime.now()

    # 수집만
    if args.collect:
        step_collect()
        logger.info("=== 수집 완료 ===")
        return

    # 글 작성만 (발행 안 함)
    if args.write:
        topic = step_pick_best_topic()
        if topic:
            step_write(topic)
        logger.info("=== 작성 완료 (발행 안 함) ===")
        return

    # 전체 파이프라인: 수집 → 선택 → 작성 → 발행
    topics = step_collect()
    topic = step_pick_best_topic(topics)
    if not topic:
        logger.error("글감을 찾을 수 없습니다. 종료합니다.")
        return

    article = step_write(topic)
    if not article:
        logger.error("글 작성 실패. 종료합니다.")
        return

    if args.dry_run:
        logger.info("=== dry-run 모드: 발행 건너뜀 ===")
        return

    step_publish(article)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"=== 블로그 엔진 완료 (소요 시간: {elapsed:.1f}초) ===")


if __name__ == '__main__':
    main()
