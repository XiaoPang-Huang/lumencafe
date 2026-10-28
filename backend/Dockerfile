# 多阶段构建：builder 装依赖，runtime 只留运行时文件，非 root 运行
FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS builder

WORKDIR /srv
COPY requirements.txt .
# PIP_INDEX_URL 由 compose 构建参数注入（国内走镜像加速），默认官方 PyPI
ARG PIP_INDEX_URL=https://pypi.org/simple
# --require-hashes：lockfile 纪律（D6），逐包校验 requirements.txt 里的 sha256
# 注意：改 requirements.txt 后若服务器构建缓存未失效（镜像里仍缺新包），
# 给本注释加一行版本号强制 bust 该层缓存（2026-10-28 踩中：cache-bust=1）
RUN pip install --no-cache-dir --prefix=/install --index-url=${PIP_INDEX_URL} --require-hashes -r requirements.txt


FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

# 从 builder 拷贝已安装的依赖（含 uvicorn standard 的编译产物）
COPY --from=builder /install /usr/local

# 步 2 镜像清包（拍板回执 v2.3，评估见 docs/依赖锁定清单-v1.md §5.2）：
# trivy 实测基础镜像自带 4 条可修 HIGH 全部位于 pip 26.2.2 的 vendored 私有副本
#（pip/_vendor/msgpack 1.1.2、urllib3 2.7.0、pkg_resources（setuptools 70.3.0）），
# pip uninstall 不可达；三者均非项目依赖（lockfile 不引用，运行时零 import）。
# runtime 阶段无需 pip → 整体移除，4 条可修 HIGH 随 pip 一并清除；builder 阶段保留。
# 回退：删除本 RUN 块重建镜像。
RUN rm -rf /usr/local/lib/python3.14/site-packages/pip \
           /usr/local/lib/python3.14/site-packages/pip-26.2.2.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14

# 非 root 运行，降低容器内提权风险（沿用旧版形态）
RUN useradd --system --uid 10001 --home-dir /srv appuser

# 应用代码 + Alembic（启动命令为 alembic upgrade head && uvicorn ...）
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser app ./app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
