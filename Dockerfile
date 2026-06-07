# Nebula archiver web service (FastAPI + background worker/scheduler).
# Runs serve.py -> uvicorn on 0.0.0.0:8000.
FROM python:3.14-slim

# ffmpeg: yt-dlp merges bestvideo+bestaudio. curl: container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pipenv

WORKDIR /app

# Install deps into the system interpreter (no venv needed inside a container).
COPY Pipfile Pipfile.lock ./
RUN pipenv install --system --deploy

COPY src ./src

# serve.py imports app modules as top-level packages (api, config, ...).
WORKDIR /app/src

EXPOSE 8000

CMD ["python", "serve.py"]
