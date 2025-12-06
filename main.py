# main.py
import os
import logging
import re
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import redis
from rq import Queue

import db, validator
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quizbot.main")

if not config.TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set in env")

bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Init DB
db.set_db_path(config.DB_PATH)
db.init_db(owner_tg_id=config.OWNER_TG_ID)

# Redis & RQ
redis_conn = redis.from_url(config.REDIS_URL)
queue = Queue("quiz-jobs", connection=redis_conn, default_timeout=3600)

DES_START_RE = re.compile(r"^\s*DES:", re.IGNORECASE)

async def is_sudo(user_id: int) -> bool:
    if user_id == config.OWNER_TG_ID:
        return True
    return db.is_sudo(user_id)

def owner_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📩 Format help", callback_data="help:format"))
    kb.add(InlineKeyboardButton("👤 List sudos", callback_data="admin:list_sudos"))
    return kb

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    if await is_sudo(uid):
        caption = [
            "🛡️ BLACK RHINO CONTROL PANEL",
            "Welcome, Boss 👑",
            "",
            "🚀 Send a formatted quiz (DES/Q/A/ANS style).",
            "You may include: TARGET: <chat_id or @channel> to set posting target for this quiz.",
            "",
            "Use /format_help for an example."
        ]
        await message.reply("\n".join(caption), reply_markup=owner_keyboard())
    else:
        await message.reply(
            "🚫 This is a private bot.\nThis bot is for the owner / sudo users only."
        )

@dp.message(Command("format_help"))
async def cmd_format_help(message: types.Message):
    await message.reply(
        "Required format example:\n\n"
        "DES: ❓Example Quiz❓\n"
        "TARGET: -1001234567890   (optional; channel id or @channelname)\n\n"
        "Q: What is 2+2?\n"
        "A: (A) 3\n"
        "B: (B) 4\n"
        "C: (C) 5\n"
        "D: (D) 2\n"
        "ANS: B\n"
        "EXP: simple math (optional)\n\n"
        "DES: Example Quiz COMPLETED ✅\n\n"
        "Send as a single message. Bot will validate and enqueue the quiz."
    )

@dp.message(Command("add_sudo"))
async def cmd_add_sudo(message: types.Message):
    uid = message.from_user.id
    if not await is_sudo(uid):
        return await message.reply("Not authorized.")
    args = message.get_args().strip()
    if args.isdigit():
        new_id = int(args)
    elif message.reply_to_message:
        new_id = message.reply_to_message.from_user.id
    else:
        return await message.reply("Usage: /add_sudo <tg_id> or reply to message.")
    db.add_sudo(new_id, name=None, added_by=uid)
    await message.reply(f"✅ Added sudo user: {new_id}")

@dp.message(Command("remove_sudo"))
async def cmd_remove_sudo(message: types.Message):
    uid = message.from_user.id
    if not await is_sudo(uid):
        return await message.reply("Not authorized.")
    args = message.get_args().strip()
    if args.isdigit():
        rem_id = int(args)
    elif message.reply_to_message:
        rem_id = message.reply_to_message.from_user.id
    else:
        return await message.reply("Usage: /remove_sudo <tg_id> or reply to message.")
    db.remove_sudo(rem_id)
    await message.reply(f"✅ Removed sudo user: {rem_id}")

@dp.message(Command("list_sudos"))
async def cmd_list_sudos(message: types.Message):
    uid = message.from_user.id
    if not await is_sudo(uid):
        return await message.reply("Not authorized.")
    sudos = db.list_sudos()
    if not sudos:
        return await message.reply("No sudo users.")
    lines = ["Sudo users:"]
    for s in sudos:
        lines.append(f"- {s.get('tg_id')}")
    await message.reply("\n".join(lines))

@dp.message()
async def handle_message(message: types.Message):
    uid = message.from_user.id
    text = message.text or ""
    if not await is_sudo(uid):
        return await message.reply("🚫 This is a private bot. No action.")

    if DES_START_RE.match(text):
        ok, res = validator.validate_and_parse(text)
        if not ok:
            # short error message as requested
            await message.reply(f"⚠️ Format error: {res}\nUse /format_help")
            return

        title = res.get("title")
        target = res.get("target")
        questions = res.get("questions")
        if not target:
            # ask owner to provide target
            await message.reply(
                "ℹ️ No TARGET found in message. Please reply with:\n"
                "`/postto <chat_id_or_@channel>`\n"
                "to post this quiz now.",
                parse_mode="Markdown"
            )
            # store pending job to redis key for owner
            pending_key = f"pending_quiz:{uid}"
            # store minimal data as string (avoid pickling)
            import json
            job_payload = {
                "title": title,
                "target": None,
                "questions": questions,
                "owner_id": uid
            }
            r = redis.from_url(config.REDIS_URL)
            r.set(pending_key, json.dumps(job_payload), ex=3600)
            await message.reply("✅ Quiz saved temporarily for 1 hour. Use /postto to post it.")
            return

        # enqueue directly
        job_payload = {
            "type": "formatted",
            "owner_id": uid,
            "title": title,
            "target": target,
            "questions": questions
        }
        try:
            job = queue.enqueue("worker.process_formatted_job", job_payload)
            await message.reply(f"🔄 Quiz accepted and queued (job id: {job.id}). Will post to {target}.")
        except Exception as e:
            logger.exception("Failed to enqueue job: %s", e)
            await message.reply("❌ Failed to queue the quiz. Check logs.")
        return

    # if not formatted input
    return await message.reply("Unrecognized input. Send formatted quiz or use /format_help.")

@dp.message(Command("postto"))
async def cmd_postto(message: types.Message):
    uid = message.from_user.id
    if not await is_sudo(uid):
        return await message.reply("Not authorized.")
    args = message.get_args().strip()
    if not args:
        return await message.reply("Usage: /postto <chat_id_or_@channel>")
    target = args
    pending_key = f"pending_quiz:{uid}"
    r = redis.from_url(config.REDIS_URL)
    import json
    raw = r.get(pending_key)
    if not raw:
        return await message.reply("No pending quiz found. Send formatted quiz first.")
    try:
        job_payload = json.loads(raw)
    except:
        return await message.reply("Stored quiz data corrupted.")
    job_payload["target"] = target
    job_payload["owner_id"] = uid
    try:
        job = queue.enqueue("worker.process_formatted_job", job_payload)
        r.delete(pending_key)
        await message.reply(f"🔄 Pending quiz queued (job id: {job.id}). Will post to {target}.")
    except Exception as e:
        logger.exception("Failed to enqueue pending job: %s", e)
        await message.reply("❌ Failed to queue the quiz. Check logs.")

# startup/shutdown
async def on_startup():
    logger.info("Bot startup")
    try:
        redis_conn.ping()
        logger.info("Redis reachable")
    except Exception as e:
        logger.warning("Redis unreachable: %s", e)

async def on_shutdown():
    await bot.session.close()

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
