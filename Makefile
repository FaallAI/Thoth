# Developer and operator commands. Run from WSL at the repository root: `make help`.
# The Windows CUDA build of the Rust CLI stays on build_cuda.bat.

SHELL := /bin/bash
.DEFAULT_GOAL := help

RUFF := $(HOME)/.local/bin/uvx ruff@0.17.2
PY_PATHS := python/src python/tests
# Bun is installed on Windows only; WSL reaches it through interop.
BUN := $(shell command -v bun || command -v bun.exe)
COMPOSE := docker compose --env-file .env.stage1.local -f compose.stage1.local.yml -f compose.stage1.providers.yml -f compose.stage1.renderer.yml
T ?= tests
SERVICE ?= worker

.PHONY: help test lint format check test-postgres test-minio dashboard-test dashboard-build smoke-cdp smoke-browser smoke-renderer deploy status logs captcha-stats

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

test: ## Python tests; T=<path> narrows them (default: the whole suite)
	bash scripts/dev/pytest-wsl.sh $(T)

lint: ## ruff check and format check
	$(RUFF) check $(PY_PATHS)
	$(RUFF) format --check $(PY_PATHS)

format: ## ruff format, then ruff check --fix
	$(RUFF) format $(PY_PATHS)
	$(RUFF) check --fix $(PY_PATHS)

check: lint test ## lint, then the whole Python suite

test-postgres: ## Postgres-backed tests on a throwaway PostgreSQL 16.4 (a skip is a failure)
	bash scripts/dev/pytest-postgres.sh

test-minio: ## Media store tests on a throwaway MinIO (a skip is a failure)
	bash scripts/dev/pytest-minio.sh

dashboard-test: ## Dashboard tests
	cd dashboard && $(BUN) test

dashboard-build: ## Dashboard type check and build
	cd dashboard && $(BUN) run build

smoke-cdp: ## Offline CDP sidecar smoke; IMAGE=<image>
	bash docker/test-cdp-offline.sh $(IMAGE)

smoke-browser: ## Offline stealthy-browser launch smoke; IMAGE=<image>
	bash docker/test-browser-offline.sh $(IMAGE)

smoke-renderer: ## Offline renderer + web smoke; IMAGE=<image> RENDERER_IMAGE=<image> WEB_IMAGE=<image>
	bash docker/test-renderer-offline.sh $(IMAGE) $(RENDERER_IMAGE) $(WEB_IMAGE)

deploy: ## Deploy the stack on the THOTH_IMAGE pinned in .env.stage1.local
	bash scripts/ops/deploy-stage1.sh

captcha-stats: ## Save the worker's captcha outcome lines, then count every saved one
	bash scripts/ops/captcha-outcomes.sh

status: ## Stack service status
	$(COMPOSE) ps --format '{{.Service}} {{.Status}}'

logs: ## Last 200 log lines of one service; SERVICE=<name> (default: worker)
	$(COMPOSE) logs --tail=200 $(SERVICE)
