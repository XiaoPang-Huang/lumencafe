"""种子逻辑（T02）：权限点、预置角色与绑定、引导管理员、应用注册表、记账内置分类。

全部幂等（按自然键 upsert），可随服务启动反复执行。
- 权限点清单：架构设计 §6.1（admin 全量，member 仅 app:*）；
- 引导管理员：仅 users 表为空时生效（配置项 LUMEN_ADMIN_USERNAME/PASSWORD）；
- 记账内置分类与原型 data.js 对齐（餐饮/交通/购物/居住/工资）。
"""
import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.apps import AppRegistry
from app.models.llm import GatewayToken, LLMModel, Provider
from app.models.money import MoneyCategory
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.security import hash_password

# (code, 名称, 描述, 批次说明) —— 与架构设计 §6.1 对齐
PERMISSIONS: list[tuple[str, str, str]] = [
    ("app:chat", "使用 AI 对话", "通用对话应用"),
    ("app:money", "记账", "记账应用（v1.1 新增）"),
    ("app:papers", "文献", "文献应用（批次 2 有接口，先 seed 权限点）"),
    ("admin:users", "用户/角色管理", "平台管理-成员"),
    ("admin:models", "模型管理", "平台管理-模型与网关"),
]

# 预置角色：admin 全量权限点；member 全部 app:*
ROLES: dict[str, dict] = {
    "admin": {"description": "管理员，拥有全部权限点", "perms": "all"},
    "member": {"description": "普通成员，可使用各应用", "perms": "app:*"},
}

# 应用注册表（批次 1：chat + money；papers 批次 2 注册）
APPS: list[dict] = [
    {
        "id": "chat",
        "name": "AI 对话",
        "desc": "通用 AI 对话，对标 DeepSeek 界面",
        "color": "#f0f6ff",
        "icon": "chat",
        "sort": 1,
        "mode": "chat",
        "perm_code": "app:chat",
    },
    {
        "id": "money",
        "name": "记账本",
        "desc": "记一笔，AI 帮你整理",
        "color": "#f0f6ff",
        "icon": "money",
        "sort": 2,
        "mode": "backend",
        "perm_code": "app:money",
    },
]

# 记账内置分类（built_in=true：可改名、可隐藏、不可删除；与原型 data.js 对齐）
MONEY_BUILT_IN_CATEGORIES: list[tuple[str, str]] = [
    ("餐饮", "expense"),
    ("交通", "expense"),
    ("购物", "expense"),
    ("居住", "expense"),
    ("工资", "income"),
]

# 厂家模板：env 种子时给默认 base_url / 模型名（Q12）
LLM_VENDOR_TEMPLATES: dict[str, dict] = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "mock": {"base_url": "", "model": "mock"},
}

DEFAULT_MODEL_META = {"context": "", "vision": False, "files": False}


async def _seed_permissions(db: AsyncSession) -> None:
    for code, name, desc in PERMISSIONS:
        exists = (
            await db.execute(select(Permission.id).where(Permission.code == code))
        ).scalar_one_or_none()
        if exists is None:
            db.add(Permission(code=code, name=name, description=desc))


async def _seed_roles(db: AsyncSession) -> None:
    perms = (await db.execute(select(Permission))).scalars().all()
    by_code = {p.code: p for p in perms}
    existing = {
        r.name: r for r in (await db.execute(select(Role))).scalars().all()
    }
    for name, spec in ROLES.items():
        role = existing.get(name)
        if role is None:
            role = Role(name=name, description=spec["description"], built_in=True)
            db.add(role)
            await db.flush()
        wanted = (
            set(by_code)
            if spec["perms"] == "all"
            else {c for c in by_code if c.startswith("app:")}
        )
        have = set(
            (
                await db.execute(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                )
            ).scalars().all()
        )
        for code in wanted - have:
            db.add(RolePermission(role_id=role.id, permission_id=by_code[code].id))


