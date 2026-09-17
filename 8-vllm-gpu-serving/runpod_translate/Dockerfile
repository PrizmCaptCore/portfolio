FROM vllm/vllm-openai:latest

# vLLM image already ships Python + vLLM + CUDA deps. We only need the
# FastAPI proxy stack used by server.py and the RunPod serverless SDK,
# plus git so entrypoint.sh can pull fresh server.py from GitHub on
# each launch (zero-rebuild code deploys — see /admin/reload).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" openai httpx pydantic runpod hf_transfer

# Bake model weights into the image. RunPod uses on-demand active workers,
# so a fresh worker pulling the image must boot fast — downloading 8GB+ of
# weights from HF on first start would blow the warmup budget.
#
# HF_TOKEN is provided as a BuildKit secret from the GHA workflow.
# Build with:
#   docker build --secret id=hf_token,env=HF_TOKEN ...
ARG MODEL_NAME=google/translategemma-4b-it
ENV MODEL_NAME=${MODEL_NAME}
ENV HF_HOME=/root/.cache/huggingface
ENV HF_HUB_ENABLE_HF_TRANSFER=1
# Use snapshot_download directly — the `huggingface-cli download` subcommand
# was removed in recent huggingface_hub versions (replaced by `hf download`).
# Calling the library function avoids CLI surface churn across base image
# upgrades.
RUN --mount=type=secret,id=hf_token \
    HF_TOKEN=$(cat /run/secrets/hf_token) \
    python3 -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['MODEL_NAME'])"

# Weights are now baked in. At runtime we never want transformers/HF Hub
# to phone home for ETag / chat_template.json checks. Without these flags
# it does an unauthenticated HEAD against the gated repo and crashes 401.
# IMPORTANT: these MUST come AFTER the snapshot_download RUN above —
# otherwise the download itself is blocked.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

WORKDIR /app
# server.py is baked as fallback. entrypoint.sh pulls fresh code from
# GitHub on each start (if GIT_PAT is set), so code-only changes need
# only `git push` + `POST /admin/reload` — no image rebuild.
# handler.py is left for the legacy Serverless deployment path.
COPY server.py handler.py ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# server.py spawns vLLM on localhost:8001 and exposes the public API on 8000.
# Override the Container Start Command to `python handler.py` for Serverless.
EXPOSE 8000
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
