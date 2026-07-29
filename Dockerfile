# Imagen del server para una INSTANCIA OPERADA (un integrador que corre aiuda
# para sus clientes en un VPS, con Postgres vía DATABASE_URL). La instalación
# local normal NO usa Docker: es `uvx aiuda`.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY core/pyproject.toml core/
COPY server/pyproject.toml server/

COPY core/ core/
COPY server/ server/

RUN uv pip install --system ./core "./server[postgres]"

EXPOSE 8000
CMD ["uvicorn", "aiuda_server.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
