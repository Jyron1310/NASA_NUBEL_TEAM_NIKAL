# Nikal Cusco: API (FastAPI) + interfaz (React + MapLibre) + datos armonizados de Cusco.
# Basado en plataforma_local/Dockerfile.modelo de Antonio (rama antonio/backend-modelo):
# contexto = RAÍZ del repositorio, datos dentro de la imagen, sin pipeline sintético.
# Agregado: etapa Node que compila la interfaz y validación de los datos contra METHODOLOGY.md §14.
#
# Construir desde la raíz del repositorio:
#   docker build -f plataforma_local/Dockerfile -t firecal-cusco .
#   docker run --rm -p 8000:8000 firecal-cusco          # luego abrir http://localhost:8000
# o, desde plataforma_local/:  docker compose up --build
#
# PLAT_DIR: carpeta de la plataforma dentro del contexto (plataforma_local en el repositorio;
# "." en una copia local que ya tiene backend/, frontend/, data/ y harmonizacion/ en su raíz).
ARG PLAT_DIR=plataforma_local

# ---- 1) Interfaz: npm ci + vite build -> /web/dist
FROM node:22-slim AS web
ARG PLAT_DIR
WORKDIR /web
COPY ${PLAT_DIR}/frontend/package.json ${PLAT_DIR}/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ${PLAT_DIR}/frontend/ ./
RUN npm run build

# ---- 2) API + datos
FROM python:3.12-slim
ARG PLAT_DIR
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 FIRECAL_DATA_MODE=real \
    FIRECAL_SOURCE_ROOT=/app FIRECAL_FRONTEND_DIR=/app/frontend
WORKDIR /app/backend

COPY ${PLAT_DIR}/backend/requirements-lock.txt ./
RUN pip install -r requirements-lock.txt

COPY ${PLAT_DIR}/backend/ ./
RUN pip install -e . --no-deps
COPY --from=web /web/dist/ /app/frontend/

# Datos de Cusco (METHODOLOGY.md): mismos caminos relativos que en el repositorio.
COPY data/harmonized/ /app/data/harmonized/
COPY harmonizacion/cusco_ref/ /app/harmonizacion/cusco_ref/
# Valida filas, sumas y SHA-256 contra METHODOLOGY.md §14 y arma el Parquet. Si los datos cambiaron,
# la construcción falla y no se publica nada.
RUN firecal plan-events

RUN useradd --create-home --uid 10001 firecal && chown -R firecal /app/backend/data
USER firecal

EXPOSE 8000
# PORT lo fijan Cloud Run / Azure Container Apps / Render; 8000 por defecto.
# En la nube: FIRECAL_TRUST_PROXY=1 (límite por IP real) y, si la interfaz se publica en otro
# dominio, FIRECAL_CORS_ORIGINS=https://<dominio>.
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
