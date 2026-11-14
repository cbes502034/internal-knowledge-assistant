#!/usr/bin/env bash
# 資料庫備份（對應職缺：Linux 環境操作、Shell Script 撰寫）
#
# TODO：完成這支腳本
#   1. set -euo pipefail          —— 任何一步失敗就停止
#   2. 從專案根目錄的 .env 讀取 POSTGRES_USER、POSTGRES_DB
#   3. 備份檔放在 backups/，檔名帶時間，例如 assistant_20261114_0300.sql.gz
#   4. 用 docker compose exec -T db pg_dump ... | gzip > 檔案
#   5. 備份完成後檢查檔案大小不為 0，否則以非 0 狀態結束
#   6. 只保留最近 7 份，刪除更舊的
#   7. 思考：怎麼驗證備份檔真的可以還原？怎麼排程每天執行（cron）？
echo "scripts/backup.sh 尚未實作" >&2
exit 1
