#!/usr/bin/env python3
"""
auto_post.py — Randomized blog posting scheduler

Designed to be called by cron every hour (e.g., 8am-10pm).
Each invocation randomly decides whether to post based on:
  - How many posts have been made today
  - Target posts per day (randomized between min/max)
  - Time windows and probability distribution

Usage:
    # Cron calls this every hour during posting window
    python auto_post.py

    # Force a post regardless of schedule
    python auto_post.py --force

    # Check status without posting
    python auto_post.py --status

    # Dry-run (write article but don't publish)
    python auto_post.py --dry-run

Schedule patterns (configured below):
    - "2-per-day":    1~2 posts/day, random times between 8am-9pm
    - "3-per-2days":  target 3 posts over 2 days, varies daily
"""
import argparse
import json
import logging
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
SCHEDULE_STATE_FILE = DATA_DIR / 'post_schedule_state.json'

LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'auto_post.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# ─── Schedule Configuration ──────────────────────────────────────────
# Posting window: only post between these hours (24h format)
POST_WINDOW_START = 8   # 8:00 AM
POST_WINDOW_END = 21    # 9:00 PM

# Target posts: randomly pick between min and max each day
DAILY_MIN_POSTS = 1
DAILY_MAX_POSTS = 2

# 2-day cycle: total target over 2 days (e.g., 3 posts in 2 days)
# Set to 0 to disable 2-day mode and use pure daily mode
TWO_DAY_TARGET = 3

# Base probability of posting per hourly check (adjusted dynamically)
BASE_POST_PROBABILITY = 0.25
# ─────────────────────────────────────────────────────────────────────


