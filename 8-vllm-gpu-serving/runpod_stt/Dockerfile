FROM pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime

# Base image ships Python 3.12 with PEP 668 externally-managed-environment
# protection enabled. That's a host-system safeguard — inside a single-purpose
# container it just blocks pip. Disable it once globally instead of passing
# --break-system-packages to every pip call.
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

# NeMo source build. parakeet-unified-en-0.6b (2026-04 release) requires
# NeMo main. Pin NEMO_REF to a known-good commit when the build stabilizes
# — leaving it at `main` will silently drift across rebuilds.
ARG NEMO_REF=main
RUN git clone https://github.com/NVIDIA-NeMo/NeMo.git /opt/NeMo \
    && cd /opt/NeMo \
    && git checkout ${NEMO_REF} \
    && pip install --no-cache-dir -e ".[asr]"

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" websockets

ENV STT_MODEL=nvidia/parakeet-unified-en-0.6b
# Bake model weights so cold start doesn't hit HF.
RUN python -c "import nemo.collections.asr as nemo_asr; \
    nemo_asr.models.ASRModel.from_pretrained('nvidia/parakeet-unified-en-0.6b', map_location='cpu')"

WORKDIR /app
# server.py is baked as a fallback only. The entrypoint pulls a fresh
# copy from GitHub on each start (if GIT_PAT is set), so deploying
# code-only changes never requires rebuilding this image — just restart
# the Pod or hit POST /admin/reload.
COPY server.py .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8765

CMD ["/app/entrypoint.sh"]
