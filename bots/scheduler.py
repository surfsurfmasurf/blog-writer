"""
Scheduler (scheduler.py)
Role: Manages execution schedules for all bots + Telegram manual command listener
Libraries: APScheduler + python-telegram-bot
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

log_handler = RotatingFileHandler(
    LOG_DIR / 'scheduler.log',
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[log_handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
IMAGE_MODE = os.getenv('IMAGE_MODE', 'manual').lower()
# State variable used when awaiting images in request mode
# {chat_id: prompt_id} — remembers which prompt to associate the next received image with
_awaiting_image: dict[int, str] = {}

_publish_enabled = True


def load_schedule() -> dict:
    with open(CONFIG_DIR / 'schedule.json', 'r', encoding='utf-8') as f:
        return json.load(f)


# --- Scheduled Jobs ------------------------------------------------

def job_collector():
    logger.info("[Schedule] Collector bot started")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import collector_bot
        collector_bot.run()
    except Exception as e:
        logger.error(f"Collector bot error: {e}")


def job_ai_writer():
    logger.info("[Schedule] AI article writing triggered")
    if not _publish_enabled:
        logger.info("Publishing paused — skipping")
        return
    try:
        _trigger_openclaw_writer()
    except Exception as e:
        logger.error(f"AI article writing trigger error: {e}")


def _trigger_openclaw_writer():
    topics_dir = DATA_DIR / 'topics'
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    topic_files = sorted(topics_dir.glob(f'{today}_*.json'))
    if not topic_files:
        logger.info("No topics to process today")
        return
    for topic_file in topic_files[:3]:
        draft_check = drafts_dir / topic_file.name
        if draft_check.exists():
            continue
        topic_data = json.loads(topic_file.read_text(encoding='utf-8'))
        logger.info(f"Article writing request: {topic_data.get('topic', '')}")
        _call_gemini_writer(topic_data, draft_check)


def _call_gemini_writer(topic_data: dict, output_path: Path):
    """Write article via Gemini API and save draft"""
    logger.info(f"Gemini article writing request: {topic_data.get('topic', '')}")
    try:
        import writer_bot
        article = writer_bot.write_article(topic_data)
        if article:
            output_path.write_text(
                json.dumps(article, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            logger.info(f"Gemini article writing complete: {article.get('title', '')}")
        else:
            logger.error(f"Gemini article writing failed: {topic_data.get('topic', '')}")
    except Exception as e:
        logger.error(f"Gemini article writing error: {e}")


def job_publish(slot: int):
    if not _publish_enabled:
        logger.info(f"[Schedule] Publishing paused — skipping slot {slot}")
        return
    logger.info(f"[Schedule] Publisher bot (slot {slot})")
    try:
        _publish_next()
    except Exception as e:
        logger.error(f"Publisher bot error: {e}")


def _publish_next():
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    for draft_file in sorted(drafts_dir.glob('*.json')):
        try:
            article = json.loads(draft_file.read_text(encoding='utf-8'))
            sys.path.insert(0, str(BASE_DIR / 'bots'))
            import publisher_bot
            import linker_bot
            import markdown as md_lib
            body_html = md_lib.markdown(
                article.get('body', ''), extensions=['toc', 'tables', 'fenced_code']
            )
            body_html = linker_bot.process(article, body_html)
            article['body'] = body_html
            article['_body_is_html'] = True
            publisher_bot.publish(article)
            draft_file.unlink(missing_ok=True)
            break
        except Exception as e:
            logger.error(f"Draft processing error ({draft_file.name}): {e}")


def job_analytics_daily():
    logger.info("[Schedule] Analytics bot daily report")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import analytics_bot
        analytics_bot.daily_report()
    except Exception as e:
        logger.error(f"Analytics bot error: {e}")


def job_analytics_weekly():
    logger.info("[Schedule] Analytics bot weekly report")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import analytics_bot
        analytics_bot.weekly_report()
    except Exception as e:
        logger.error(f"Analytics bot weekly report error: {e}")


def job_image_prompt_batch():
    """Request mode only — send prompt batch every Monday at 10:00"""
    if IMAGE_MODE != 'request':
        return
    logger.info("[Schedule] Image prompt batch send")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import image_bot
        image_bot.send_prompt_batch()
    except Exception as e:
        logger.error(f"Image batch error: {e}")


# --- Telegram Command Handlers ------------------------------------

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "Publishing active" if _publish_enabled else "Publishing paused"
    mode_label = {'manual': 'Manual', 'request': 'Request', 'auto': 'Auto'}.get(IMAGE_MODE, IMAGE_MODE)
    await update.message.reply_text(
        f"Blog engine status: {status}\nImage mode: {mode_label} ({IMAGE_MODE})"
    )


async def cmd_stop_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _publish_enabled
    _publish_enabled = False
    await update.message.reply_text("Publishing has been paused.")


async def cmd_resume_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _publish_enabled
    _publish_enabled = True
    await update.message.reply_text("Publishing has been resumed.")


async def cmd_show_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_dir = DATA_DIR / 'topics'
    today = datetime.now().strftime('%Y%m%d')
    files = sorted(topics_dir.glob(f'{today}_*.json'))
    if not files:
        await update.message.reply_text("No topics collected today.")
        return
    lines = [f"Topics collected today ({len(files)}):"]
    for f in files[:10]:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            lines.append(f"  [{data.get('quality_score',0)}pts][{data.get('corner','')}] {data.get('topic','')[:50]}")
        except Exception:
            pass
    await update.message.reply_text('\n'.join(lines))


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("No articles pending manual review.")
        return
    lines = [f"Pending manual review ({len(pending)}):"]
    for i, item in enumerate(pending[:5], 1):
        lines.append(f"  {i}. [{item.get('corner','')}] {item.get('title','')[:50]}")
        lines.append(f"     Reason: {item.get('pending_reason','')}")
    lines.append("\n/approve [number]  /reject [number]")
    await update.message.reply_text('\n'.join(lines))


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("No pending articles.")
        return
    args = context.args
    idx = int(args[0]) - 1 if args and args[0].isdigit() else 0
    if not (0 <= idx < len(pending)):
        await update.message.reply_text("Invalid number.")
        return
    success = publisher_bot.approve_pending(pending[idx].get('_filepath', ''))
    await update.message.reply_text(
        f"Approved: {pending[idx].get('title','')}" if success else "Publishing failed. Check logs."
    )


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("No pending articles.")
        return
    args = context.args
    idx = int(args[0]) - 1 if args and args[0].isdigit() else 0
    if not (0 <= idx < len(pending)):
        await update.message.reply_text("Invalid number.")
        return
    publisher_bot.reject_pending(pending[idx].get('_filepath', ''))
    await update.message.reply_text(f"Rejected: {pending[idx].get('title','')}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generating weekly report...")
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import analytics_bot
    analytics_bot.weekly_report()


# --- Image-related Commands (request mode) -------------------------

async def cmd_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of pending image prompts"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot
    pending = image_bot.get_pending_prompts('pending')
    selected = image_bot.get_pending_prompts('selected')
    done = image_bot.get_pending_prompts('done')

    if not pending and not selected:
        await update.message.reply_text(
            f"No pending image requests.\n"
            f"Completed images: {len(done)}\n\n"
            f"/imgbatch — Request batch send now"
        )
        return

    lines = [f"Image production status\n"]
    if pending:
        lines.append(f"Pending ({len(pending)}):")
        for p in pending:
            lines.append(f"  #{p['id']} {p['topic'][:40]}")
    if selected:
        lines.append(f"\nIn progress ({len(selected)}):")
        for p in selected:
            lines.append(f"  #{p['id']} {p['topic'][:40]}")
    lines.append(f"\nCompleted: {len(done)}")
    lines.append(
        f"\n/imgpick [number] — Get prompt\n"
        f"/imgbatch — Resend full list"
    )
    await update.message.reply_text('\n'.join(lines))


async def cmd_imgpick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select a specific prompt by number, send full prompt, and enter image-awaiting state"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /imgpick [number]\nExample: /imgpick 3")
        return

    prompt_id = args[0]
    prompt = image_bot.get_prompt_by_id(prompt_id)
    if not prompt:
        await update.message.reply_text(f"Prompt #{prompt_id} not found.\nUse /images to check the list")
        return

    if prompt['status'] == 'done':
        await update.message.reply_text(f"#{prompt_id} is already completed.")
        return

    # Send single prompt (split send considering Telegram message length limit)
    image_bot.send_single_prompt(prompt_id)

    # Register image-awaiting state
    chat_id = update.message.chat_id
    _awaiting_image[chat_id] = prompt_id
    logger.info(f"Image awaiting registered: chat={chat_id}, prompt=#{prompt_id}")


async def cmd_imgbatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send all pending prompts as batch (manual trigger)"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot
    image_bot.send_prompt_batch()
    await update.message.reply_text("Prompt batch send complete.")


async def cmd_imgcancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel image-awaiting state"""
    chat_id = update.message.chat_id
    if chat_id in _awaiting_image:
        pid = _awaiting_image.pop(chat_id)
        await update.message.reply_text(f"#{pid} image awaiting cancelled.")
    else:
        await update.message.reply_text("No pending image request at this time.")


