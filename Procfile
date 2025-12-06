web: gunicorn health:app --bind 0.0.0.0:$PORT --workers 1
bot: python3 main.py
worker: rq worker -u ${REDIS_URL} quiz-jobs
