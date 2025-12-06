# main.py
import os
import logging
import asyncio
import re
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import redis
from rq import Queue

import db
import validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quizbot.main")

# Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_TG_ID = int(os.getenv("OWNER_TG_ID", "0"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_PATH = os.getenv("DB_PATH", "/home/render/project/botdata.sqlite")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN env var is required")

# Set DB path and init
db.set_db_path(DB_PATH)
db.init_db(owner_tg_id=OWNER_TG_ID)

# Bot & dispatcher
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# RQ queue
redis_conn = redis.from_url(REDIS_URL)
queue = Queue("quiz-jobs", connection=redis_conn, default_timeout=3600)


# --- helper checks ---
async def is_sudo(user_id: int) -> bool:
    if user_id == OWNER_TG_ID:
        return True
    return db.is_sudo(user_id)


def owner_panel_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📢 Channel / Group Management", callback_data="settings:channels"),
        InlineKeyboardButton("👤 Sudo Users", callback_data="settings:sudo"),
    )
    kb.add(
        InlineKeyboardButton("⚙️ Bot Settings", callback_data="settings:bot"),
    )
    return kb


# --- commands ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    if await is_sudo(uid):
        # Owner view
        caption_lines = [
            "🛡️ BLACK RHINO CONTROL PANEL",
            "Welcome, Boss 👑",
            "",
            "🚀 Want a quiz?",
            "📩 Send the formatted quiz (DES/Q/A/ANS style) and I’ll post it to the default channel.",
            "",
            "Use /format_help to see the required format."
        ]
        await message.reply("\n".join(caption_lines), reply_markup=owner_panel_keyboard())
    else:
        await message.reply(
            "🚫 This is a private bot.\n\n"
            "This bot is restricted and can be used only by the authorized owner.\n"
            "If you reached here by mistake — no action needed."
        )


@dp.message(Command("format_help"))
async def cmd_format_help(message: types.Message):
    await message.reply(
        "Required format example:\n\n"
        "DES: ❓TITLE❓\n\n"
        "Q: Sample question?\n"
        "A: (A) Option text\n"
        "B: (B) Option text\n"
        "C: (C) Option text\n"
        "D: (D) Option text\n"
        "ANS: A\n"
        "EXP: Short explanation (optional)\n\n"
        "DES: TITLE COMPLETED ✅\n\n"
        "Send the entire block as a single message. The bot will validate and queue the quiz."
    )


@dp.message(Command("set_target"))
async def cmd_set_target(msg: types.Message):
    uid = msg.from_user.id
    if not await is_sudo(uid):
        return await msg.reply("Not authorized.")
    arg = msg.get_args().strip()
    if not arg:
        return await msg.reply("Usage: /set_target <chat_id>")
    try:
        chat_id = int(arg)
    except:
        return await msg.reply("Invalid chat id.")
    db.set_default_target(chat_id)
    await msg.reply(f"✅ Default target set to {chat_id}")


@dp.message(Command("add_sudo"))
async def cmd_add_sudo(msg: types.Message):
    uid = msg.from_user.id
    if not await is_sudo(uid):
        return await msg.reply("Not authorized.")
    args = msg.get_args().strip()
    new_id = None
    if args.isdigit():
        new_id = int(args)
    elif msg.reply_to_message:
        new_id = msg.reply_to_message.from_user.id
    else:
        return await msg.reply("Usage: /add_sudo <tg_id> or reply to a user's message with /add_sudo")
    db.add_sudo(new_id, name=None, added_by=uid)
    await msg.reply(f"✅ Added sudo user: {new_id}")


@dp.message(Command("remove_sudo"))
async def cmd_remove_sudo(msg: types.Message):
    uid = msg.from_user.id
    if not await is_sudo(uid):
        return await msg.reply("Not authorized.")
    args = msg.get_args().strip()
    rem_id = None
    if args.isdigit():
        rem_id = int(args)
    elif msg.reply_to_message:
        rem_id = msg.reply_to_message.from_user.id
    else:
        return await msg.reply("Usage: /remove_sudo <tg_id> or reply to a message with /remove_sudo")
    db.remove_sudo(rem_id)
    await msg.reply(f"✅ Removed sudo user: {rem_id}")


