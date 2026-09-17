# ============================================================================
# Relay Assistant — top-level Makefile
# ============================================================================
# Central entry point for common project tasks. Run all commands from the repo
# root without extra `cd frontend` steps.
#
# Quick start:
#   make install         # install npm dependencies
#   make dev             # run tauri dev
#   make build           # build distributable app (.app/.dmg)
#
# Help:
#   make help            # print available commands
# ============================================================================

# ---------------------------------------------------------------------------
# Configurable
# ---------------------------------------------------------------------------
PNPM        ?= pnpm
PYTHON      ?= python3
PIP         ?= pip3
FRONTEND_DIR := frontend

# Always run this Makefile relative to the repo root, even from subdirectories.
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# ---------------------------------------------------------------------------
# Explicit `.PHONY` targets to avoid filename collisions.
# ---------------------------------------------------------------------------
.PHONY: help install install-node dev dev-cloud dev-cloud-win build \
        build-local release-windows lint check

# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help

help: ## Print the list of available commands
	@echo "Relay Assistant — Makefile targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Supported environment overrides:"
	@echo "  PNPM=$(PNPM)  PYTHON=$(PYTHON)  PIP=$(PIP)"

# ---------------------------------------------------------------------------
# Dependency installation
# ---------------------------------------------------------------------------
install: install-node ## Install dependencies

install-node: ## Install frontend npm dependencies (pnpm install)
	cd $(FRONTEND_DIR) && $(PNPM) install

# Note: model assets (opus-mt translation, Xenova embedding model, audio
# icons, transformers wasm) are fetched automatically by the frontend's
# `prebuild` / `postinstall` hooks — no separate `make setup-model` step.
# The opt-in `local-ml` Cargo feature additionally needs
# `python scripts/setup_translation_model.py` (the runtime error message
# in audio/translation.rs already points at it).

# ---------------------------------------------------------------------------
# Tauri workflow
# ---------------------------------------------------------------------------
dev: ## Run tauri dev
	cd $(FRONTEND_DIR) && $(PNPM) tauri:dev

dev-cloud: ## Run tauri dev with cloud backend via relay_web gateway. Pass VERSION=x.y.z to stamp a non-DEMO version (auto-reverts on exit).
	cd $(FRONTEND_DIR) && \
	  if [ -n "$(VERSION)" ]; then \
	    BACKUP=$$(mktemp -d); \
	    echo "Stamping version $(VERSION) (backup at $$BACKUP, auto-reverts on exit)"; \
	    cp package.json "$$BACKUP/package.json"; \
	    cp src-tauri/tauri.conf.json "$$BACKUP/tauri.conf.json"; \
	    cp src-tauri/Cargo.toml "$$BACKUP/Cargo.toml"; \
	    trap 'echo "Reverting version stamp"; cp "$$BACKUP/package.json" package.json; cp "$$BACKUP/tauri.conf.json" src-tauri/tauri.conf.json; cp "$$BACKUP/Cargo.toml" src-tauri/Cargo.toml; rm -rf "$$BACKUP"' EXIT INT TERM; \
	    npm pkg set version="$(VERSION)" >/dev/null; \
	    node -e "const fs=require('fs');const p='src-tauri/tauri.conf.json';const d=JSON.parse(fs.readFileSync(p));d.version='$(VERSION)';fs.writeFileSync(p,JSON.stringify(d,null,4)+'\n');"; \
	    node -e "const fs=require('fs');const p='src-tauri/Cargo.toml';let c=fs.readFileSync(p,'utf8');c=c.replace(/^version = .*/m,'version = \"$(VERSION)\"');fs.writeFileSync(p,c);"; \
	  fi; \
	  RELAY_TRANSLATION_URL=https://api.example.com/api/v1/ai \
	    $(PNPM) tauri:dev

dev-cloud-win: ## Same as dev-cloud but auto-sources VS 2022 vcvars64 (Windows). No need to open "x64 Native Tools Command Prompt". Runs from any shell.
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-cloud-win.ps1 -Version "$(VERSION)"

build: ## Run tauri build — produces the distributable app (.app/.dmg on macOS, .exe/.msi on Windows). Model assets are pulled in by the frontend prebuild hook.
	cd $(FRONTEND_DIR) && $(PNPM) tauri:build

build-local: ## Local dev build — patches version to 0.0.1 so Windows MSI accepts it, then restores
	cd $(FRONTEND_DIR) && node scripts/build-local.mjs

release-windows: ## Build, sign, and upload Windows artifacts to the existing draft release. Usage: make release-windows TAG=0.0.19 [AWS_PROFILE=<profile>] [PUBLISH=1] [ONLY_UPLOAD=1]
	$(if $(strip $(TAG)),,$(error TAG=<X.Y.Z> is required, e.g. make release-windows TAG=0.0.19))
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release-windows.ps1 -Tag "$(TAG)" $(if $(AWS_PROFILE),-AwsProfile "$(AWS_PROFILE)",) $(if $(PUBLISH),-Publish,) $(if $(ONLY_UPLOAD),-OnlyUpload,)

upload-release-windows: ## Plain upload of pre-built Windows artifacts to the release. Use when release-windows.ps1's auth probe is being annoying. Usage: make upload-release-windows TAG=0.0.22
	$(if $(strip $(TAG)),,$(error TAG=<X.Y.Z> is required, e.g. make upload-release-windows TAG=0.0.22))
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/upload-release-windows.ps1 -Tag "$(TAG)"

# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------
lint: ## frontend lint
	cd $(FRONTEND_DIR) && $(PNPM) lint

check: ## Run a Rust backend compile check (cargo check)
	cd $(FRONTEND_DIR)/src-tauri && cargo check
