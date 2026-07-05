FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries needed by lxml and trafilatura at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY sql ./sql
COPY widget ./widget

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["sitebot", "serve", "--host", "0.0.0.0", "--port", "8000"]
