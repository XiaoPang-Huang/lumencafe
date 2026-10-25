"""平台管理-模型管理（PRD §4.3，权限点 admin:models）。

- Provider 条目 = 厂商×套餐平级（架构定稿修订3）；api_key 脱敏回显（§9.1）；
- 默认路由 = providers.is_default + llm_models.is_default 两标记（Q10/Q13），
  部分唯一索引兜底全库至多一个，切换时同事务先清旧标记；
- fetch-models 调官方 GET {base_url}/models 平铺入库（custom/enabled 保留）；
- 网关令牌（Q17）：仅存 sha256 哈希 + 掩码，完整令牌仅创建时返回一次；
- 步 3（D4 管理面约束）：模型指派 / 熔断状态 / 用量统计全部挂本路由
  （现有 admin:models 权限，零新增鉴权面），统计仅管理员可见。
"""
import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.llm import (
    GatewayToken,
    LLMCallLog,
    LLMModel,
    ModelAssignment,
    ModelCircuitState,
    Provider,
)
from app.models.user import User
from app.schemas.llm import (
    DEFAULT_MODEL_META,
    VENDOR_WHITELIST,
    AppUsageStat,
    AssignmentListOut,
    CircuitStateOut,
    DefaultRouteOut,
    DefaultRouteSet,
    FallbackRef,
    FetchedModel,
    GatewayTokenCreate,
    GatewayTokenCreated,
    GatewayTokenOut,
    ModelAssignmentOut,
    ModelAssignmentSet,
    ModelCreate,
    ModelMeta,
    ModelOut,
    ModelPoolItem,
    ModelUpdate,
    ModelUsageStat,
    ProviderCreate,
    ProviderDetailOut,
    ProviderOut,
    ProviderUpdate,
    RouteRef,
    TestResult,
    UsageLogOut,
    UsageLogPage,
    UsageSummaryOut,
)
from app.services import circuit_service, llm_gateway, route_service

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


# ── 模型指派（步 3 D2：app_key → 主模型 + 有序备用链）──────────
def _assignment_out(
    assignment: ModelAssignment, names: dict[int, str]
) -> ModelAssignmentOut:
    return ModelAssignmentOut(
        app_key=assignment.app_key,
        primary_model_id=assignment.primary_model_id,
        primary_model_name=names.get(assignment.primary_model_id, "（已删除）"),
        fallback_chain=[
            FallbackRef(id=mid, name=names.get(mid, "（已删除）"))
            for mid in (assignment.fallback_chain or [])
        ],
        enabled=assignment.enabled,
    )


async def _model_names(db: AsyncSession) -> dict[int, str]:
    rows = (
        await db.execute(select(LLMModel.id, LLMModel.name).order_by(LLMModel.id))
    ).all()
    return {int(mid): name for mid, name in rows}


