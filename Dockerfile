# Middleware PrestaShop — imagen por cliente
#
# Build:  docker build -t dc-middleware:latest .
#
# Cada cliente corre un contenedor de esta imagen con su propio catalogo.db
# (montado en /data) y sus propias credenciales PrestaShop (vía env_file).
FROM python:3.12-slim

# Chromium + chromedriver para Selenium headless, y fuentes para renderizado
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/models/hf \
    SENTENCE_TRANSFORMERS_HOME=/app/models/st

WORKDIR /app

# Dependencias Python (torch/sentence-transformers son las pesadas)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cargar el modelo de embeddings (~90MB) para que el arranque no descargue
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY middleware/ ./middleware/
COPY admin_ui/ ./admin_ui/
COPY scripts/ ./scripts/
COPY *.py ./
COPY *.json ./
COPY "003 DESCRIPCIONES.xlsx" ./
COPY migrations/ ./migrations/

EXPOSE 5000

# Datos persistentes del cliente: catalogo.db + caches de scrape
VOLUME /data
ENV DB_PATH=/data/catalogo.db

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
