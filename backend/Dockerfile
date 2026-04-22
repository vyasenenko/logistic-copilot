FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps + FFmpeg + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gcc libpq-dev ffmpeg fonts-dejavu-core && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install deps via subprocess (not shell-joined): commas in specifiers break `pip install $(...)`
RUN python <<'PY'
import subprocess
import tomllib

with open("pyproject.toml", "rb") as f:
    deps = tomllib.load(f)["project"]["dependencies"]
subprocess.check_call(["pip", "install", "--no-cache-dir", *deps])
PY

COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
