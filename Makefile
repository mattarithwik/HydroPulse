.DEFAULT_GOAL := help
PROFILE ?= direct
COMPOSE_PROFILES := monitoring$(if $(filter streaming,$(PROFILE)),, )$(if $(filter streaming,$(PROFILE)),streaming,)

.PHONY: help bootstrap start stop status test lint seed stage1-live stage1-backfill stage1-audit quality-audit upstream-audit upstream-backfill upstream-analysis freeze-manifest build-features replay backup restore
help:
	@awk 'BEGIN {FS=":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
bootstrap: ## Check prerequisites and create local directories
	@./scripts/bootstrap.sh
start: ## Start localhost services; PROFILE=streaming enables Kafka and Spark
	HYDROPULSE_INGESTION_MODE=$(PROFILE) COMPOSE_PROFILES=$(COMPOSE_PROFILES) docker compose up -d --build
stop: ## Stop services without deleting durable data
	docker compose down
status: ## Show service and resource state
	docker compose ps
	docker stats --no-stream $$(docker compose ps -q) 2>/dev/null || true
test: ## Run backend tests and frontend type/build checks
	python -m pytest
	cd frontend && npm run build
lint: ## Run Python lint checks
	python -m ruff check src tests
seed: ## Add explicitly synthetic UI-development observations
	python -m hydropulse.cli seed-demo
stage1-live: ## Archive current USGS and NWPS payloads for all targets
	PYTHONPATH=src .venv/bin/python -m hydropulse.stage1 live
stage1-backfill: ## Resume the native USGS backfill through the latest complete UTC day
	PYTHONPATH=src .venv/bin/python -m hydropulse.stage1 backfill-usgs --start 2007-10-01 --end $$(date -u -v-1d +%Y-%m-%d) --concurrency 4
stage1-audit: ## Build the current coverage and flood-episode report
	PYTHONPATH=src .venv/bin/python -m hydropulse.stage1 audit --end $$(date -u -v-1d +%Y-%m-%d)
quality-audit: ## Build detailed coverage, gap, threshold, and eligibility reports
	PYTHONPATH=src .venv/bin/python -m hydropulse.quality_audit --end $$(date -u -v-1d +%Y-%m-%d)
upstream-audit: ## Discover and qualify connected upstream gauge candidates
	PYTHONPATH=src .venv/bin/python -m hydropulse.upstream_audit audit --end 2026-09-13
upstream-backfill: ## Resume selected upstream gauge history acquisition
	PYTHONPATH=src .venv/bin/python -m hydropulse.upstream_audit backfill --report data/reports/upstream-audit-2026-09-13.json --end 2026-09-13
upstream-analysis: ## Verify actual upstream coverage and select training-only travel lags
	PYTHONPATH=src .venv/bin/python -m hydropulse.upstream_analysis --report data/reports/upstream-audit-2026-09-13.json --end 2026-09-13
freeze-manifest: ## Freeze the data split and qualified upstream lags before stage-model work
	PYTHONPATH=src .venv/bin/python -m hydropulse.evaluation_manifest --end 2026-09-13 --quality-report data/reports/quality-audit-2026-09-13.json --upstream-report data/reports/upstream-analysis-2026-09-13.json
build-features: ## Build causal river-only training examples from the frozen manifest
	PYTHONPATH=src .venv/bin/python -m hydropulse.features --manifest data/manifests/stage-model-2026-09-13.json --target $(TARGET)
replay: ## Create replay job (operator API once service is running)
	@echo "POST /api/v1/operator/replay with the local operator token"
backup: ## Create a local timestamped PostgreSQL backup
	@mkdir -p backups
	docker compose exec -T postgres pg_dump -U hydropulse -Fc hydropulse > backups/hydropulse-$$(date -u +%Y%m%dT%H%M%SZ).dump
restore: ## Restore DUMP into the running database (explicit DUMP=/path/file)
	@test -n "$(DUMP)" || (echo "DUMP is required" && exit 2)
	docker compose exec -T postgres pg_restore -U hydropulse -d hydropulse --clean --if-exists < "$(DUMP)"
