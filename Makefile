# CopilotRunner — common dev tasks (Docker, backend, frontend, mobile)
.PHONY: help install install-backend install-frontend install-mobile \
	up down logs ps test test-backend lint lint-backend lint-frontend \
	lint-mobile format-backend clean

PYTHON ?= python3
COMPOSE ?= docker compose

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' Makefile | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend install-mobile ## Install dependencies for all apps

install-backend: ## Install backend (editable + dev extras)
	cd backend && $(PYTHON) -m pip install -e ".[dev]"

install-frontend: ## Install frontend npm packages
	cd frontend && npm ci

install-mobile: ## Fetch Flutter/Dart packages for mobile
	cd mobile && flutter pub get

up: ## Start full stack (postgres, qdrant, minio, backend, frontend)
	$(COMPOSE) up --build

down: ## Stop and remove compose containers (volumes kept)
	$(COMPOSE) down

logs: ## Follow compose logs
	$(COMPOSE) logs -f --tail=200

ps: ## Show compose service status
	$(COMPOSE) ps

test: test-backend ## Run tests (backend; extend when frontend/mobile tests exist)

test-backend: ## Run backend pytest
	cd backend && $(PYTHON) -m pytest

lint: lint-backend lint-frontend lint-mobile ## Run all linters

lint-backend: ## Ruff check backend
	cd backend && $(PYTHON) -m ruff check app tests

lint-frontend: ## Next.js lint
	cd frontend && npm run lint

lint-mobile: ## Flutter analyzer
	cd mobile && flutter analyze

format-backend: ## Format backend with Ruff
	cd backend && $(PYTHON) -m ruff format app tests

clean: ## Remove local Python/Node/Flutter caches (not docker volumes)
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next frontend/node_modules/.cache
	rm -rf mobile/build mobile/.dart_tool
