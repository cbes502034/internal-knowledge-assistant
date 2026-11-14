FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 不用 root 執行：程式被攻破時，攻擊者在容器內的權限也有限。
# 上傳目錄先建好並交給這個使用者，掛上具名 volume 時會沿用這個擁有者。
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /srv/data/uploads && chown -R app /srv/data
USER app

# 啟動前先套用資料表結構
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
