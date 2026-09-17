FROM vllm/vllm-openai:latest

# vLLM image already ships Python + vLLM + CUDA deps. We only need the
# FastAPI proxy stack used by server.py and the RunPod serverless SDK,
# plus git so entrypoint.sh can pull fresh server.py from GitHub on
# each launch (zero-rebuild code deploys — see /admin/reload).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" httpx pydantic runpod hf_transfer

# Bake model weights into the image. RunPod uses on-demand active workers
# for chat (real-time meeting summaries can't tolerate cold start), so the
# image must boot fast — downloading 5GB+ from HF on first start would blow
# the warmup budget.
#
# HF_TOKEN is provided as a BuildKit secret from the GHA workflow.
ARG SUMMARY_MODEL=google/gemma-4-E2B-it
ENV SUMMARY_MODEL=${SUMMARY_MODEL}
ENV HF_HOME=/root/.cache/huggingface
ENV HF_HUB_ENABLE_HF_TRANSFER=1
# Use snapshot_download directly — the `huggingface-cli download` subcommand
# was removed in recent huggingface_hub versions (replaced by `hf download`).
# Calling the library function avoids CLI surface churn across base image
# upgrades.
RUN --mount=type=secret,id=hf_token \
    HF_TOKEN=$(cat /run/secrets/hf_token 2>/dev/null || echo "") \
    python3 -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['SUMMARY_MODEL'])"

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

# server.py = Pod (FastAPI on :8000, vLLM on :8001)
# handler.py = Serverless (RunPod SDK)
# Override the Container Start Command to `python3 handler.py` for Serverless.
EXPOSE 8000
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
