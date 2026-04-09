FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps + FFmpeg + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev ffmpeg fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir $(python -c "import tomllib; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; print(' '.join(deps))")

COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
