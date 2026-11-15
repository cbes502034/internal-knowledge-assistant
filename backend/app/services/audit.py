"""
稽核紀錄：每個重要動作寫一筆「誰、何時、從哪、做了什麼、對象」。
對應職缺：資訊安全、內部系統的可追溯性。

只記事件本身，不記問題內容、密碼、文件本文：日誌通常比資料庫更多人看得到，
放進機密內容就等於多開一個外洩的口。
"""

import ipaddress

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def client_ip(request: Request) -> str | None:
    """
    取來源 IP。只取直接連進來的那一端，不信任 X-Forwarded-For 標頭：
    那個標頭任何人都能自己填，前面沒有可信任的反向代理時，拿它當 IP 等於讓攻擊者自己決定紀錄內容。
    """
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:  # 例如測試工具的 "testclient"，不是合法 IP 就不記
        return None


def log_event(
    db: Session,
    request: Request,
    action: str,
    *,
    user_id: int | None = None,
    target: str | None = None,
) -> None:
    """新增一筆稽核紀錄並立刻 commit：紀錄要在主要動作完成之後寫，失敗的動作也要記（例如登入失敗）。"""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target=target[:100] if target else None,  # 欄位上限 100 字
            ip=client_ip(request),
        )
    )
    db.commit()
