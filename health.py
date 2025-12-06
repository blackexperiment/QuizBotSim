# health.py
from flask import Flask, jsonify
import os
import time
import sqlite3

app = Flask(__name__)

DB_PATH = os.getenv("DB_PATH", "./botdata.sqlite")
OWNER_TG_ID = os.getenv("OWNER_TG_ID", "not_set")
APP_VERSION = os.getenv("APP_VERSION", "dev")

def db_exists():
    return os.path.exists(DB_PATH)

def db_check():
    try:
        if not db_exists():
            return False
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False

@app.route("/")
def root():
    return "QuizBot health server is running."

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "timestamp": int(time.time()),
        "db_found": db_exists(),
        "db_valid": db_check(),
        "owner": OWNER_TG_ID,
        "version": APP_VERSION
    })

@app.route("/info")
def info():
    return jsonify({
        "service": "quizbot",
        "env": "render",
        "version": APP_VERSION,
        "owner": OWNER_TG_ID,
        "db_path": DB_PATH
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
