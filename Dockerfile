# ── Stage 1: Build the React frontend ────────────────────────────────────────
FROM node:20-bullseye-slim AS frontend-builder

WORKDIR /frontend

COPY strain/frontend/package*.json ./
RUN npm ci --prefer-offline

COPY strain/frontend/ ./
RUN npm run build

# ── Stage 2: Python deps (heavy ML) ──────────────────────────────────────────
FROM python:3.11-bullseye AS backend

WORKDIR /app

# System build deps + BLAS for scikit-learn / hdbscan
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ gfortran \
    libopenblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade tooling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

# Install in dependency order to maximise layer caching
RUN pip install --no-cache-dir numpy>=1.26.0
RUN pip install --no-cache-dir scipy>=1.13.0 scikit-learn>=1.4.0
RUN pip install --no-cache-dir hdbscan>=0.8.33
RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn[standard]>=0.29.0 \
    sqlmodel>=0.0.18 \
    sentence-transformers>=2.7.0 \
    python-docx>=1.1.0 \
    pdfplumber>=0.11.0 \
    python-levenshtein>=0.25.0 \
    python-multipart>=0.0.9 \
    aiofiles>=23.2.1

# Copy application source
COPY strain/ ./strain/

# Copy data (SQLite DB + embedding cache + seed files)
COPY data/ ./data/

# Copy built frontend from stage 1 → served as static files by FastAPI
COPY --from=frontend-builder /frontend/dist ./strain/frontend/dist

# No pip install needed — strain is found directly via PYTHONPATH
ENV PYTHONPATH=/app
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Pre-download the sentence-transformers model (baked into image, zero cold-start)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2'); print('Model pre-baked OK')"

EXPOSE 8080

CMD ["uvicorn", "strain.backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
