"""測試用的假模型與共用的小工具。"""
import math
import zlib

from app.core.bm25 import tokenize
from app.core.llm_service import LLMUnavailableError

DIM = 1024


def fake_vector(text: str) -> list[float]:
    """把 bigram 雜湊到 1024 維再正規化：字面越相近的文字，向量越相近。結果固定、不需要模型。"""
    vector = [0.0] * DIM
    for token in tokenize(text):
        vector[zlib.crc32(token.encode("utf-8")) % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeLLM:
    embed_model = "fake-embed"
    gen_model = "fake-gen"

    def __init__(self):
        self.embedded = 0           # 總共算了幾段向量（用來驗證重新處理會沿用舊向量）
        self.generated = 0
        self.down = False           # True：模擬模型服務掛掉
        self.answer = "依據資料辦理。[1]"
        self.last_prompt = ""
        self.last_system = ""

    def embed_many(self, texts):
        if self.down:
            raise LLMUnavailableError("down")
        self.embedded += len(texts)
        return [fake_vector(t) for t in texts]

    def embed(self, text):
        return self.embed_many([text])[0]

    def generate(self, prompt, *, system=None):
        if self.down:
            raise LLMUnavailableError("down")
        self.generated += 1
        self.last_prompt, self.last_system = prompt, system or ""
        return self.answer

    def ping(self):
        return [self.embed_model, self.gen_model]


PASSWORD = "correct-horse-battery"


def register(client, email: str, dept: str = "ops"):
    return client.post("/api/v1/users", json={"email": email, "password": PASSWORD, "dept_code": dept})


def login(client, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/token",
                       data={"grant_type": "password", "username": email, "password": password})


def set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.execute(update(User).where(User.email == email).values(role=role))
        db.commit()


def make_user(client, email: str, dept: str = "ops", role: str = "employee") -> dict:
    """註冊、設定角色、登入，回傳 Authorization 標頭。"""
    assert register(client, email, dept).status_code == 201
    if role != "employee":
        set_role(email, role)
    token = login(client, email).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
