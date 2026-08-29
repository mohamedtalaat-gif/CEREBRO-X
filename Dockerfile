# ════════════════════════════════════════════════════════════════════════════
#  CEREBRO-X  —  Dockerfile (Stable Latest)
# ════════════════════════════════════════════════════════════════════════════
#  Created by   : Muhammad Talaat (BPharm, R&D Computational Lead)
#  Last updated : 2026-05-09
#
#  Strategy: Use latest compatible versions for all libraries to get
#  performance improvements and bug fixes, while pinning minimum versions
#  to prevent breaking changes. Build-time smoke tests guarantee core
#  functionality (resolver, video, fonts) works.
# ════════════════════════════════════════════════════════════════════════════

FROM python:3.13-slim AS base

LABEL org.opencontainers.image.title="CEREBRO-X"
LABEL org.opencontainers.image.description="Computational pharmaceutical pipeline for CNS drug delivery system optimization"
LABEL org.opencontainers.image.authors="Muhammad Talaat <mohamed.talaat@pharma.asu.edu.eg>"
LABEL org.opencontainers.image.source="https://github.com/cerebro-x/cerebro-x"
LABEL org.opencontainers.image.licenses="Proprietary"
LABEL org.cerebro.version="22.1"

ARG PYTHON_ENV=production

# ── Layer 1: System dependencies + brand typography ────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ gfortran \
        libffi-dev libssl-dev \
        libopenblas-dev liblapack-dev \
        libhdf5-dev \
        curl wget git \
        ca-certificates \
        fonts-inter fonts-liberation fontconfig \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# ── Layer 2: Scientific foundation (latest stable where safe) ──────────────
RUN pip install --no-cache-dir \
        "numpy>=2.0,<3.0" \
        "pandas>=2.3" \
        "scipy>=1.17" \
        "scikit-learn>=1.8" \
        "matplotlib>=3.10" \
        "seaborn>=0.13.2" \
        "xgboost>=2.1" \
        "shap>=0.46"

# ── Layer 3: Cheminformatics & Bioinformatics (pinned for compatibility) ────
RUN pip install --no-cache-dir rdkit==2024.9.4               || echo "[BUILD-WARN] rdkit"
RUN pip install --no-cache-dir biopython==1.84                || echo "[BUILD-WARN] biopython"
RUN pip install --no-cache-dir chembl-webresource-client      || echo "[BUILD-WARN] chembl-webresource-client"
RUN pip install --no-cache-dir pubchempy==1.0.4               || echo "[BUILD-WARN] pubchempy"
RUN pip install --no-cache-dir MDAnalysis==2.7.0              || echo "[BUILD-WARN] MDAnalysis"

# ── Layer 4: Phase 5 first-principles libraries (latest, conflict-free) ─────
#    - thermo and chemicals are tightly coupled; let pip resolve latest compatible
#    - others: latest with minimum version constraints to avoid regressions
RUN pip install --no-cache-dir \
        "mendeleev>=1.1" \
        "thermo>=0.4" \
        "chemicals>=1.3.3" \
        "pint>=0.24" \
        "periodictable>=1.7" \
        "molmass>=2024.10" \
        "qcelemental>=0.28"

# ── Layer 5: Visualization, output, web ─────────────────────────────────────
RUN pip install --no-cache-dir \
        "plotly>=5.24" \
        "bokeh>=3.6" \
        "imageio>=2.36" \
        "imageio-ffmpeg>=0.5.1" \
        "pillow>=11.0" \
        "reportlab>=4.2" \
        "openpyxl>=3.1" \
        "xlsxwriter>=3.2" \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.34" \
        "pydantic>=2.10" \
        "python-multipart>=0.0.20"

# ── Layer 6: Database, queue, scheduling, monitoring ────────────────────────
RUN pip install --no-cache-dir \
        "sqlalchemy>=2.0" \
        "psycopg2-binary>=2.9" \
        "alembic>=1.14" \
        "celery[redis]>=5.4" \
        "redis>=5.2" \
        "flower>=2.0" \
        "apscheduler>=3.10" \
        "prometheus-client>=0.21" \
        "psutil>=6.1"

# ── Layer 7: Auth & utilities ───────────────────────────────────────────────
RUN pip install --no-cache-dir \
        "python-jose[cryptography]>=3.3" \
        "passlib[bcrypt]>=1.7" \
        "python-dotenv>=1.0" \
        "pyyaml>=6.0" \
        "requests>=2.32" \
        "networkx>=3.4" \
        "joblib>=1.4"

# ── Layer 8: Catch-all (requirements.txt) ───────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt || \
    echo "[BUILD-WARN] Some requirements.txt entries failed — pipeline will use available subset"

# ── Layer 9: Application code ───────────────────────────────────────────────
COPY . /app/

RUN mkdir -p \
        /app/outputs/logs \
        /app/outputs/lineage \
        /app/outputs/quarantine \
        /app/config \
        /app/data \
        /app/inputs \
        /app/clinical_pk_data \
    && chmod -R 755 /app/outputs

# engine/ holds the flat cerebro_*.py modules (moved out of the project root
# for a cleaner layout); set PYTHONPATH here, before the build-check RUN
# steps below, since those run bare `python -c "from cerebro_value_resolver
# import ..."` commands that need it on the path too (run.py's own
# src/path_resolver.py bootstrap only helps process the app at runtime, not
# these standalone build-time smoke tests).
ENV PYTHONPATH=/app:/app/engine

# ── Build-time smoke tests (abort if core functionality missing) ────────────
RUN python -c "from cerebro_value_resolver import resolve_value, list_categories; \
                 print(f'[BUILD-CHECK] Resolver loaded: {len(list_categories())} categories'); \
                 r = resolve_value('drug_logp', smiles='CCO'); \
                 assert r.get('value') is not None, 'resolver smoke test FAILED'; \
                 print(f'[BUILD-CHECK] Smoke test passed: drug_logp(ethanol)={r[\"value\"]:.3f}')"

RUN python -c "import imageio_ffmpeg; from imageio_ffmpeg import get_ffmpeg_exe; \
                 print(f'[BUILD-CHECK] imageio_ffmpeg OK, ffmpeg: {get_ffmpeg_exe()}')"

RUN python -c "import matplotlib; matplotlib.use('Agg'); \
                 import matplotlib.font_manager as fm; \
                 fm._load_fontmanager(try_read_cache=False); \
                 from cerebro_brand import register_brand_fonts; \
                 status = register_brand_fonts(verbose=True); \
                 assert status['inter'] or status['liberation'], 'Font registration failed'; \
                 print(f'[BUILD-CHECK] Fonts: Inter={status[\"inter\"]}, Liberation={status[\"liberation\"]}')"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CEREBRO_VERSION=22.1 \
    CEREBRO_ARCH=bundle-only \
    MPLBACKEND=Agg \
    PYTHONPATH=/app:/app/engine

# src/api/app.py only defines /healthz, /readyz, /health/deep -- there is no
# plain /health route, so this always 404'd. docker-compose.prod.yml's own
# healthcheck already uses the real /healthz path; this image-level default
# was the only place still pointing at the wrong one.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

EXPOSE 8000 8001

# Not --headless: run.py's start_infra(headless=True) never starts uvicorn
# at all, so a plain `docker run` of this image with the default CMD would
# EXPOSE/advertise port 8000 and run the HEALTHCHECK above against it while
# nothing actually listened there. docker-compose.prod.yml already overrides
# this command with real uvicorn args, so this only changes the image's own
# standalone default (`docker run <image>` with no compose file) to match
# what its own EXPOSE/HEALTHCHECK directives promise.
CMD ["python", "run.py"]