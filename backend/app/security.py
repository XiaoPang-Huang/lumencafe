"""密码哈希（bcrypt）与 JWT 签发/校验。

- sub = user.id（字符串形式），过期 = settings.jwt_expire_days 天；
- 校验失败统一抛 PyJWTError / ValueError，由 deps 层转 401。
"""
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> int:
    """解出 user.id；签名/过期问题抛 jwt.PyJWTError。"""
    return int(jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])["sub"])
