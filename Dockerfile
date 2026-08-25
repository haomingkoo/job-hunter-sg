# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --legacy-peer-deps; else npm install --legacy-peer-deps; fi
COPY frontend/ .
COPY shared/ ../shared/
RUN npm run build

# Stage 2: Python backend + serve frontend static files
FROM python:3.12-slim

# System deps for weasyprint (PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 fonts-liberation && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
# Torch pins an old setuptools release, but the application does not need the
# packaging tool at runtime. Remove that vulnerable build-only surface.
RUN python -m pip uninstall -y setuptools

RUN useradd --create-home --uid 10001 --user-group appuser && chown appuser:appuser /app
ENV HOME=/home/appuser
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    chown -R appuser:appuser /home/appuser
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY --chown=appuser:appuser backend/ .
COPY --chown=appuser:appuser shared/ ../shared/

# Copy built frontend into /app/static
COPY --from=frontend-build --chown=appuser:appuser /app/frontend/dist ./static

EXPOSE 8000

USER appuser

CMD ["python", "main.py"]
