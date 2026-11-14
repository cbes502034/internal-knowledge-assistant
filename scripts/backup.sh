#!/usr/bin/env bash
# 資料庫備份（對應職缺：Linux 環境操作、Shell Script 撰寫）
#
# 用法（在專案根目錄）：
#   bash scripts/backup.sh               備份到 backups/<資料庫>_<時間>.sql.gz，保留最近 7 份
#   KEEP=14 bash scripts/backup.sh       保留最近 14 份
# 排程（Linux 主機，每天凌晨 3 點）：
#   0 3 * * * cd /opt/knowledge-assistant && bash scripts/backup.sh >> backups/backup.log 2>&1
# 還原（先還原到新的資料庫驗證，確認沒問題再切換）：
#   docker compose exec -T db createdb -U <使用者> restore_check
#   gunzip -c backups/<檔名>.sql.gz | docker compose exec -T db psql -U <使用者> -d restore_check
set -euo pipefail                      # 任何一步失敗就停止；管線中任一段失敗也算失敗

cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  set -a; source .env; set +a          # 讀 POSTGRES_USER、POSTGRES_DB
fi
DB_USER="${POSTGRES_USER:?請在 .env 設定 POSTGRES_USER}"
DB_NAME="${POSTGRES_DB:?請在 .env 設定 POSTGRES_DB}"
KEEP="${KEEP:-7}"

mkdir -p backups
file="backups/${DB_NAME}_$(date +%Y%m%d_%H%M%S).sql.gz"
trap 'rm -f "$file.partial"' EXIT      # 中途失敗不留下半個檔案

docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner | gzip > "$file.partial"
if [[ ! -s "$file.partial" ]] || ! gzip -t "$file.partial"; then
  echo "備份失敗：檔案是空的或壓縮檔損壞" >&2
  exit 1
fi
mv "$file.partial" "$file"
echo "已備份：$file（$(du -h "$file" | cut -f1)）"

# 只保留最近 KEEP 份（依修改時間排序，新的在前）
ls -1t backups/"${DB_NAME}"_*.sql.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f -- "$old"
  echo "已刪除舊備份：$old"
done
