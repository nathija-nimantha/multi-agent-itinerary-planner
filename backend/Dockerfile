# Backend-only image. The frontend is built and served separately by Vercel, so
# there is no Node stage here and nothing is mounted at "/" — this container
# answers /api/* and nothing else.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# app/ and kb/ sit side by side because config.py resolves KB_PATH as
# ROOT/kb/sri_lanka.json, where ROOT is the parent of app/.
COPY app ./app
COPY kb ./kb

# Render injects PORT; 10000 is its default and only a local fallback here.
ENV PORT=10000
EXPOSE 10000

# Shell form so ${PORT} expands; `exec` gives uvicorn PID 1 so SIGTERM reaches
# it and the instance shuts down cleanly.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