def load_state() -> dict:
    """Load scheduling state from JSON file."""
    if SCHEDULE_STATE_FILE.exists():
        try:
            return json.loads(SCHEDULE_STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    """Save scheduling state to JSON file."""
    SCHEDULE_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def get_today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def get_yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')


def init_day(state: dict) -> dict:
    """Initialize a new day's schedule if needed."""
    today = get_today_str()

    if state.get('current_date') != today:
        yesterday_posts = state.get('posts_today', 0)
        yesterday_date = state.get('current_date', '')

        # Determine today's target
        if TWO_DAY_TARGET > 0:
            # 2-day cycle mode
            cycle_day = state.get('cycle_day', 0)  # 0 or 1
            if cycle_day == 0:
                # Day 1 of cycle: randomly split the 2-day target
                day1_target = random.randint(1, TWO_DAY_TARGET - 1)
                day2_target = TWO_DAY_TARGET - day1_target
                state['day1_target'] = day1_target
                state['day2_target'] = day2_target
                today_target = day1_target
                logger.info(f"New 2-day cycle: Day 1={day1_target}, Day 2={day2_target} (total={TWO_DAY_TARGET})")
            else:
                # Day 2 of cycle: use remaining target, adjust for day 1 actual
                day1_actual = state.get('day1_actual', 0)
                remaining = TWO_DAY_TARGET - day1_actual
                today_target = max(1, remaining)
                logger.info(f"2-day cycle Day 2: target={today_target} (day1 posted {day1_actual})")

            state['cycle_day'] = 1 - cycle_day  # Toggle 0↔1
            if cycle_day == 0:
                state['day1_actual'] = 0
        else:
            # Pure daily mode
            today_target = random.randint(DAILY_MIN_POSTS, DAILY_MAX_POSTS)
            logger.info(f"New day target: {today_target} posts")

        # Pick random posting hours for today
        available_hours = list(range(POST_WINDOW_START, POST_WINDOW_END + 1))
        post_hours = sorted(random.sample(
            available_hours,
            min(today_target, len(available_hours))
        ))
        # Add random minute offset to each hour
        post_times = []
        for h in post_hours:
            m = random.randint(0, 55)
            post_times.append(f"{h:02d}:{m:02d}")

        state['current_date'] = today
        state['target_today'] = today_target
        state['posts_today'] = 0
        state['post_times'] = post_times
        state['posted_times'] = []
        state['yesterday_date'] = yesterday_date
        state['yesterday_posts'] = yesterday_posts

        logger.info(f"Today's schedule: {today_target} posts at {post_times}")
        save_state(state)

    return state


def should_post_now(state: dict) -> tuple[bool, str]:
    """Decide whether to post right now. Returns (should_post, reason)."""
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute

    # Outside posting window?
    if current_hour < POST_WINDOW_START or current_hour > POST_WINDOW_END:
        return False, f"Outside posting window ({POST_WINDOW_START}:00-{POST_WINDOW_END}:00)"

    # Already hit today's target?
    posts_today = state.get('posts_today', 0)
    target_today = state.get('target_today', 1)
    if posts_today >= target_today:
        return False, f"Daily target reached ({posts_today}/{target_today})"

    # Check scheduled times
    post_times = state.get('post_times', [])
    posted_times = state.get('posted_times', [])
    remaining_times = [t for t in post_times if t not in posted_times]

    if not remaining_times:
        return False, "No remaining scheduled times"

    # Find the next scheduled time
    now_str = f"{current_hour:02d}:{current_minute:02d}"
    for scheduled_time in remaining_times:
        sched_h, sched_m = map(int, scheduled_time.split(':'))
        # Allow a 59-minute window after scheduled time
        if current_hour == sched_h and current_minute >= sched_m:
            return True, f"Scheduled time hit: {scheduled_time}"
        # If we're past a scheduled hour entirely, also trigger
        if current_hour > sched_h:
            return True, f"Catching up on missed time: {scheduled_time}"

    # Not time yet
    next_time = remaining_times[0]
    return False, f"Waiting for next scheduled time: {next_time}"


def record_post(state: dict):
    """Record that a post was made."""
    state['posts_today'] = state.get('posts_today', 0) + 1
    now_str = f"{datetime.now().hour:02d}:{datetime.now().minute:02d}"
    state.setdefault('posted_times', []).append(now_str)

    # Update day1_actual for 2-day cycle tracking
    if TWO_DAY_TARGET > 0 and state.get('cycle_day') == 0:
        state['day1_actual'] = state.get('posts_today', 0)

    state['last_post_at'] = datetime.now().isoformat()
    save_state(state)
    logger.info(f"Post recorded: {state['posts_today']}/{state.get('target_today', '?')} today")


def run_blog_engine(dry_run: bool = False) -> bool:
    """Execute run.py to create and publish a blog post."""
    cmd = [sys.executable, str(BASE_DIR / 'run.py')]
    if dry_run:
        cmd.append('--dry-run')

    logger.info(f"Executing: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )
        if result.returncode == 0:
            logger.info("Blog engine completed successfully")
            # Print last few lines of output
            for line in result.stdout.strip().split('\n')[-5:]:
                logger.info(f"  | {line}")
            return True
        else:
            logger.error(f"Blog engine failed (exit code {result.returncode})")
            if result.stderr:
                for line in result.stderr.strip().split('\n')[-5:]:
                    logger.error(f"  | {line}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("Blog engine timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Failed to run blog engine: {e}")
        return False


def print_status(state: dict):
    """Print current schedule status."""
    today = get_today_str()
    print(f"\n{'='*50}")
    print(f"  Auto-Post Schedule Status")
    print(f"{'='*50}")
    print(f"  Date:           {today}")
    print(f"  Posts today:    {state.get('posts_today', 0)}/{state.get('target_today', '?')}")
    print(f"  Scheduled at:   {state.get('post_times', [])}")
    print(f"  Posted at:      {state.get('posted_times', [])}")
    print(f"  Last post:      {state.get('last_post_at', 'never')}")
    if TWO_DAY_TARGET > 0:
        cycle_day = 'Day 1' if state.get('cycle_day') == 1 else 'Day 2'
        print(f"  2-day cycle:    {cycle_day} (target: {TWO_DAY_TARGET} per 2 days)")
    print(f"  Post window:    {POST_WINDOW_START}:00 - {POST_WINDOW_END}:00")
    remaining = [t for t in state.get('post_times', []) if t not in state.get('posted_times', [])]
    if remaining:
        print(f"  Next post at:   ~{remaining[0]}")
    else:
        print(f"  Next post at:   (done for today)")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description='Randomized blog auto-poster')
    parser.add_argument('--force', action='store_true', help='Force post now regardless of schedule')
    parser.add_argument('--status', action='store_true', help='Show schedule status')
    parser.add_argument('--dry-run', action='store_true', help='Dry-run (no publishing)')
    args = parser.parse_args()

    state = load_state()
    state = init_day(state)

    if args.status:
        print_status(state)
        return

    if args.force:
        logger.info("Force posting...")
        success = run_blog_engine(dry_run=args.dry_run)
        if success and not args.dry_run:
            record_post(state)
        return

    # Normal mode: check if we should post
    should_post, reason = should_post_now(state)
    logger.info(f"Schedule check: {'POST' if should_post else 'SKIP'} — {reason}")

    if should_post:
        success = run_blog_engine(dry_run=args.dry_run)
        if success and not args.dry_run:
            record_post(state)
    else:
        logger.info("Skipping this cycle.")


if __name__ == '__main__':
    main()
