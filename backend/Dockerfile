# 多阶段构建：builder 装依赖，runtime 只留运行时文件，非 root 运行
FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS builder

WORKDIR /srv
COPY requirements.txt .
# PIP_INDEX_URL 由 compose 构建参数注入（国内走镜像加速），默认官方 PyPI
ARG PIP_INDEX_URL=https://pypi.org/simple
# --require-hashes：lockfile 纪律（D6），逐包校验 requirements.txt 里的 sha256
RUN pip install --no-cache-dir --prefix=/install --index-url=${PIP_INDEX_URL} --require-hashes -r requirements.txt


FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

# 从 builder 拷贝已安装的依赖（含 uvicorn standard 的编译产物）
COPY --from=builder /install /usr/local

# 非 root 运行，降低容器内提权风险（沿用旧版形态）
RUN useradd --system --uid 10001 --home-dir /srv appuser

# 应用代码 + Alembic（启动命令为 alembic upgrade head && uvicorn ...）
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser app ./app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