@router.get("/assignments", response_model=AssignmentListOut)
async def list_assignments(
    admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    """指派列表 + 模型池（指派编辑下拉用：启用模型，id + 展示名）。"""
    assignments = (
        await db.execute(select(ModelAssignment).order_by(ModelAssignment.app_key))
    ).scalars().all()
    names = await _model_names(db)
    pool_rows = (
        await db.execute(
            select(LLMModel, Provider)
            .join(Provider, Provider.id == LLMModel.provider_id)
            .where(LLMModel.enabled.is_(True), Provider.enabled.is_(True))
            .order_by(Provider.id, LLMModel.sort, LLMModel.id)
        )
    ).all()
    return AssignmentListOut(
        assignments=[_assignment_out(a, names) for a in assignments],
        model_pool=[
            ModelPoolItem(id=m.id, name=m.name, provider_name=p.name)
            for m, p in pool_rows
        ],
    )


@router.put("/assignments/{app_key}", response_model=ModelAssignmentOut)
async def set_assignment(
    app_key: str,
    body: ModelAssignmentSet,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    """写入指派（upsert）：校验主模型与备用链模型均存在且启用；链内去重、排除主模型。"""
    wanted = [body.primary_model_id, *body.fallback_chain]
    if len(set(wanted)) != len(wanted):
        raise HTTPException(status_code=400, detail="备用链与主模型重复")
    rows = (
        await db.execute(select(LLMModel).where(LLMModel.id.in_(wanted)))
    ).scalars().all()
    found = {m.id: m for m in rows}
    missing = [m for m in wanted if m not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"模型不存在：{missing}")
    disabled = [m.id for m in found.values() if not m.enabled]
    if disabled:
        raise HTTPException(status_code=400, detail=f"模型已停用：{disabled}")

    assignment = (
        await db.execute(select(ModelAssignment).where(ModelAssignment.app_key == app_key))
    ).scalar_one_or_none()
    if assignment is None:
        assignment = ModelAssignment(app_key=app_key)
        db.add(assignment)
    assignment.primary_model_id = body.primary_model_id
    assignment.fallback_chain = list(body.fallback_chain or [])
    assignment.enabled = body.enabled
    await db.commit()
    await db.refresh(assignment)
    return _assignment_out(assignment, await _model_names(db))


# ── 熔断状态（步 3 Q2，Portkey 语义，存库）───────────────────
@router.get("/circuit-states", response_model=list[CircuitStateOut])
async def list_circuit_states(
    admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(ModelCircuitState, LLMModel)
            .outerjoin(LLMModel, LLMModel.id == ModelCircuitState.model_id)
            .order_by(ModelCircuitState.model_id)
        )
    ).all()
    return [
        CircuitStateOut(
            model_id=s.model_id,
            model_name=m.name if m else "（已删除）",
            state=s.state,
            consecutive_failures=s.consecutive_failures,
            opened_at=s.opened_at,
            next_probe_at=s.next_probe_at,
            updated_at=s.updated_at,
        )
        for s, m in rows
    ]


@router.post("/circuit-states/{model_id}/reset")
async def reset_circuit_state(
    model_id: int,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    """手动恢复熔断（管理面运维操作）：清状态，路由立即重新采纳该模型。"""
    await circuit_service.reset(db, model_id)
    return {"ok": True}


# ── 用量统计（步 3 D3，布局抄 one-api：卡片 + 表格；Q3 无限期保留 + 时间筛选）──
def _usage_window(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """时间窗 [start, end)，默认近 7 天（PG 聚合口径，Q6：卡片 + 表格即够）。"""
    end_at = end or datetime.now(UTC)
    start_at = start or (end_at - timedelta(days=7))
    if start_at >= end_at:
        raise HTTPException(status_code=400, detail="start 须早于 end")
    return start_at, end_at


@router.get("/usage/summary", response_model=UsageSummaryOut)
async def usage_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    start_at, end_at = _usage_window(start, end)
    cond = [LLMCallLog.created_at >= start_at, LLMCallLog.created_at < end_at]

    total_row = (
        await db.execute(
            select(
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.cost), 0),
                func.coalesce(func.avg(LLMCallLog.latency_ms), 0),
            ).where(*cond)
        )
    ).one()
    success_calls = int(
        (
            await db.execute(
                select(func.count(LLMCallLog.id)).where(*cond, LLMCallLog.success.is_(True))
            )
        ).scalar_one()
    )
    total_calls = int(total_row[0])
    input_tokens = int(total_row[1])
    output_tokens = int(total_row[2])
    total_cost = float(total_row[3])

    by_model_rows = (
        await db.execute(
            select(
                LLMCallLog.model_id,
                LLMCallLog.model_name,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.cost), 0),
            )
            .where(*cond)
            .group_by(LLMCallLog.model_id, LLMCallLog.model_name)
            .order_by(func.coalesce(func.sum(LLMCallLog.cost), 0).desc())
        )
    ).all()
    success_by_model = {
        row[0]: int(row[1])
        for row in (
            await db.execute(
                select(LLMCallLog.model_id, func.count(LLMCallLog.id))
                .where(*cond, LLMCallLog.success.is_(True))
                .group_by(LLMCallLog.model_id)
            )
        ).all()
    }
    by_app_rows = (
        await db.execute(
            select(
                LLMCallLog.app_key,
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.cost), 0),
            )
            .where(*cond)
            .group_by(LLMCallLog.app_key)
            .order_by(func.count(LLMCallLog.id).desc())
        )
    ).all()
    success_by_app = {
        row[0]: int(row[1])
        for row in (
            await db.execute(
                select(LLMCallLog.app_key, func.count(LLMCallLog.id))
                .where(*cond, LLMCallLog.success.is_(True))
                .group_by(LLMCallLog.app_key)
            )
        ).all()
    }
    return UsageSummaryOut(
        total_calls=total_calls,
        success_calls=success_calls,
        failed_calls=total_calls - success_calls,
        success_rate=round(success_calls / total_calls, 4) if total_calls else 0.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        avg_latency_ms=round(float(total_row[4]), 1),
        by_model=[
            ModelUsageStat(
                model_id=row[0],
                model_name=row[1],
                calls=int(row[2]),
                success_calls=success_by_model.get(row[0], 0),
                input_tokens=int(row[3]),
                output_tokens=int(row[4]),
                cost=float(row[5]),
            )
            for row in by_model_rows
        ],
        by_app=[
            AppUsageStat(
                app_key=row[0],
                calls=int(row[1]),
                success_calls=success_by_app.get(row[0], 0),
                input_tokens=int(row[2]),
                output_tokens=int(row[3]),
                cost=float(row[4]),
            )
            for row in by_app_rows
        ],
    )


@router.get("/usage/logs", response_model=UsageLogPage)
async def usage_logs(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    app_key: str | None = Query(default=None, max_length=64),
    model_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    """调用日志明细分页（one-api 日志式；时间筛选 + app_key/模型过滤，Q3 无限期保留）。"""
    start_at, end_at = _usage_window(start, end)
    cond = [LLMCallLog.created_at >= start_at, LLMCallLog.created_at < end_at]
    if app_key:
        cond.append(LLMCallLog.app_key == app_key)
    if model_id is not None:
        cond.append(LLMCallLog.model_id == model_id)

    total = int(
        (await db.execute(select(func.count(LLMCallLog.id)).where(*cond))).scalar_one()
    )
    rows = (
        await db.execute(
            select(LLMCallLog)
            .where(*cond)
            .order_by(LLMCallLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return UsageLogPage(
        items=[
            UsageLogOut(
                id=r.id,
                app_key=r.app_key,
                model_id=r.model_id,
                model_name=r.model_name,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                latency_ms=r.latency_ms,
                success=r.success,
                error=r.error,
                cost=float(r.cost) if r.cost is not None else None,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
