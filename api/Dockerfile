# Cable-fault locator API (stdlib-only Python, no pip installs required).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    API_PORT=8000

WORKDIR /app
COPY app ./app

EXPOSE 8000
CMD ["python", "-m", "app.server"]
