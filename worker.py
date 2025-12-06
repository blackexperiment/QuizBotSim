# worker.py
import os
import logging
import time
import redis
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quizbot.worker")

BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
OWNER_ID = config.OWNER_TG_ID
POLL_DELAY = config.POLL_DELAY

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

bot = Bot(token=BOT_TOKEN)

def _letter_to_index(letter: str) -> int:
    return ord(letter.upper()) - ord("A")

def _safe_send_message(chat_id: int, text: str, parse_mode=None):
    try:
        bot.send_message(chat_id, text, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Could not send message to {chat_id}: {e}")

def process_formatted_job(payload: dict):
    owner_id = payload.get("owner_id")
    target_chat = payload.get("target")
    title = payload.get("title", "Untitled Quiz")
    questions = payload.get("questions", [])

    logger.info(f"Starting quiz job for {target_chat} with {len(questions)} questions")

    try:
        _safe_send_message(owner_id, f"🔄 Quiz job started: {title}")
        header_text = f"🎯 *Starting Quiz:* {title}\nTotal Questions: {len(questions)}"
        _safe_send_message(target_chat, header_text, parse_mode="Markdown")
    except Exception as e:
        logger.warning("Unable to send header: %s", e)

    for idx, q in enumerate(questions, start=1):
        question_text = f"Q{idx}. {q['q']}"
        options = q["options"]
        correct_letter = q["ans"].strip().upper()
        try:
            correct_index = _letter_to_index(correct_letter)
        except:
            _safe_send_message(owner_id, f"⚠️ Invalid ANS '{correct_letter}' in question {idx}. Skipped.")
            logger.warning("Invalid ANS for question %d: %s", idx, correct_letter)
            continue

        # Send poll
        try:
            bot.send_poll(
                chat_id=target_chat,
                question=question_text,
                options=options,
                type="quiz",
                correct_option_id=correct_index,
                is_anonymous=False
            )
            logger.info("Sent Q%d", idx)
        except TelegramRetryAfter as e:
            delay = int(e.retry_after) + 1
            logger.warning("Rate limit hit. Sleeping %s seconds", delay)
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
            _safe_send_message(owner_id, f"❌ Bot cannot send messages to {target_chat}. Check permissions.")
            logger.exception("Forbidden sending to %s", target_chat)
            return
        except Exception as e:
            logger.exception("Error sending Q%d: %s", idx, e)
            _safe_send_message(owner_id, f"❌ Failed to send Question {idx}. Check logs.")
            continue

        # optional EXP message under poll to the owner (not to channel)
        if q.get("exp"):
            _safe_send_message(owner_id, f"Q{idx} explanation: {q.get('exp')}")

        time.sleep(POLL_DELAY)

    _safe_send_message(target_chat, "✅ *Quiz Completed!*", parse_mode="Markdown")
    _safe_send_message(owner_id, f"🎉 Quiz completed successfully: {title}")
    logger.info("Quiz job finished")
