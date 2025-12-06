# worker.py
import os
import logging
import time
from typing import Dict, List

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quizbot.worker")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_TG_ID = int(os.getenv("OWNER_TG_ID", "0"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN env var is required")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# -------------------------
# MAIN JOB EXECUTOR
# -------------------------

def process_formatted_job(payload: Dict):
    """
    Called by RQ worker when main.py enqueues a quiz job.
    payload format:

    {
        "type": "formatted",
        "owner_id": <int>,
        "title": <str>,
        "target": <chat_id>,
        "questions": [
            {
                "q": "...",
                "options": ["(A) ...", "(B) ...", ...],
                "ans": "A",
                "exp": "optional explanation or None"
            },
            ...
        ]
    }
    """

    owner_id = payload["owner_id"]
    target_chat = payload["target"]
    title = payload["title"]
    questions = payload["questions"]

    logger.info(f"Starting quiz job for target {target_chat} with {len(questions)} questions")

    # Step 1 — Send header message
    header_text = f"🎯 *Starting Quiz:*\n*{title}*\n\nTotal Questions: {len(questions)}"
    _safe_send_message(owner_id, f"🔄 Quiz job started: {title}")
    _safe_send_message(target_chat, header_text, parse_mode="Markdown")

    # Step 2 — Post quiz polls one-by-one
    for idx, qdata in enumerate(questions, start=1):

        question_text = f"Q{idx}. {qdata['q']}"
        options = qdata["options"]
        correct_letter = qdata["ans"].strip().upper()

        # Convert letter → index
        try:
            correct_index = _letter_to_index(correct_letter)
        except:
            # Invalid ANS, skip but alert
            _safe_send_message(owner_id, f"⚠️ Invalid ANS '{correct_letter}' in question {idx}. Skipped.")
            continue

        try:
            bot.send_poll(
                chat_id=target_chat,
                question=question_text,
                options=options,
                type="quiz",
                correct_option_id=correct_index,
                is_anonymous=False
            )
            logger.info(f"Sent Q{idx}")
        except TelegramRetryAfter as e:
            # Rate limit — wait and retry
            delay = int(e.retry_after) + 1
            logger.warning(f"Rate limit hit. Waiting {delay}s")
            time.sleep(delay)
            bot.send_poll(
                chat_id=target_chat,
                question=question_text,
                options=options,
                type="quiz",
                correct_option_id=correct_index,
                is_anonymous=False
            )
        except TelegramForbiddenError:
            # Bot can't send to chat — notify owner
            _safe_send_message(owner_id, f"❌ Bot cannot send messages to {target_chat}. Check permissions.")
            return
        except Exception as e:
            logger.exception(f"Error sending Q{idx}: {e}")
            _safe_send_message(owner_id, f"❌ Failed to send Question {idx}. Check logs.")
            continue

        # Slow down for rate limits — safe value
        time.sleep(0.8)

    # Step 3 — Final "Quiz Completed" message
    _safe_send_message(target_chat, "✅ *Quiz Completed!*", parse_mode="Markdown")
    _safe_send_message(owner_id, f"🎉 Quiz completed successfully: {title}")

    logger.info("Quiz job finished")


# -------------------------
# Helper functions
# -------------------------

def _safe_send_message(chat_id: int, text: str, parse_mode=None):
    """
    Safely send a message without crashing worker.
    """
    try:
        bot.send_message(chat_id, text, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Could not send message to {chat_id}: {e}")


def _letter_to_index(letter: str) -> int:
    """
    Convert A/B/C/D/E/F → 0/1/2/3/4...
    """
    return ord(letter.upper()) - ord("A")
