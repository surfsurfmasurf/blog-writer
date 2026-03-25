"""
Image Bot (image_bot.py)
Role: Generate featured images for all blog articles using Gemini Imagen API.
Also manages editorial cartoon images for QuickTake section.

IMAGE_MODE environment variable selects the mode for QuickTake cartoons:
  manual  (default) — Sends 1 prompt via Telegram at article publish time.
  request          — Batch prompts via Telegram for manual generation.
  auto             — OpenAI DALL-E 3 API auto-generation (requires OPENAI_API_KEY).

Featured images for regular articles always use Gemini Imagen (no extra API key needed).
"""
import base64
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
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
IMAGE_MODE = os.getenv('IMAGE_MODE', 'manual').lower()


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


# --- Featured Image Generation (Gemini Imagen) -----------------------

def generate_featured_image(title: str, description: str = '', tags: list = None) -> str | None:
    """
    Generate a featured/hero image using Gemini's image generation model.
    Model: gemini-2.5-flash-image (supports response_modalities=['IMAGE'])
    Returns: local file path to saved image, or None on failure.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — skipping image generation")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        tags_str = ', '.join(tags[:3]) if tags else ''
        prompt = (
            f"Generate an image: A clean, modern, professional blog featured image "
            f"for a tech article about: {title}. "
            f"{f'Keywords: {tags_str}. ' if tags_str else ''}"
            f"Style: minimalist flat illustration, subtle gradients, tech-themed, "
            f"abstract geometric shapes, muted professional color palette (blues, grays, whites), "
            f"no text, no watermarks, suitable as a blog header image."
        )

        # Try image-capable models in order of preference
        image_models = [
            'gemini-2.5-flash-image',
            'gemini-2.0-flash-exp',
        ]

        for model_name in image_models:
            try:
                logger.info(f"Trying image model: {model_name}")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=['IMAGE'],
                    ),
                )

                # Extract image from response parts
                if response.candidates:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                            image_data = part.inline_data.data
                            ext = 'png' if 'png' in part.inline_data.mime_type else 'jpg'
                            safe_name = re.sub(r'[^\w\-]', '_', title)[:50]
                            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}.{ext}"
                            save_path = IMAGES_DIR / filename
                            save_path.write_bytes(image_data)
                            logger.info(f"Featured image generated with {model_name}: {save_path}")
                            return str(save_path)

                logger.info(f"{model_name}: no image in response, trying next model")
            except Exception as e:
                logger.info(f"{model_name} failed: {e}")
                continue

        logger.warning("All image models failed")
        return None

    except Exception as e:
        logger.warning(f"Featured image generation failed: {e}")
        return None


def upload_image_to_blogger(image_path: str) -> str | None:
    """
    Upload image to a free hosting service and return the public URL.
    Uses imgbb.com free tier (no API key needed for anonymous uploads).
    Falls back to base64 data URI if upload fails.
    """
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Try imgbb free upload (anonymous, no API key)
        resp = requests.post(
            'https://api.imgbb.com/1/upload',
            params={'key': '00000000000000000000000000000000'},  # anonymous
            files={'image': image_data},
            timeout=30,
        )
        if resp.status_code == 200 and resp.json().get('success'):
            url = resp.json()['data']['url']
            logger.info(f"Image uploaded: {url}")
            return url
    except Exception as e:
        logger.debug(f"imgbb upload failed: {e}")

    # Fallback: base64 data URI (works in most blog platforms)
    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        data_uri = f"data:image/png;base64,{b64}"
        logger.info("Using base64 data URI for image")
        return data_uri
    except Exception as e:
        logger.warning(f"Image encoding failed: {e}")
        return None


# --- Cartoon Prompt Generation ----------------------------------------

def build_cartoon_prompt(topic: str, description: str = '') -> str:
    """Generate cartoon-style image prompt (generic — usable with any generative AI)"""
    desc_part = f" {description}" if description else ""
    prompt = (
        f"Editorial cartoon style, single panel.{desc_part} "
        f"Topic: {topic}. "
        f"Style: simple line art, expressive characters, thought-provoking social commentary, "
        f"newspaper editorial cartoon aesthetic, minimal color, black and white with accent colors. "
        f"No text in the image. Square format 1:1."
    )
    return prompt


# --- Pending Prompt Management ----------------------------------------

def load_pending_prompts() -> list[dict]:
    if not PENDING_PROMPTS_FILE.exists():
        return []
    try:
        return json.loads(PENDING_PROMPTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_pending_prompts(prompts: list[dict]):
    PENDING_PROMPTS_FILE.write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def add_pending_prompt(topic: str, description: str, article_ref: str = '') -> dict:
    prompts = load_pending_prompts()
    for p in prompts:
        if p['topic'] == topic and p['status'] == 'pending':
            logger.info(f"Prompt already pending: {topic}")
            return p

    prompt_text = build_cartoon_prompt(topic, description)
    item = {
        'id': str(len(prompts) + 1),
        'uid': uuid.uuid4().hex[:8],
        'topic': topic,
        'description': description,
        'prompt': prompt_text,
        'article_ref': article_ref,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'image_path': '',
    }
    prompts.append(item)
    save_pending_prompts(prompts)
    logger.info(f"Prompt added #{item['id']}: {topic}")
    return item


def get_pending_prompts(status: str = 'pending') -> list[dict]:
    return [p for p in load_pending_prompts() if p['status'] == status]


def mark_prompt_selected(prompt_id: str) -> dict | None:
    prompts = load_pending_prompts()
    for p in prompts:
        if p['id'] == str(prompt_id):
            p['status'] = 'selected'
            p['selected_at'] = datetime.now().isoformat()
            save_pending_prompts(prompts)
            return p
    return None


def mark_prompt_done(prompt_id: str, image_path: str) -> dict | None:
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
    safe_name = re.sub(r'[^\w\-]', '_', topic)[:50]
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_p{prompt_id}_{safe_name}.png"
    save_path = IMAGES_DIR / filename
    save_path.write_bytes(image_bytes)
    logger.info(f"Image saved: {save_path}")
    return str(save_path)


def save_image_from_telegram(file_bytes: bytes, prompt_id: str) -> str | None:
    prompt = get_prompt_by_id(prompt_id)
    if not prompt:
        logger.warning(f"Prompt #{prompt_id} not found")
        return None
    image_path = save_image_from_bytes(file_bytes, prompt['topic'], prompt_id)
    mark_prompt_done(prompt_id, image_path)
    return image_path


# --- Batch Send -------------------------------------------------------

def send_prompt_batch():
    logger.info("=== Image prompt batch send started ===")
    topics_dir = DATA_DIR / 'topics'
    for f in sorted(topics_dir.glob('*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('corner') == 'QuickTake':
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
        "Select with /imgpick [number] -> Generate -> Send image in chat.\n",
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
    prompt = get_prompt_by_id(prompt_id)
    if not prompt:
        send_telegram(f"Prompt #{prompt_id} not found.")
        return
    mark_prompt_selected(prompt_id)
    msg = (
        f"<b>[Image Production — #{prompt['id']}]</b>\n\n"
        f"Topic: <b>{prompt['topic']}</b>\n\n"
        f"Prompt:\n<code>{prompt['prompt']}</code>\n\n"
        f"Send the generated image in this chat.\n"
        f"(Include <code>#{prompt['id']}</code> in the caption)"
    )
    send_telegram(msg)
    logger.info(f"Single prompt sent #{prompt_id}: {prompt['topic']}")


# --- Auto Mode (DALL-E) -----------------------------------------------

def generate_image_auto_dalle(prompt: str, topic: str) -> str | None:
    """Auto-generate image via OpenAI DALL-E 3 API"""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set — DALL-E unavailable")
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
        logger.info(f"DALL-E image saved: {save_path}")
        return str(save_path)
    except Exception as e:
        logger.error(f"DALL-E image generation failed: {e}")
        return None


# --- Manual Mode -------------------------------------------------------

def process_manual_mode(topic: str, description: str = '') -> str:
    prompt = build_cartoon_prompt(topic, description)
    safe_name = re.sub(r'[^\w\-]', '_', topic)[:50]
    expected_path = IMAGES_DIR / f"{datetime.now().strftime('%Y%m%d')}_{safe_name}.png"
    send_telegram(
        f"<b>[Cartoon Image Request — manual]</b>\n\n"
        f"Topic: <b>{topic}</b>\n\n"
        f"Prompt:\n<code>{prompt}</code>\n\n"
        f"Save generated image to:\n<code>{expected_path}</code>"
    )
    logger.info(f"Manual mode prompt sent: {topic}")
    return str(expected_path)


# --- Main Entry Point -------------------------------------------------

def generate_and_get_url(article: dict) -> str | None:
    """
    Generate a featured image for ANY article and return a usable URL/data URI.
    This is the main function called by the publishing pipeline.
    """
    title = article.get('title', '')
    description = article.get('meta', '')
    tags = article.get('tags', [])

    logger.info(f"Generating featured image for: {title}")

    # Generate image with Gemini Imagen
    image_path = generate_featured_image(title, description, tags)

    if not image_path:
        logger.info("Featured image generation skipped or failed")
        return None

    # Get a public URL for the image
    image_url = upload_image_to_blogger(image_path)
    return image_url


def process_quicktake(article: dict) -> str | None:
    """Process cartoon image for QuickTake articles (legacy behavior)."""
    topic = article.get('title', '')
    description = article.get('meta', '')
    logger.info(f"QuickTake image: {topic} (mode: {IMAGE_MODE})")

    if IMAGE_MODE == 'auto':
        prompt = build_cartoon_prompt(topic, description)
        image_path = generate_image_auto_dalle(prompt, topic)
        if image_path:
            send_telegram(
                f"<b>[Auto Image Generation Complete]</b>\n\n{topic}\nPath: <code>{image_path}</code>"
            )
        return image_path
    elif IMAGE_MODE == 'request':
        add_pending_prompt(topic, description, article_ref=article.get('_source_file', ''))
        return None
    else:
        return process_manual_mode(topic, description)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'batch':
        send_prompt_batch()
    else:
        sample = {'title': 'Building Microservices with Go', 'meta': 'A guide', 'tags': ['Go', 'microservices']}
        url = generate_and_get_url(sample)
        print(f"Image URL: {url}")
