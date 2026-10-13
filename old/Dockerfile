FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非 root 运行，降低容器内提权风险
RUN useradd --system --uid 10001 --home-dir /srv appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
