"""
run.py — Blog engine immediate execution
Each run: Collect topics → Select best topic → Write article with Gemini → Publish to Blogger

Usage:
    python run.py              # Collect → Write → Publish (full pipeline)
    python run.py --collect    # Collect only
    python run.py --write      # Write from collected topics only (no publishing)
    python run.py --dry-run    # Test without publishing (write article only)
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
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
    """Step 1: Collect topics"""
    logger.info("=" * 50)
    logger.info("Step 1: Collecting topics")
    logger.info("=" * 50)

    import collector_bot
    topics = collector_bot.run()

    if not topics:
        logger.warning("No topics collected.")
        return []

    logger.info(f"Collection complete: {len(topics)} topics")
    return topics


def step_pick_best_topic(topics: list[dict] | None = None) -> dict | None:
    """Step 2: Select best topic (by quality score)"""
    logger.info("=" * 50)
    logger.info("Step 2: Selecting best topic")
    logger.info("=" * 50)

    # Use provided topics or load saved topics
    if not topics:
        topics = _load_today_topics()

    if not topics:
        logger.warning("No topics available for selection.")
        return None

    # Exclude already drafted topics
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
        logger.info("All topics already drafted. Selecting highest score from full list.")
        available = topics

    # Sort by quality score
    available.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    best = available[0]

    logger.info(f"Selected topic: [{best.get('quality_score', 0)} pts][{best.get('corner', '')}] {best.get('topic', '')}")
    return best


def step_write(topic_data: dict) -> dict | None:
    """Step 3: Write article with Gemini"""
    logger.info("=" * 50)
    logger.info("Step 3: Writing article with Gemini")
    logger.info("=" * 50)

    import writer_bot
    article = writer_bot.write_article(topic_data)

    if not article:
        logger.error("Article writing failed")
        return None

    # Save draft
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    draft_path = drafts_dir / f'{timestamp}_draft.json'
    draft_path.write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    logger.info(f"Draft saved: {draft_path.name}")

    _print_article_preview(article)
    return article


def step_generate_image(article: dict) -> str | None:
    """Step 3.5: Generate featured image with Gemini Imagen"""
    logger.info("=" * 50)
    logger.info("Step 3.5: Generating featured image")
    logger.info("=" * 50)

    import image_bot
    image_url = image_bot.generate_and_get_url(article)

    if image_url:
        article['featured_image_url'] = image_url
        logger.info(f"Featured image ready: {image_url[:80]}...")
    else:
        logger.info("No featured image generated (continuing without image)")

    return image_url


def step_publish(article: dict) -> bool:
    """Step 4: Publish to Blogger"""
    logger.info("=" * 50)
    logger.info("Step 4: Publishing to Blogger")
    logger.info("=" * 50)

    import publisher_bot
    import linker_bot
    import markdown as md_lib

    # Convert body to HTML if not already
    if not article.get('_body_is_html'):
        body_html = md_lib.markdown(
            article.get('body', ''),
            extensions=['tables', 'fenced_code']
        )
        body_html = linker_bot.process(article, body_html)

        # Insert featured image at the top if available
        featured_url = article.get('featured_image_url')
        if featured_url:
            img_html = (
                f'<div class="featured-image" style="margin-bottom:2em;">'
                f'<img src="{featured_url}" alt="{article.get("title", "")}" '
                f'style="width:100%;max-width:800px;height:auto;border-radius:8px;" />'
                f'</div>\n'
            )
            body_html = img_html + body_html

        article['body'] = body_html
        article['_body_is_html'] = True

    success = publisher_bot.publish(article)

    if success:
        logger.info("Publishing succeeded!")
    else:
        logger.warning("Auto-publishing failed or pending manual review. Check the logs.")

    return success


def _load_today_topics() -> list[dict]:
    """Load today's collected topics"""
    topics_dir = DATA_DIR / 'topics'
    topics_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    topics = []
    for f in sorted(topics_dir.glob(f'{today}_*.json')):
        try:
            topics.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass

    # If no topics today, load recent topics
    if not topics:
        logger.info("No topics collected today -> searching existing topics")
        for f in sorted(topics_dir.glob('*.json'), reverse=True):
            try:
                topics.append(json.loads(f.read_text(encoding='utf-8')))
            except Exception:
                pass
            if len(topics) >= 50:
                break

    return topics


def _print_article_preview(article: dict):
    """Print article preview"""
    print("\n" + "=" * 60)
    print(f"  Title: {article.get('title', '')}")
    print(f"  Corner: {article.get('corner', '')}")
    print(f"  Tags: {', '.join(article.get('tags', []))}")
    print(f"  Meta: {article.get('meta', '')[:80]}...")
    body = article.get('body', '')
    print(f"  Body: {len(body)} chars")
    print(f"  Sources: {len(article.get('sources', []))}")
    kr_summary = article.get('korean_summary', '')
    if kr_summary:
        print(f"  Korean Summary: {kr_summary[:120]}...")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Blog engine immediate execution')
    parser.add_argument('--collect', action='store_true', help='Run collection only')
    parser.add_argument('--write', action='store_true', help='Write article from collected topics only (no publishing)')
    parser.add_argument('--dry-run', action='store_true', help='Test without publishing')
    args = parser.parse_args()

    logger.info("=== Blog Engine Started ===")
    start_time = datetime.now()

    # Collect only
    if args.collect:
        step_collect()
        logger.info("=== Collection complete ===")
        return

    # Write only (no publishing)
    if args.write:
        topic = step_pick_best_topic()
        if topic:
            step_write(topic)
        logger.info("=== Writing complete (no publishing) ===")
        return

    # Full pipeline: Collect → Select → Write → Publish
    topics = step_collect()
    topic = step_pick_best_topic(topics)
    if not topic:
        logger.error("No topics found. Exiting.")
        return

    article = step_write(topic)
    if not article:
        logger.error("Article writing failed. Exiting.")
        return

    # Generate featured image
    step_generate_image(article)

    if args.dry_run:
        logger.info("=== Dry-run mode: skipping publishing ===")
        return

    step_publish(article)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"=== Blog Engine complete (elapsed: {elapsed:.1f}s) ===")


if __name__ == '__main__':
    main()
