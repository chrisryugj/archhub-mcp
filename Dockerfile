# 건축HUB MCP — fly.io 배포용 (streamable-http)
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY archhub ./archhub

# non-root 사용자
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

ENV MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["python", "-m", "archhub", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