async def _seed_admin(db: AsyncSession) -> None:
    """仅 users 表为空时引导管理员（LUMEN_ADMIN_USERNAME/PASSWORD）。"""
    user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if user_count > 0:
        return
    admin = User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        nickname="管理员",
    )
    db.add(admin)
    await db.flush()
    role = (
        await db.execute(select(Role).where(Role.name == "admin"))
    ).scalar_one()
    db.add(UserRole(user_id=admin.id, role_id=role.id))


async def seed_money_categories(db: AsyncSession, user_id: int) -> None:
    """给指定用户补记账内置分类（注册新用户时调用；已存在则跳过）。"""
    existing = set(
        (await db.execute(select(MoneyCategory.name).where(MoneyCategory.user_id == user_id)))
        .scalars()
        .all()
    )
    for sort, (name, kind) in enumerate(MONEY_BUILT_IN_CATEGORIES, start=1):
        if name not in existing:
            db.add(
                MoneyCategory(
                    user_id=user_id, built_in=True, sort=sort, name=name, kind=kind
                )
            )


async def _seed_apps(db: AsyncSession) -> None:
    for app in APPS:
        exists = (
            await db.execute(
                select(AppRegistry.id).where(AppRegistry.id == app["id"])
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(AppRegistry(built_in=True, **app))


async def _seed_llm(db: AsyncSession) -> None:
    """初始 LLM 渠道种子（Q12）：仅 providers 为空时；mock 避免生产误配。

    - LUMEN_LLM_PROVIDER=deepseek/kimi 且 Key 非空 → 种子对应渠道；
    - LUMEN_LLM_PROVIDER=mock → 种子 mock（本地开发占位，不联网）；
    - 未配置 provider 且未配任何 Key → mock 兜底（本地开箱可用）。
    种子的渠道同时打默认路由两标记（is_default），默认路由开箱可用。
    """
    count = (
        await db.execute(select(func.count(Provider.id)))
    ).scalar_one()
    if count > 0:
        return
    provider_key = (settings.llm_provider or "").strip().lower()
    api_key = ""
    if provider_key == "deepseek":
        api_key = settings.deepseek_key
    elif provider_key == "kimi":
        api_key = settings.kimi_key
    elif provider_key == "mock":
        pass
    elif not provider_key and not (settings.deepseek_key or settings.kimi_key):
        provider_key = "mock"  # Q12：本地兜底
    else:
        return
    if provider_key in ("deepseek", "kimi") and not api_key:
        return
    template = LLM_VENDOR_TEMPLATES[provider_key]
    provider = Provider(
        name=f"{provider_key}（种子）",
        vendor=provider_key,
        base_url=template["base_url"],
        api_key=api_key,
        enabled=True,
        is_default=True,
    )
    db.add(provider)
    await db.flush()
    db.add(
        LLMModel(
            provider_id=provider.id,
            name=template["model"],
            is_default=True,
            custom=False,
            enabled=True,
            meta=dict(DEFAULT_MODEL_META),
            sort=1,
        )
    )


async def _seed_gateway_tokens(db: AsyncSession) -> None:
    """首个网关令牌由 LUMEN_INTERNAL_TOKEN 种子（Q17）；之后全部界面管理。"""
    if not settings.internal_token:
        return
    count = (
        await db.execute(select(func.count(GatewayToken.id)))
    ).scalar_one()
    if count > 0:
        return
    token = settings.internal_token
    db.add(
        GatewayToken(
            name="env 种子（LUMEN_INTERNAL_TOKEN）",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            token_mask=f"sk-••••{token[-4:]}",
            model_scope=None,
        )
    )


async def run_seed(db: AsyncSession) -> None:
    """启动种子入口：幂等，单事务提交。"""
    await _seed_permissions(db)
    await db.flush()
    await _seed_roles(db)
    await _seed_admin(db)
    await _seed_apps(db)
    admin = (
        await db.execute(select(User).where(User.username == settings.admin_username))
    ).scalar_one_or_none()
    if admin is not None:
        await seed_money_categories(db, admin.id)
    await _seed_llm(db)
    await _seed_gateway_tokens(db)
    await db.commit()
