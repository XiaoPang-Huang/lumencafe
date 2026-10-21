"""平台管理-模型管理（PRD §4.3，权限点 admin:models）。

- Provider 条目 = 厂商×套餐平级（架构定稿修订3）；api_key 脱敏回显（§9.1）；
- 默认路由 = providers.is_default + llm_models.is_default 两标记（Q10/Q13），
  部分唯一索引兜底全库至多一个，切换时同事务先清旧标记；
- fetch-models 调官方 GET {base_url}/models 平铺入库（custom/enabled 保留）；
- 网关令牌（Q17）：仅存 sha256 哈希 + 掩码，完整令牌仅创建时返回一次。
"""
import hashlib
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.llm import GatewayToken, LLMModel, Provider
from app.models.user import User
from app.schemas.llm import (
    DEFAULT_MODEL_META,
    VENDOR_WHITELIST,
    DefaultRouteOut,
    DefaultRouteSet,
    FetchedModel,
    GatewayTokenCreate,
    GatewayTokenCreated,
    GatewayTokenOut,
    ModelCreate,
    ModelMeta,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderDetailOut,
    ProviderOut,
    ProviderUpdate,
    RouteRef,
    TestResult,
)
from app.services import llm_gateway, route_service

router = APIRouter(prefix="/admin/models", tags=["admin-models"])


async def _admin_models(user: User = Depends(require_permission("admin:models"))) -> User:
    return user


# 增量 v1（§10-Q5）：fetch-models 按厂商预填思考档位（官方文档映射，管理员可改；
# 预填表随官方文档演进手工维护）。levels 为空 = 官方仅开关两态（R5 边界①）。
VENDOR_REASONING_PRESETS: dict[str, dict] = {
    "deepseek": {
        "enabled": True,
        "levels": [
            {"value": "high", "label": "高"},
            {"value": "max", "label": "超高"},
        ],
        "default_level": "high",
    },
    "kimi": {
        "enabled": True,
        "levels": [
            {"value": "high", "label": "高"},
            {"value": "max", "label": "超高"},
        ],
        "default_level": "high",
    },
    "openai": {
        "enabled": True,
        "levels": [
            {"value": "low", "label": "low"},
            {"value": "medium", "label": "medium"},
            {"value": "high", "label": "high"},
            {"value": "xhigh", "label": "xhigh"},
        ],
        "default_level": "medium",
    },
    "custom": {
        "enabled": True,
        "levels": [
            {"value": "low", "label": "low"},
            {"value": "medium", "label": "medium"},
            {"value": "high", "label": "high"},
        ],
        "default_level": "medium",
    },
    # mock：两态开关，便于本地双流链路演示
    "mock": {
        "enabled": True,
        "levels": [{"value": "on", "label": "开"}, {"value": "off", "label": "关"}],
        "default_level": "on",
    },
}


def merge_model_meta(old: dict | None, new: dict | None) -> dict:
    """meta 顶层键整体合并（以请求体为准，不回退历史键）→ ModelMeta 校验后整体写回。

    增量 v1（R4/R5）：reasoning 走 MetaReasoning 结构校验（default_level 必须在
    levels 内）；tools/custom_protocol 仅预留位。校验失败抛 400（结构非法不落库）。
    """
    merged = dict(old or {})
    if new:
        merged.update(new)
    try:
        return ModelMeta.model_validate(merged).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"meta 结构非法：{exc}") from exc


def mask_key(key: str) -> str:
    """API Key 脱敏（§9.1）；无 key 返回空串。"""
    return f"****{key[-4:]}" if key else ""


def _provider_out(p: Provider) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        vendor=p.vendor,
        base_url=p.base_url,
        enabled=p.enabled,
        is_default=p.is_default,
        has_key=bool(p.api_key),
        api_key_masked=mask_key(p.api_key),
    )


def _model_out(m: LLMModel) -> ModelOut:
    return ModelOut(
        id=m.id,
        name=m.name,
        is_default=m.is_default,
        custom=m.custom,
        enabled=m.enabled,
        meta=dict(m.meta or {}),
        sort=m.sort,
    )


async def _get_provider(db: AsyncSession, pid: int) -> Provider:
    provider = (
        await db.execute(select(Provider).where(Provider.id == pid))
    ).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return provider


def _check_vendor(vendor: str) -> None:
    if vendor not in VENDOR_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"vendor 须为 {'/'.join(VENDOR_WHITELIST)}",
        )


def _cfg_of(provider: Provider, model: str) -> llm_gateway.ClientCfg:
    return llm_gateway.ClientCfg(
        base_url=provider.base_url, api_key=provider.api_key, model=model, vendor=provider.vendor
    )


