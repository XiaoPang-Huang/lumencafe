import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import WhitelistUser
from ..schemas import AuthOut, WechatLoginIn
from ..security import create_token

logger = logging.getLogger("island.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

WECHAT_CODE2SESSION = "https://api.weixin.qq.com/sns/jscode2session"


async def code_to_openid(code: str) -> str:
    """微信 wx.login 的 code 换 openid。

    开发模式下，code 以 "dev:" 开头时直接视为 openid（如 dev:user1），
    方便在没有真实 AppID 时本地联调。
    """
    if settings.dev_login and code.startswith("dev:"):
        return code
    if not settings.wechat_appid or not settings.wechat_secret:
        raise HTTPException(status_code=500, detail="服务端未配置微信 AppID/Secret")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            WECHAT_CODE2SESSION,
            params={
                "appid": settings.wechat_appid,
                "secret": settings.wechat_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
    data = resp.json()
    if "openid" not in data:
        # 详情只进服务端日志，不给调用方（避免泄露配置信息）
        logger.warning("wechat code2session failed: %s", data.get("errmsg"))
        raise HTTPException(status_code=502, detail="微信登录服务暂时不可用")
    return data["openid"]


@router.post("/wechat", response_model=AuthOut)
async def wechat_login(body: WechatLoginIn, db: AsyncSession = Depends(get_db)):
    openid = await code_to_openid(body.code)
    user = (
        await db.execute(select(WhitelistUser).where(WhitelistUser.openid == openid))
    ).scalar_one_or_none()
    if user is None:
        # 不在白名单：不报错，由前端展示「未授权」页。不回传 openid，减少信息暴露。
        # openid 记入服务端日志，便于管理员把人加进白名单。
        logger.info("login rejected (not in whitelist): openid=%s", openid)
        return AuthOut(authorized=False)
    return AuthOut(
        authorized=True,
        token=create_token(openid),
        user={"openid": user.openid, "nickname": user.nickname, "role": user.role},
    )