@dp.message(Command("list_sudos"))
async def cmd_list_sudos(msg: types.Message):
    uid = msg.from_user.id
    if not await is_sudo(uid):
        return await msg.reply("Not authorized.")
    sudos = db.list_sudos()
    if not sudos:
        return await msg.reply("No sudo users.")
    lines = ["Sudo users:"]
    for s in sudos:
        lines.append(f"- {s.get('tg_id')}")
    await msg.reply("\n".join(lines))


# Settings callback (simple)
@dp.callback_query(lambda c: c.data and c.data.startswith("settings:"))
async def cb_settings(query: types.CallbackQuery):
    user_id = query.from_user.id
    if not await is_sudo(user_id):
        return await query.answer("Not authorized", show_alert=True)
    kind = query.data.split(":", 1)[1]
    if kind == "channels":
        default = db.get_default_target(user_id)
        text = f"📢 Channel / Group Management\n\nDefault target chat id: {default}\n\nUse /set_target <chat_id> to set."
        await query.message.edit_text(text)
    elif kind == "sudo":
        sudos = db.list_sudos()
        lines = ["👤 Sudo Users\n"]
        for s in sudos:
            lines.append(f"- {s.get('tg_id')}")
        lines.append("\nUse /add_sudo <tg_id> or reply to a user's message with /add_sudo")
        await query.message.edit_text("\n".join(lines))
    else:
        await query.message.edit_text("Settings — feature coming soon.")
    await query.answer()


# Regex to detect if message starts with DES:
DES_START_RE = re.compile(r"^\s*DES:\s*", re.IGNORECASE)


@dp.message()
async def handle_message(message: types.Message):
    uid = message.from_user.id
    text = message.text or ""
    if not await is_sudo(uid):
        return await message.reply("🚫 This is a private bot. No action.")

    # If message begins with DES:, treat as formatted quiz input
    if DES_START_RE.match(text):
        # Validate locally first
        ok, result = validator.validate_and_parse(text)
        if not ok:
            # Validation failed: send clear error to owner
            # result is error message
            await message.reply(f"⚠️ Format error:\n{result}\n\nUse /format_help to see the required format.")
            return

        # Parse success: result is list of question dicts
        parsed_questions = result  # list of {"q","options","ans","exp"}
        title = validator.extract_title_from_formatted(text) or "Untitled Quiz"
        target_chat = db.get_default_target(uid)

        job_payload = {
            "type": "formatted",
            "owner_id": uid,
            "title": title,
            "target": target_chat,
            "questions": parsed_questions,
        }

        # Enqueue job
        try:
            job = queue.enqueue("worker.process_formatted_job", job_payload)
            await message.reply(f"🔄 Quiz accepted and queued (job id: {job.id}). Will be posted to default channel {target_chat}.")
        except Exception as e:
            logger.exception("Failed to enqueue job: %s", e)
            await message.reply("❌ Failed to queue the quiz. Check logs.")
        return

    # Unrecognized input for owner
    await message.reply(
        "🚫 Unrecognized input. Send the quiz in the required DES/Q/A/ANS format. Use /format_help for an example."
    )


# Startup/shutdown
async def on_startup():
    logger.info("Bot startup: initializing DB and queue health check")
    db.init_db(owner_tg_id=OWNER_TG_ID)
    # quick redis ping
    try:
        redis_conn.ping()
        logger.info("Redis reachable")
    except Exception as e:
        logger.warning("Cannot reach Redis: %s", e)


async def on_shutdown():
    logger.info("Shutting down bot...")
    await bot.session.close()


if __name__ == "__main__":
    from aiogram import executor
    try:
        asyncio.run(on_startup())
    except Exception:
        pass
    executor.start_polling(dp, skip_updates=True, on_shutdown=on_shutdown)
