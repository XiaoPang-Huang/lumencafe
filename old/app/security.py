import jwt
from datetime import datetime, timedelta, timezone

from .config import settings

ALGO = "HS256"


def create_token(openid: str) -> str:
    payload = {
        "sub": openid,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> str:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])["sub"]