# ── Provider CRUD ───────────────────────────────────────
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)):
    providers = (
        await db.execute(select(Provider).order_by(Provider.id))
    ).scalars().all()
    return [_provider_out(p) for p in providers]


@router.post("/providers", response_model=ProviderDetailOut, status_code=201)
async def create_provider(
    body: ProviderCreate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    _check_vendor(body.vendor)
    provider = Provider(**body.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return ProviderDetailOut(**_provider_out(provider).model_dump(), models=[])


@router.get("/providers/{pid}", response_model=ProviderDetailOut)
async def get_provider(pid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)):
    provider = await _get_provider(db, pid)
    models = (
        await db.execute(
            select(LLMModel).where(LLMModel.provider_id == pid).order_by(LLMModel.sort, LLMModel.id)
        )
    ).scalars().all()
    return ProviderDetailOut(
        **_provider_out(provider).model_dump(), models=[_model_out(m) for m in models]
    )


@router.put("/providers/{pid}", response_model=ProviderOut)
async def update_provider(
    pid: int,
    body: ProviderUpdate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    provider = await _get_provider(db, pid)
    data = body.model_dump(exclude_unset=True)
    if body.vendor is not None:
        _check_vendor(body.vendor)
    if "api_key" in data and not data["api_key"]:
        del data["api_key"]  # 留空 = 不修改
    for key, value in data.items():
        setattr(provider, key, value)
    await db.commit()
    await db.refresh(provider)
    return _provider_out(provider)


@router.delete("/providers/{pid}")
async def delete_provider(
    pid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    provider = await _get_provider(db, pid)
    if provider.is_default:
        raise HTTPException(status_code=409, detail="默认路由正在引用该 Provider，请先切换默认路由")
    default_model = (
        await db.execute(
            select(LLMModel.id).where(
                LLMModel.provider_id == pid, LLMModel.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
    if default_model is not None:
        raise HTTPException(status_code=409, detail="默认路由正在引用其下模型，请先切换默认路由")
    await db.delete(provider)  # llm_models ON DELETE CASCADE
    await db.commit()
    return {"ok": True}


@router.post("/providers/{pid}/test", response_model=TestResult)
async def test_provider(
    pid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    provider = await _get_provider(db, pid)
    start = time.time()
    model_row = (
        await db.execute(
            select(LLMModel)
            .where(LLMModel.provider_id == pid, LLMModel.enabled.is_(True))
            .order_by(LLMModel.sort, LLMModel.id)
            .limit(1)
        )
    ).scalars().first()
    model_name = model_row.name if model_row else ""
    cfg = _cfg_of(provider, model_name or "mock")
    if cfg.is_mock:
        return TestResult(ok=True, latency_ms=0, model=model_name)
    try:
        reply = await llm_gateway.chat_once(
            cfg, [{"role": "user", "content": "ping，回复 pong 即可"}], timeout=20.0
        )
        return TestResult(
            ok=bool(reply), latency_ms=int((time.time() - start) * 1000), model=model_name
        )
    except llm_gateway.UpstreamError as exc:
        return TestResult(
            ok=False, latency_ms=int((time.time() - start) * 1000), model=model_name, error=str(exc)
        )


@router.post("/providers/{pid}/fetch-models", response_model=list[FetchedModel])
async def fetch_models(
    pid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    """官方 GET {base_url}/models 拉取可用模型，平铺入库（已存在的保留 custom/enabled/meta）。"""
    provider = await _get_provider(db, pid)
    cfg = _cfg_of(provider, "mock" if not provider.api_key else "")
    try:
        names = await llm_gateway.fetch_model_names(cfg)
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"拉取模型列表失败：{exc}") from exc

    existing = {
        m.name: m
        for m in (
            await db.execute(select(LLMModel).where(LLMModel.provider_id == pid))
        ).scalars().all()
    }
    # Q5：新入库模型按厂商预填思考档位（已存在的行保留原 meta 不回填）
    vendor = (provider.vendor or "").lower()
    preset_reasoning = VENDOR_REASONING_PRESETS.get(vendor)
    result: list[FetchedModel] = []
    for sort, name in enumerate(names, start=1):
        row = existing.get(name)
        if row is None:
            meta = dict(DEFAULT_MODEL_META)
            if preset_reasoning is not None:
                meta["reasoning"] = dict(preset_reasoning)
            row = LLMModel(
                provider_id=pid,
                name=name,
                custom=False,
                enabled=True,
                meta=meta,
                sort=sort,
            )
            db.add(row)
            await db.flush()
        result.append(FetchedModel(name=name, meta=dict(row.meta or {})))
    await db.commit()
    return result


@router.post("/providers/{pid}/models", response_model=ModelOut, status_code=201)
async def create_custom_model(
    pid: int,
    body: ModelCreate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    """手动添加自定义模型（custom=true 可删除；同 Provider 重名 409）。"""
    await _get_provider(db, pid)
    exists = (
        await db.execute(
            select(LLMModel.id).where(
                LLMModel.provider_id == pid, LLMModel.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="该 Provider 下已存在同名模型")
    max_sort = (
        await db.execute(
            select(LLMModel.sort).where(LLMModel.provider_id == pid).order_by(LLMModel.sort.desc())
        )
    ).scalars().first()
    model = LLMModel(
        provider_id=pid,
        name=body.name,
        custom=True,
        enabled=True,
        meta=merge_model_meta(None, body.meta or dict(DEFAULT_MODEL_META)),
        sort=(max_sort or 0) + 1,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.put("/providers/{pid}/models/{mid}", response_model=ModelOut)
async def update_model(
    pid: int,
    mid: int,
    body: ModelUpdate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    """模型级修正：meta 能力元数据（Q16 + R4/R5）与启用开关（管理页编辑用）。

    meta 顶层键整体合并后按 ModelMeta 校验（reasoning 档位结构非法 400）。
    """
    model = (
        await db.execute(
            select(LLMModel).where(LLMModel.id == mid, LLMModel.provider_id == pid)
        )
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    data = body.model_dump(exclude_unset=True)
    if data.get("meta") is not None:
        model.meta = merge_model_meta(model.meta, data["meta"])
    if data.get("enabled") is not None:
        model.enabled = data["enabled"]
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.delete("/providers/{pid}/models/{mid}")
async def delete_model(
    pid: int, mid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    """仅自定义模型可删除；官方拉取模型以重新拉取为准（§3.2 注）。"""
    model = (
        await db.execute(
            select(LLMModel).where(LLMModel.id == mid, LLMModel.provider_id == pid)
        )
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if not model.custom:
        raise HTTPException(status_code=400, detail="官方拉取模型不可删除，可重新拉取或停用")
    if model.is_default:
        raise HTTPException(status_code=409, detail="默认路由正在引用该模型，请先切换默认路由")
    await db.delete(model)
    await db.commit()
    return {"ok": True}


# ── 默认路由（Q10/Q13）──────────────────────────────────
@router.get("/default-route", response_model=DefaultRouteOut)
async def get_default_route(
    admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    route = await route_service.resolve_default(db)
    if route is None:
        return DefaultRouteOut(provider=None, model=None)
    return DefaultRouteOut(
        provider=RouteRef(id=route.provider_id, name=route.provider_name),
        model=RouteRef(id=route.model_id, name=route.model_name),
    )


@router.put("/default-route", response_model=DefaultRouteOut)
async def set_default_route(
    body: DefaultRouteSet,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    provider = await _get_provider(db, body.provider_id)
    model = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.id == body.model_id, LLMModel.provider_id == provider.id
            )
        )
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=400, detail="模型不属于该 Provider")
    # 部分唯一索引兜底：同事务先清旧标记再设新标记
    await db.execute(update(Provider).values(is_default=False))
    await db.execute(update(LLMModel).values(is_default=False))
    provider.is_default = True
    model.is_default = True
    await db.commit()
    return DefaultRouteOut(
        provider=RouteRef(id=provider.id, name=provider.name),
        model=RouteRef(id=model.id, name=model.name),
    )


# ── 网关令牌（Q17）──────────────────────────────────────
def _token_out(t: GatewayToken) -> GatewayTokenOut:
    return GatewayTokenOut(
        id=t.id,
        name=t.name,
        token_mask=t.token_mask,
        model_scope=t.model_scope,
        active=t.active,
        created_at=t.created_at,
    )


@router.get("/gateway-tokens", response_model=list[GatewayTokenOut])
async def list_gateway_tokens(
    admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    tokens = (
        await db.execute(select(GatewayToken).order_by(GatewayToken.id))
    ).scalars().all()
    return [_token_out(t) for t in tokens]


@router.post("/gateway-tokens", response_model=GatewayTokenCreated, status_code=201)
async def create_gateway_token(
    body: GatewayTokenCreate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    token = "sk-" + secrets.token_urlsafe(24)
    row = GatewayToken(
        name=body.name,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_mask=f"sk-••••{token[-4:]}",
        model_scope=body.model_scope,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return GatewayTokenCreated(token=token, item=_token_out(row))


@router.delete("/gateway-tokens/{tid}")
async def revoke_gateway_token(
    tid: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    row = (
        await db.execute(select(GatewayToken).where(GatewayToken.id == tid))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="令牌不存在")
    row.active = False  # 吊销立即生效
    await db.commit()
    return {"ok": True}
