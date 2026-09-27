# One-shot verification image: code tests + frontend build + API smoke.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    API_URL=http://api:8000 \
    WEB_URL=http://web

WORKDIR /app
COPY api ./api
COPY tests ./tests
COPY web ./web
COPY verify ./verify

CMD ["python", "-m", "verify.run"]
