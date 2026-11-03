FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt

ARG WITH_ML=1
RUN if [ "$WITH_ML" = "1" ]; then \
        pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 torchvision==0.29.2 \
        && pip install -r requirements-ml.txt; \
    fi

COPY . .

RUN useradd --create-home --uid 1000 app \
    && mkdir -p media protected var staticfiles \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--proxy-headers", "config.asgi:application"]
