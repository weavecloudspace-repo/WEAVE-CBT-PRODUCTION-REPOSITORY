# syntax=docker/dockerfile:1.7

# =============================
# Build the React/Vite frontend
# =============================

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# =====================================================
# Shared Python/Nuitka toolchain for compiled artifacts
# =====================================================

FROM python:3.11-slim-bookworm AS python-build-base

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ccache \
        patchelf \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /workspace/backend/requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /workspace/backend/requirements.txt

COPY deployment/docker/app/nuitka/requirements-build.txt \
    /workspace/deployment/docker/app/nuitka/requirements-build.txt
RUN python -m pip install --no-cache-dir \
    -r /workspace/deployment/docker/app/nuitka/requirements-build.txt

ENV CCACHE_DIR=/root/.cache/ccache \
    CCACHE_BASEDIR=/workspace \
    CCACHE_COMPILERCHECK=content \
    CCACHE_MAXSIZE=2G


# =======================================================
# Compile the backend once for API, worker and schema bootstrap
# =======================================================

FROM python-build-base AS backend-builder

COPY backend/ /workspace/backend/
COPY deployment/docker/app/entrypoints/runtime.py \
    /workspace/deployment/docker/app/entrypoints/runtime.py
COPY deployment/docker/app/nuitka/common-options.txt \
    /workspace/deployment/docker/app/nuitka/common-options.txt
COPY deployment/docker/app/nuitka/build-runtime.sh \
    /workspace/deployment/docker/app/nuitka/build-runtime.sh

RUN chmod +x /workspace/deployment/docker/app/nuitka/build-runtime.sh
RUN --mount=type=cache,id=weave-nuitka-ccache,target=/root/.cache/ccache \
    /workspace/deployment/docker/app/nuitka/build-runtime.sh \
    && ccache --show-stats


# =========================
# Shared runtime foundation
# =========================

FROM python:3.11-slim-bookworm AS runtime-base

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p \
        /var/lib/weave-cbt/identity \
        /var/lib/weave-cbt/media \
        /var/lib/weave-cbt/branding


# =======================================================
# Bootstrap-only runtime for an early schema smoke test
# =======================================================

FROM runtime-base AS bootstrap-runtime

COPY --from=backend-builder \
    /workspace/deployment/docker/app/build/nuitka/runtime/weave-cbt.dist \
    /app/weave-cbt

CMD ["/app/weave-cbt/weave-cbt", "bootstrap"]


# ===============================
# Final WEAVE CBT runtime image
# ===============================

FROM runtime-base AS runtime

COPY --from=backend-builder \
    /workspace/deployment/docker/app/build/nuitka/runtime/weave-cbt.dist \
    /app/weave-cbt

# Frontend remains a separate artifact. Frontend-only changes do not invalidate
# the Nuitka backend compilation stage.
COPY --from=frontend-builder /workspace/frontend/dist /app/web

EXPOSE 8000

# API is the default process. Compose selects worker/bootstrap modes explicitly.
CMD ["/app/weave-cbt/weave-cbt", "api"]
