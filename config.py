# config.py
import os

def env(key: str, default=None):
    val = os.getenv(key, default)
    return val

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
OWNER_TG_ID = int(env("OWNER_TG_ID", "0")) if env("OWNER_TG_ID") else 0
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
DB_PATH = env("DB_PATH", "/home/render/project/botdata.sqlite")
APP_VERSION = env("APP_VERSION", "v1")

# Safety defaults
POLL_DELAY = float(env("POLL_DELAY", "1.0"))  # seconds between polls (default 1.0)
