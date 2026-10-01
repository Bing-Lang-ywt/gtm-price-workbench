FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 供容器健康检查；其余为 Playwright Chromium 运行时依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
        libasound2 libatspi2.0-0 libxshmfence1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

# 完整依赖（含 playwright）。VPS 全栈含定时爬虫，ENABLE_SPA_CRAWL=1 需要浏览器，
# 故不再像“只读展示快照”那样剔除 playwright。
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium 装到全局可读路径，供运行态非 root 用户(appuser)使用
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium \
    && chmod -R a+rX /ms-playwright

COPY app ./app

# 数据库落在挂载卷上，容器重建不丢数据
ENV DATABASE_URL=sqlite:////data/price_monitor.db

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