# --- Image/File Receive Handler ------------------------------------

async def _receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         file_getter, caption: str):
    """Common image receive handler (photo / document)"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot

    chat_id = update.message.chat_id

    # Determine prompt ID: awaiting state > caption parsing > none
    prompt_id = _awaiting_image.get(chat_id)
    if not prompt_id and caption:
        # Extract #number format from caption if present
        m = __import__('re').search(r'#(\d+)', caption)
        if m:
            prompt_id = m.group(1)

    if not prompt_id:
        await update.message.reply_text(
            "Cannot determine which topic this image belongs to.\n\n"
            "Method 1: Select with /imgpick [number] first, then send the image\n"
            "Method 2: Add #number in the image caption (e.g., #3)\n\n"
            "/images — Check current pending list"
        )
        return

    # Download file from Telegram
    try:
        tg_file = await file_getter()
        file_bytes = (await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"File download failed: {e}")
        return

    # Save and mark prompt as done
    image_path = image_bot.save_image_from_telegram(bytes(file_bytes), prompt_id)
    if not image_path:
        await update.message.reply_text(f"Save failed. Check if #{prompt_id} exists.")
        return

    # Clear awaiting state
    _awaiting_image.pop(chat_id, None)

    prompt = image_bot.get_prompt_by_id(prompt_id)
    topic = prompt['topic'] if prompt else ''
    await update.message.reply_text(
        f"<b>Image saved successfully!</b>\n\n"
        f"#{prompt_id} {topic}\n"
        f"Path: <code>{image_path}</code>\n\n"
        f"This image will be automatically used when publishing the corresponding cartoon article.",
        parse_mode='HTML',
    )
    logger.info(f"Image received: #{prompt_id} -> {image_path}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram photo received"""
    caption = update.message.caption or ''
    photo = update.message.photo[-1]  # Highest resolution
    await _receive_image(
        update, context,
        file_getter=lambda: context.bot.get_file(photo.file_id),
        caption=caption,
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram document received — for high-resolution image transfer"""
    doc = update.message.document
    mime = doc.mime_type or ''
    if not mime.startswith('image/'):
        return  # Only process image files
    caption = update.message.caption or ''
    await _receive_image(
        update, context,
        file_getter=lambda: context.bot.get_file(doc.file_id),
        caption=caption,
    )


# --- Text Commands --------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cmd_map = {
        'stop publishing': cmd_stop_publish,
        'resume publishing': cmd_resume_publish,
        'show today topics': cmd_show_topics,
        'weekly report': cmd_report,
        'show pending articles': cmd_pending,
        'image list': cmd_images,
    }
    if text.lower() in cmd_map:
        await cmd_map[text.lower()](update, context)
    else:
        await update.message.reply_text(
            "Available commands:\n"
            "- stop publishing / resume publishing\n"
            "- show today topics\n"
            "- show pending articles\n"
            "- weekly report\n"
            "- image list\n\n"
            "Slash commands:\n"
            "/approve [number] — Approve article\n"
            "/reject [number] — Reject article\n"
            "/images — Image production status\n"
            "/imgpick [number] — Select prompt\n"
            "/imgbatch — Batch send prompts\n"
            "/imgcancel — Cancel image awaiting\n"
            "/status — Bot status"
        )


# --- Scheduler Setup + Main ----------------------------------------

def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone='Asia/Seoul')
    schedule_cfg = load_schedule()

    job_map = {
        'collector': job_collector,
        'ai_writer': job_ai_writer,
        'publish_1': lambda: job_publish(1),
        'publish_2': lambda: job_publish(2),
        'publish_3': lambda: job_publish(3),
        'analytics': job_analytics_daily,
    }
    for job in schedule_cfg.get('jobs', []):
        fn = job_map.get(job['id'])
        if fn:
            scheduler.add_job(fn, 'cron', hour=job['hour'], minute=job['minute'], id=job['id'])

    # Fixed schedule
    scheduler.add_job(job_analytics_weekly, 'cron',
                      day_of_week='sun', hour=22, minute=30, id='weekly_report')

    # Request mode: send image prompt batch every Monday at 10:00
    if IMAGE_MODE == 'request':
        scheduler.add_job(job_image_prompt_batch, 'cron',
                          day_of_week='mon', hour=10, minute=0, id='image_batch')
        logger.info("Image request mode: registered weekly Monday 10:00 batch send")

    logger.info("Scheduler setup complete")
    return scheduler


async def main():
    logger.info("=== Blog Engine Scheduler Started ===")
    scheduler = setup_scheduler()
    scheduler.start()

    if TELEGRAM_BOT_TOKEN:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Publishing related
        app.add_handler(CommandHandler('status', cmd_status))
        app.add_handler(CommandHandler('approve', cmd_approve))
        app.add_handler(CommandHandler('reject', cmd_reject))
        app.add_handler(CommandHandler('pending', cmd_pending))
        app.add_handler(CommandHandler('report', cmd_report))
        app.add_handler(CommandHandler('topics', cmd_show_topics))

        # Image related (usable in both request and manual modes)
        app.add_handler(CommandHandler('images', cmd_images))
        app.add_handler(CommandHandler('imgpick', cmd_imgpick))
        app.add_handler(CommandHandler('imgbatch', cmd_imgbatch))
        app.add_handler(CommandHandler('imgcancel', cmd_imgcancel))

        # Image file receive
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

        # Text commands
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        logger.info("Telegram bot started")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received")
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            scheduler.shutdown()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — running scheduler only")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()

    logger.info("=== Blog Engine Scheduler Stopped ===")


if __name__ == '__main__':
    asyncio.run(main())
