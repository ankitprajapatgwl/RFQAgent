# ============================================================================
# RFQ Agent — developer & container workflow
# Run `make` or `make help` to list available targets.
# ============================================================================

# Use bash for recipes.
SHELL := /bin/bash

# Docker Compose command (v2 plugin). Override with: make COMPOSE="docker-compose"
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help install run test lint format typecheck check \
        docker-build docker-up docker-down docker-logs docker-restart docker-shell clean

help: ## Show this help message
	@echo "RFQ Agent — available make targets:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""

# --------------------------------------------------------------------------
# Local (manual) workflow — uses `uv` for fast, reproducible environments.
# --------------------------------------------------------------------------
install: ## Create the virtualenv and install all deps (incl. dev extras)
	uv sync --extra dev

run: ## Run the app locally with autoreload (http://localhost:8000)
	uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

test: ## Run the unit test suite
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check src tests

format: ## Auto-format with ruff
	uv run ruff format src tests

typecheck: ## Static type-check with mypy
	uv run mypy

check: lint typecheck test ## Run lint + typecheck + tests (CI gate)

# --------------------------------------------------------------------------
# Docker workflow — full stack (FastAPI app + PostgreSQL).
# --------------------------------------------------------------------------
build: ## Build the application image
	$(COMPOSE) build

up: ## Build (if needed) and start the full stack in the background
	$(COMPOSE) up --build -d
	@echo "RFQ Agent is starting at http://localhost:8000  (docs: /docs)"

down: ## Stop the stack and remove containers
	$(COMPOSE) down

restart: ## Restart the stack
	$(COMPOSE) down && $(COMPOSE) up --build -d

logs: ## Follow application logs
	$(COMPOSE) logs -f app

shell: ## Open a shell inside the running app container
	$(COMPOSE) exec app /bin/bash

clean: ## Remove caches, build artifacts and the local SQLite database
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f data/*.db
