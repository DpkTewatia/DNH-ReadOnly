# FileVault — read-only file server for a folder of images and text.
#
# No build stage: the app is Python, so the image is the runtime plus three
# dependencies. The served folder is never baked in — it is bind-mounted at
# /data, and the app refuses to start if it overlaps /app.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FILEVAULT_ROOT_PATH=/data

# Only nginx on the host can reach this container, so forwarded headers from it
# are trusted; without this every refusal would be logged against the Docker
# bridge address rather than the real caller. Kept out of the ENV above because
# a comment inside a line continuation is not handled the same way by every
# builder.
ENV FORWARDED_ALLOW_IPS=*

WORKDIR /app

# Requirements first: this layer is cached until a dependency changes, so
# editing the app does not re-run pip.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# uid 1654 matches the user the .NET image used, which is the uid the deploy
# pipeline checks the media folder against. The mount point is created here so
# a missing volume fails as "empty vault" rather than as a permissions error.
RUN useradd --uid 1654 --no-create-home --shell /usr/sbin/nologin filevault \
    && mkdir -p /data

USER 1654

EXPOSE 8080

# python rather than curl: the slim image ships neither curl nor wget, and the
# interpreter is already here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request as r; r.urlopen('http://127.0.0.1:8080/healthz', timeout=4)" || exit 1

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
