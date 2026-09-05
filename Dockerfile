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
LABEL org.opencontainers.image.source="https://github.com/mohamedtalaat-gif/CEREBRO-X"
LABEL org.opencontainers.image.licenses="Proprietary"
LABEL org.cerebro.version="22.1"

ARG PYTHON_ENV=production

# ── Layer 1: System dependencies + brand typography ────────────────────────
# libboost-all-dev + swig: required to build the `vina` PyPI package from
# source. vina 1.2.7 (the version real_docking_engine.py targets) ships
# prebuilt wheels only up to cp312 -- none for this image's Python 3.13 --
# so `pip install vina` needs the actual C++ build toolchain (Boost +
# SWIG-generated bindings) rather than a wheel. Without these two packages
# the install fails outright and every docking call silently falls back to
# the LIE approximation, which is what was happening before this line
# existed despite the README/outreach materials already claiming real
# AutoDock Vina docking.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ gfortran \
        libffi-dev libssl-dev \
        libopenblas-dev liblapack-dev \
        libhdf5-dev \
        libboost-all-dev swig \
        curl wget git \
        ca-certificates \
        fonts-inter fonts-liberation fontconfig \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

WORKDIR /app

# A single dead network read can otherwise abort a whole layer after minutes
# of downloading, and -- combined with the "|| echo [BUILD-WARN]" fallbacks
# below, which exist so one optional package can't sink the whole image --
# that failure gets cached by Docker as a permanent "done" layer: every later
# rebuild reuses it without ever retrying, even once the network recovers.
# Longer timeouts and more retries make pip itself survive a flaky connection
# instead of relying on this Dockerfile getting rebuilt with --no-cache.
ENV PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# ── Layer 2: Scientific foundation (latest stable where safe) ──────────────
RUN pip install --no-cache-dir \
        "numpy>=2.0,<3.0" \
        "pandas>=2.3" \
        "scipy>=1.17" \
        "scikit-learn>=1.8" \
        "matplotlib>=3.10" \
        "seaborn>=0.13.2" \
        "shap>=0.46"

# xgboost installed separately with --no-deps: its Linux PyPI wheel declares
# a hard dependency on nvidia-nccl-cu13 (a ~250MB CUDA library, only needed
# for XGBoost's optional multi-GPU distributed-training path) even though
# nothing in this codebase ever sets tree_method="gpu_hist" or a CUDA device
# -- every XGBRegressor call here (src/core/pipeline.py, pipeline_patches.py)
# is plain CPU usage. xgboost's actual runtime imports for CPU use are
# numpy/scipy, both already installed above, so --no-deps is safe here and
# avoids downloading/shipping a multi-hundred-MB library this project never
# uses.
RUN pip install --no-cache-dir --no-deps "xgboost>=2.1"

# ── Layer 3: Cheminformatics & Bioinformatics (pinned for compatibility) ────
RUN pip install --no-cache-dir rdkit==2024.9.4               || echo "[BUILD-WARN] rdkit"
# biopython pinned to 1.88, not the older 1.84: 1.84 predates Python 3.13
# wheel builds, so it silently fell back to a from-source build that never
# ran (no network access to even fetch the sdist during a prior flaky
# build) -- 1.88 ships a manylinux_aarch64 cp313 wheel and satisfies the
# same >=1.83,<2.0 range requirements.txt already allows.
RUN pip install --no-cache-dir biopython==1.88                || echo "[BUILD-WARN] biopython"
RUN pip install --no-cache-dir chembl-webresource-client      || echo "[BUILD-WARN] chembl-webresource-client"
RUN pip install --no-cache-dir pubchempy==1.0.4               || echo "[BUILD-WARN] pubchempy"
# MDAnalysis pinned to 2.10.0, not the older 2.7.0: 2.7.0 hard-requires
# numpy<2.0, which directly conflicts with this project's numpy>=2.0 and
# can never install here regardless of network conditions. 2.10.0 requires
# numpy>=1.26.0 (compatible) and, like shap above, has no prebuilt wheel
# for linux/aarch64 + cp313 yet, so pip builds it from source using the
# gcc/gfortran/openblas/lapack toolchain installed in Layer 1.
RUN pip install --no-cache-dir MDAnalysis==2.10.0             || echo "[BUILD-WARN] MDAnalysis"
# vina 1.2.7 pinned to match real_docking_engine.py's docstring and the
# capability already described to outside parties. No cp313 wheel exists
# (see Layer 1 comment), so this builds from source against the Boost/SWIG
# toolchain installed above -- expect this step to take several minutes.
RUN pip install --no-cache-dir vina==1.2.7                    || echo "[BUILD-WARN] vina"
# meeko converts RDKit molecules to PDBQT for Vina. Pure-Python (py3-none-
# any wheel), no build toolchain needed. gemmi is meeko's own dependency
# for macrocycle/mmCIF handling -- meeko's package metadata doesn't declare
# it as a hard require, so pip installs meeko without it and it only
# surfaces as a runtime ModuleNotFoundError the first time ligand prep runs.
RUN pip install --no-cache-dir meeko>=0.6 gemmi>=0.6           || echo "[BUILD-WARN] meeko/gemmi"

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