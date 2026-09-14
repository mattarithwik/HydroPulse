.DEFAULT_GOAL := help
PROFILE ?= direct
COMPOSE_PROFILES := monitoring$(if $(filter streaming,$(PROFILE)),, )$(if $(filter streaming,$(PROFILE)),streaming,)

.PHONY: help bootstrap start stop status test lint seed replay backup restore
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
replay: ## Create replay job (operator API once service is running)
	@echo "POST /api/v1/operator/replay with the local operator token"
backup: ## Create a local timestamped PostgreSQL backup
	@mkdir -p backups
	docker compose exec -T postgres pg_dump -U hydropulse -Fc hydropulse > backups/hydropulse-$$(date -u +%Y%m%dT%H%M%SZ).dump
restore: ## Restore DUMP into the running database (explicit DUMP=/path/file)
	@test -n "$(DUMP)" || (echo "DUMP is required" && exit 2)
	docker compose exec -T postgres pg_restore -U hydropulse -d hydropulse --clean --if-exists < "$(DUMP)"

