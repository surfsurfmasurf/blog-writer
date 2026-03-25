"""
Image Bot (image_bot.py)
Role: Image generation/management for cartoon section

IMAGE_MODE environment variable selects the mode:

  manual  (default) — Sends 1 prompt via Telegram at article publish time.
                      User generates the image and saves the file to data/images/.

  request          — Scheduler periodically sends pending prompt list via Telegram.
                     User creates image with generative AI and sends it via Telegram for auto-save.
                     /images command to check pending list, /imgpick [number] to select.

  auto             — Direct OpenAI Images API (dall-e-3) call. Requires OPENAI_API_KEY.
                     Cost: $0.04-0.08 per image (separate from ChatGPT Pro subscription).
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
IMAGES_DIR = DATA_DIR / 'images'
LOG_DIR = BASE_DIR / 'logs'
PENDING_PROMPTS_FILE = IMAGES_DIR / 'pending_prompts.json'

LOG_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'image_bot.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
IMAGE_MODE = os.getenv('IMAGE_MODE', 'manual').lower()  # manual | request | auto


# --- Telegram Send --------------------------------------------------

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


# --- Prompt Generation -----------------------------------------------

def build_cartoon_prompt(topic: str, description: str = '') -> str:
    """Generate cartoon-style image prompt (generic — usable with any generative AI)"""
    desc_part = f" {description}" if description else ""
    prompt = (
        f"Korean editorial cartoon style, single panel.{desc_part} "
        f"Topic: {topic}. "
        f"Style: simple line art, expressive characters, thought-provoking social commentary, "
        f"Korean newspaper cartoon aesthetic, minimal color, black and white with accent colors. "
        f"No text in the image. Square format 1:1."
    )
    return prompt


# --- Pending Prompt Management ----------------------------------------

def load_pending_prompts() -> list[dict]:
    """Load pending_prompts.json"""
    if not PENDING_PROMPTS_FILE.exists():
        return []
    try:
        return json.loads(PENDING_PROMPTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_pending_prompts(prompts: list[dict]):
    """Save pending_prompts.json"""
    PENDING_PROMPTS_FILE.write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def add_pending_prompt(topic: str, description: str, article_ref: str = '') -> dict:
    """Add new prompt to pending list. Returns the created item."""
    prompts = load_pending_prompts()
    # Do not add if same topic already exists
    for p in prompts:
        if p['topic'] == topic and p['status'] == 'pending':
            logger.info(f"Prompt already pending: {topic}")
            return p

    prompt_text = build_cartoon_prompt(topic, description)
    item = {
        'id': str(len(prompts) + 1),  # Human-readable number
        'uid': uuid.uuid4().hex[:8],
        'topic': topic,
        'description': description,
        'prompt': prompt_text,
        'article_ref': article_ref,
        'status': 'pending',  # pending | selected | done
        'created_at': datetime.now().isoformat(),
        'image_path': '',
    }
    prompts.append(item)
    save_pending_prompts(prompts)
    logger.info(f"Prompt added #{item['id']}: {topic}")
    return item


def get_pending_prompts(status: str = 'pending') -> list[dict]:
    """Get prompt list by status"""
    return [p for p in load_pending_prompts() if p['status'] == status]


def mark_prompt_selected(prompt_id: str) -> dict | None:
    """Change a user-selected prompt to selected status"""
    prompts = load_pending_prompts()
    for p in prompts:
        if p['id'] == str(prompt_id):
            p['status'] = 'selected'
            p['selected_at'] = datetime.now().isoformat()
            save_pending_prompts(prompts)
            return p
    return None


def mark_prompt_done(prompt_id: str, image_path: str) -> dict | None:
    """Mark prompt as done after image received"""
    prompts = load_pending_prompts()
    for p in prompts:
        if p['id'] == str(prompt_id):
            p['status'] = 'done'
            p['image_path'] = image_path
            p['done_at'] = datetime.now().isoformat()
            save_pending_prompts(prompts)
            logger.info(f"Prompt #{prompt_id} completed: {image_path}")
            return p
    return None


def get_prompt_by_id(prompt_id: str) -> dict | None:
    for p in load_pending_prompts():
        if p['id'] == str(prompt_id):
            return p
    return None


# --- Image Receive and Save ------------------------------------------

def save_image_from_bytes(image_bytes: bytes, topic: str, prompt_id: str) -> str:
    """Save image received as bytes to data/images/. Returns path."""
    safe_name = re.sub(r'[^\w\-]', '_', topic)[:50]
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_p{prompt_id}_{safe_name}.png"
    save_path = IMAGES_DIR / filename
    save_path.write_bytes(image_bytes)
    logger.info(f"Image saved: {save_path}")
    return str(save_path)


def save_image_from_telegram(file_bytes: bytes, prompt_id: str) -> str | None:
    """Save image received from Telegram and mark prompt as done"""
    prompt = get_prompt_by_id(prompt_id)
    if not prompt:
        logger.warning(f"Prompt #{prompt_id} not found")
        return None

    image_path = save_image_from_bytes(file_bytes, prompt['topic'], prompt_id)
    mark_prompt_done(prompt_id, image_path)
    return image_path


# --- Request Mode — Batch Send ----------------------------------------

def send_prompt_batch():
    """
    Request mode periodic execution.
    Scans cartoon section topics from data/topics/, adds them to the prompt pending list,
    and sends all currently pending prompts via Telegram.
    """
    logger.info("=== Image prompt batch send started ===")

    # Scan cartoon topics -> add to pending list
    topics_dir = DATA_DIR / 'topics'
    for f in sorted(topics_dir.glob('*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('corner') == 'cartoon':
                add_pending_prompt(
                    topic=data.get('topic', ''),
                    description=data.get('description', ''),
                    article_ref=str(f),
                )
        except Exception:
            pass

    pending = get_pending_prompts('pending')
    selected = get_pending_prompts('selected')
    active = pending + selected

    if not active:
        send_telegram("No image production requests at this time.")
        logger.info("No pending prompts")
        return

    lines = [
        f"<b>[Image Production Request — {len(active)} items]</b>\n",
        "Please select an item from the list below to produce.\n",
        f"Select with /imgpick [number] -> Create with generative AI (Midjourney, DALL-E, Stable Diffusion, etc.) -> "
        f"Send the image in this chat.\n",
    ]
    for item in active:
        status_icon = '[In Progress]' if item['status'] == 'selected' else '[Pending]'
        lines.append(
            f"{status_icon} <b>#{item['id']}</b> {item['topic']}\n"
            f"   <code>{item['prompt'][:200]}...</code>\n"
        )
    lines.append("\n/images — Refresh full list")

    send_telegram('\n'.join(lines))
    logger.info(f"Batch send complete: {len(active)} items")


def send_single_prompt(prompt_id: str):
    """Send a single prompt with full details via Telegram"""
    prompt = get_prompt_by_id(prompt_id)
    if not prompt:
        send_telegram(f"Prompt #{prompt_id} not found.")
        return

    mark_prompt_selected(prompt_id)
    msg = (
        f"<b>[Image Production — #{prompt['id']}]</b>\n\n"
        f"Topic: <b>{prompt['topic']}</b>\n\n"
        f"Prompt (copy and paste into your generative AI):\n\n"
        f"<code>{prompt['prompt']}</code>\n\n"
        f"Once the image is ready, <b>send it in this chat</b> and it will be saved automatically.\n"
        f"(Please include <code>#{prompt['id']}</code> in the caption when sending)"
    )
    send_telegram(msg)
    logger.info(f"Single prompt sent #{prompt_id}: {prompt['topic']}")


# --- Auto Mode -------------------------------------------------------

def generate_image_auto(prompt: str, topic: str) -> str | None:
    """Auto-generate image via OpenAI DALL-E 3 API"""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set — automatic image generation unavailable")
        return None
    try:
        resp = requests.post(
            'https://api.openai.com/v1/images/generations',
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'dall-e-3',
                'prompt': prompt,
                'n': 1,
                'size': '1024x1024',
                'quality': 'standard',
            },
            timeout=60,
        )
        resp.raise_for_status()
        image_url = resp.json()['data'][0]['url']
        img_bytes = requests.get(image_url, timeout=30).content
        safe_name = re.sub(r'[^\w\-]', '_', topic)[:50]
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}.png"
        save_path = IMAGES_DIR / filename
        save_path.write_bytes(img_bytes)
        logger.info(f"Auto image saved: {save_path}")
        return str(save_path)
    except Exception as e:
        logger.error(f"Auto image generation failed: {e}")
        return None


# --- Manual Mode -----------------------------------------------------

def process_manual_mode(topic: str, description: str = '') -> str:
    """Send 1 prompt via Telegram at article publish time (user saves file manually)"""
    prompt = build_cartoon_prompt(topic, description)
    safe_name = re.sub(r'[^\w\-]', '_', topic)[:50]
    expected_path = IMAGES_DIR / f"{datetime.now().strftime('%Y%m%d')}_{safe_name}.png"
    send_telegram(
        f"<b>[Cartoon Image Request — manual]</b>\n\n"
        f"Topic: <b>{topic}</b>\n\n"
        f"Prompt:\n<code>{prompt}</code>\n\n"
        f"After generating the image, please save it to the following path:\n"
        f"<code>{expected_path}</code>"
    )
    logger.info(f"Manual mode prompt sent: {topic}")
    return str(expected_path)


# --- Main Entry Point -------------------------------------------------

def process(article: dict) -> str | None:
    """
    Process image for cartoon section articles based on mode.
    Returns: image path (None in request mode — received asynchronously later)
    """
    if article.get('corner') != 'cartoon':
        return None

    topic = article.get('title', '')
    description = article.get('meta', '')
    logger.info(f"Image bot running: {topic} (mode: {IMAGE_MODE})")

    if IMAGE_MODE == 'auto':
        prompt = build_cartoon_prompt(topic, description)
        image_path = generate_image_auto(prompt, topic)
        if image_path:
            send_telegram(
                f"<b>[Auto Image Generation Complete]</b>\n\n{topic}\nPath: <code>{image_path}</code>"
            )
        return image_path

    elif IMAGE_MODE == 'request':
        item = add_pending_prompt(topic, description, article_ref=article.get('_source_file', ''))
        send_telegram(
            f"<b>[Image Production Request Added]</b>\n\n"
            f"Topic: <b>{topic}</b>\n"
            f"Number: <b>#{item['id']}</b>\n\n"
            f"/imgpick {item['id']} — Get prompt for this topic\n"
            f"/images — View full pending list"
        )
        return None  # Image will be received later via Telegram

    else:  # manual (default)
        return process_manual_mode(topic, description)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'batch':
        send_prompt_batch()
    else:
        sample = {'corner': 'cartoon', 'title': 'Is AI stealing jobs?', 'meta': ''}
        print(process(sample))
