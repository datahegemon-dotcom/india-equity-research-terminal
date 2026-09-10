# Container for hosting the workbench.
#
# Works anywhere that runs a Dockerfile: Render, Hugging Face Spaces, Fly, Koyeb.
# The platform sets PORT, which is what switches the app from listening on the
# loopback address to listening on every interface.
#
# There is no authentication. On a public address, anyone who finds it has full
# access to the reports inside. That is the operator's stated choice.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY site ./site

# Reports live here. Mount a persistent volume at /data on any platform that
# offers one, otherwise the database is lost each time the instance restarts.
ENV IERT_DB=/data/terminal.db
RUN mkdir -p /data

EXPOSE 8848
ENV PORT=8848

CMD ["python", "-m", "app.main"]
