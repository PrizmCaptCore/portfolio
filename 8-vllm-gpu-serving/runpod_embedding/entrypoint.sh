#!/bin/bash
# Pulls the latest server.py from GitHub on each launch, then runs it.
# Loops on exit so the in-process /admin/reload handler can SIGTERM
# itself and the next iteration picks up freshly-pulled code without
# a full image rebuild. Heavy deps (vLLM, baked HF weights) are in
# the image once; code-only updates skip the build entirely.
#
# Required env:
#   GIT_PAT   GitHub PAT with read access to the runpod_deploy repo
# Optional env:
#   GIT_REF   branch / tag / commit to track (default: main)
#   GIT_REPO  owner/repo (default: your-org/runpod_deploy)
#
# Fallback: if GIT_PAT is unset or pull fails, the baked /app/server.py
# (COPY'd at image build time) is used.

set -u

REPO_DIR=/app/repo
DST=/app/server.py
REF=${GIT_REF:-main}
REPO=${GIT_REPO:-your-org/runpod_deploy}
SRC=$REPO_DIR/runpod_embedding/server.py

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

while true; do
  pull_code
  python3 "$DST"
  ec=$?
  echo "[entrypoint] server exited (code $ec), restarting in 2s"
  sleep 2
done
