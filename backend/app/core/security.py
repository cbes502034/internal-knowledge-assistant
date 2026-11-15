from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings


# Password Hashing
passwordHasher = PasswordHasher()


def hashPassword(password: str) -> str:
    return passwordHasher.hash(password)


def verifyPassword(password: str, hashedPassword: str) -> bool:
    try:
        return passwordHasher.verify(hashedPassword, password)
    except (VerifyMismatchError, VerificationError):
        return False


# JWT
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token"  # Swagger 的 Authorize 按鈕會打這個端點登入
)


def createAccessToken(
    userId: int,
    deptId: int,
    role: str,
) -> str:
    expireAt = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(userId),
        "dept": deptId,
        "role": role,
        "exp": expireAt,
    }

    token = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=ALGORITHM,
    )

    return token


def decodeAccessToken(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[ALGORITHM],
    )

    return payload