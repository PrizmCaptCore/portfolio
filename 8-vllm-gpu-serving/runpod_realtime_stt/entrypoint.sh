#!/bin/bash
# RealtimeSTT STT entrypoint. Two responsibilities:
#
#  (1) Bootstrap model weights onto the RunPod Network Volume on first
#      start, then go offline. The image itself no longer bakes weights
#      (was ~64GB → now <10GB). First pod-with-empty-volume eats a
#      ~9GB HF download (~60-90s on RunPod's bandwidth); every restart
#      and every additional pod sharing the volume reuses the cache.
#
#  (2) Pull fresh server.py from GitHub on each launch (zero-rebuild
#      code deploy — same pattern as runpod_stt / runpod_translate).
#      vLLM is a separate subprocess spawned inside server.py, so
#      /admin/reload only bounces the FastAPI layer; vLLM stays warm
#      and the next iteration reuses it via the _vllm_running() probe.
#
# Optional env:
#   HF_TOKEN  HuggingFace token. the realtime STT model is
#             Apache-2.0 / not gated, so a token is NOT required —
#             only useful to dodge anonymous-rate-limit throttling
#             on first download. Subsequent restarts hit the cache
#             and ignore HF_TOKEN entirely.
#   GIT_PAT   GitHub PAT with read access to the runpod_deploy repo
#   GIT_REF   branch / tag / commit to track (default: main)
#   GIT_REPO  owner/repo (default: your-org/runpod_deploy)
#   MODEL_NAME  HF repo id (default from Dockerfile)
#
# Fallback: if GIT_PAT is unset or git pull fails, the baked
# /app/server.py (COPY'd at image build time) is used. Pod keeps
# serving.

set -u

REPO_DIR=/app/repo
DST=/app/server.py
REF=${GIT_REF:-main}
REPO=${GIT_REPO:-your-org/runpod_deploy}
SRC=$REPO_DIR/runpod_realtime_stt/server.py
MODEL=${MODEL_NAME:?set MODEL_NAME (HF id of the realtime STT model; see Dockerfile)}

bootstrap_weights() {
  # HF_HOME is set in the Dockerfile to /runpod-volume/hf-cache. If the
  # Network Volume isn't mounted (dev/local run) we fall back to the
  # default in-container cache so the Pod still boots — just without
  # cross-restart persistence.
  if [ ! -d "/runpod-volume" ]; then
    echo "[entrypoint] WARNING: /runpod-volume not mounted — weights will not persist across restarts"
    export HF_HOME=/root/.cache/huggingface
  fi
  mkdir -p "$HF_HOME"

  # snapshot_download is idempotent — already-present files are
  # verified-and-skipped (~1-2s when fully cached), missing files are
  # filled in. So we always call it instead of trying to short-circuit
  # on a presence check. The old "if snapshots/ has any file, skip"
  # heuristic let partial-cache states (eg a previous Pod crashed mid-
  # download) boot vLLM with the safetensors present but tekken.json
  # missing, which dies with "No tokenizer file found."
  #
  # allow_patterns: skip the HF-format weight duplicate
  # (model.safetensors, ~9GB) which vLLM never reads under
  # --load-format mistral. Keep the tiny HF metadata files
  # (config.json / generation_config.json / processor_config.json,
  # ~2KB total) so vLLM's best-effort AutoConfig fallback path
  # doesn't dump noisy WARNING tracebacks on every startup.
  # token=None is fine — the realtime STT model is Apache-2.0;
  # HF_TOKEN is only consulted to escape anonymous rate limits.
  echo "[entrypoint] verifying weights at $HF_HOME (Mistral-format only)"
  MODEL="$MODEL" python3 -c "
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id=os.environ['MODEL'],
    token=os.environ.get('HF_TOKEN') or None,
    allow_patterns=[
        'consolidated*.safetensors',
        'params.json',
        'tekken.json',
        'config.json',
        'generation_config.json',
        'processor_config.json',
    ],
)
" || { echo "[entrypoint] weight download failed"; exit 1; }
  echo "[entrypoint] weights ready"

  # Now that weights are local, block HF Hub HEAD checks at runtime so
  # a gated repo doesn't 401 on every model load (same logic the old
  # image-bake flow used after snapshot_download). MUST be set AFTER
  # the download above.
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
}

pull_code() {
  if [ -z "${GIT_PAT:-}" ]; then
    echo "[entrypoint] GIT_PAT not set, using baked $DST"
    return 0
  fi
  if [ -d "$REPO_DIR/.git" ]; then
    echo "[entrypoint] fetch + reset to origin/$REF"
    git -C "$REPO_DIR" fetch --depth 1 origin "$REF" 2>&1 || {
      echo "[entrypoint] fetch failed, keeping previous code"
      return 0
    }
    git -C "$REPO_DIR" reset --hard FETCH_HEAD 2>&1 || return 0
  else
    echo "[entrypoint] cloning $REPO@$REF"
    rm -rf "$REPO_DIR"
    git clone --branch "$REF" --depth 1 \
      "https://x-access-token:${GIT_PAT}@github.com/${REPO}.git" \
      "$REPO_DIR" 2>&1 || {
      echo "[entrypoint] clone failed, using baked $DST"
      return 0
    }
  fi
  if [ ! -f "$SRC" ]; then
    echo "[entrypoint] $SRC missing in repo, keeping previous $DST"
    return 0
  fi
  if ! python3 -c "import ast, sys; ast.parse(open('$SRC').read())" 2>/dev/null; then
    echo "[entrypoint] syntax check failed for $SRC, keeping previous $DST"
    return 0
  fi
  cp "$SRC" "$DST"
  echo "[entrypoint] code pulled: $(git -C "$REPO_DIR" rev-parse --short HEAD)"
}

# Weight bootstrap runs once before the supervisor loop — subsequent
# /admin/reload iterations skip the download branch (cache hit).
bootstrap_weights

while true; do
  pull_code
  python3 "$DST"
  ec=$?
  echo "[entrypoint] server exited (code $ec), restarting in 2s"
  sleep 2
done
