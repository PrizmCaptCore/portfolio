FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# NVIDIA's pip ecosystem ships almost everything CUDA-related (cudart,
# cudnn, cublas, ptxas, libdevice) EXCEPT the nvcc front-end binary
# itself — `nvidia-cuda-nvcc-cu12` only contains ptxas + nvvm libs +
# headers, not nvcc. flashinfer JIT-compiles its sampling kernel for
# the specific GPU arch (sm_86 PTX → sm_89 runtime on L4 via driver)
# the first time vLLM's profile_run hits TopKTopPSampler, and bails
# with "/usr/local/cuda/bin/nvcc: not found" if nvcc isn't on disk.
# So we pull the actual nvcc + matching dev headers from NVIDIA's
# Debian apt repo: standard /usr/local/cuda-12.9 layout, ~250MB total.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git libsndfile1 ca-certificates binutils gcc g++ libc6-dev wget \
    && wget -qO /tmp/cuda-keyring.deb \
         https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.1-1_all.deb \
    && dpkg -i /tmp/cuda-keyring.deb \
    # NVIDIA's CUDA apt repo Release file is GPG-signed with SHA1,
    # which Debian 12's Sequoia PGP (sqv) rejects since 2026-02-01
    # ("not bound: No binding signature ... SHA1 is not considered
    # secure"). Until NVIDIA re-signs with SHA-256, mark the repo as
    # trusted=yes so apt skips signature verification for it. The
    # tarballs themselves are fetched from NVIDIA's CDN, so we still
    # rely on TLS for transport integrity.
    && find /etc/apt/sources.list.d -name 'cuda-*.list' \
         -exec sed -i 's|^deb \[|deb [trusted=yes |' {} \; \
    && apt-get update && apt-get install -y --no-install-recommends \
         cuda-nvcc-12-9 cuda-cudart-dev-12-9 cuda-cccl-12-9 \
         libcurand-dev-12-9 libcurand-12-9 \
    && ln -sfn /usr/local/cuda-12.9 /usr/local/cuda \
    && apt-get purge -y wget \
    && apt-get autoremove -y \
    && rm -rf /tmp/cuda-keyring.deb /var/lib/apt/lists/* /root/.cache /tmp/*

ARG VLLM_VERSION=0.21.0
ARG VLLM_WHEEL_URL=https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+cu129-cp38-abi3-manylinux_2_34_x86_64.whl
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cu129 \
      torch==2.11.0 \
    && pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cu129 \
      "${VLLM_WHEEL_URL}" \
      "mistral_common[audio]" \
      librosa soundfile \
      fastapi "uvicorn[standard]" websockets httpx numpy hf_transfer \
    && SITE=/usr/local/lib/python3.12/site-packages \
    && find "$SITE" -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true \
    && find "$SITE" -depth -type d \( \
         -name 'tests' -o -name 'test' -o -name '__tests__' \
         -o -name 'docs' -o -name 'doc' -o -name 'examples' -o -name 'example' \
         -o -name 'benchmarks' -o -name 'benchmark' \
       \) -exec rm -rf {} + 2>/dev/null || true \
    && find "$SITE" -depth -name __pycache__ -exec rm -rf {} + 2>/dev/null || true \
    && find "$SITE" -name '*.pyc' -delete 2>/dev/null || true \
    && rm -rf /root/.cache /tmp/* /var/lib/apt/lists/*

ARG MODEL_NAME=mistralai/Voxtral-Mini-4B-Realtime-2602
ENV MODEL_NAME=${MODEL_NAME}
ENV HF_HOME=/runpod-volume/hf-cache
ENV HF_HUB_ENABLE_HF_TRANSFER=1

# CUDA_HOME points at the apt-installed toolkit (symlinked to
# /usr/local/cuda-12.9 above). flashinfer's get_cuda_path() finds nvcc
# at $CUDA_HOME/bin/nvcc and headers under $CUDA_HOME/include during
# ninja-driven JIT compilation. Runtime libcudart loading still goes
# through torch's nvidia-cuda-runtime-cu12 wheel (LD_LIBRARY_PATH set
# by torch on import), so the apt cudart-dev here is only for nvcc's
# compile-time header resolution.
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$CUDA_HOME/bin:$PATH

ENV VLLM_DISABLE_COMPILE_CACHE=1

WORKDIR /app

COPY server.py ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8765
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
