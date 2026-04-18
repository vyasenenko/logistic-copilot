# CopilotRunner — dev workflow (Docker, backend, frontend, mobile)
# Usage: make help | make up-d | make restart-backend | V=1 make up

PROJECT_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.DEFAULT_GOAL := help

# Verbose recipes: V=1 shows commands (default: quiet)
ifneq ($(V),1)
  Q := @
endif

# Prefer project venv when present (override: make PYTHON=/path/to/python)
PYTHON ?= $(shell test -x backend/.venv/bin/python && echo backend/.venv/bin/python || echo python3)
COMPOSE ?= docker compose
LOG_TAIL ?= 200

# Compose service names (for restart/logs/shell pattern targets)
STACK_SERVICES := backend frontend postgres qdrant minio

# --- Logging (stderr, timestamp, ANSI) ---------------------------------------
define log_info
	@printf '\033[36m[%s]\033[0m \033[1m▶\033[0m %s\n' "$$(date '+%H:%M:%S')" '$(1)' >&2
endef

define log_ok
	@printf '\033[32m[%s]\033[0m \033[1m✓\033[0m %s\n' "$$(date '+%H:%M:%S')" '$(1)' >&2
endef

define log_warn
	@printf '\033[33m[%s]\033[0m \033[1m!\033[0m %s\n' "$$(date '+%H:%M:%S')" '$(1)' >&2
endef

define log_err
	@printf '\033[31m[%s]\033[0m \033[1m✗\033[0m %s\n' "$$(date '+%H:%M:%S')" '$(1)' >&2
endef

# --- Phony targets ------------------------------------------------------------
.PHONY: help doctor env-check install install-backend install-frontend install-mobile \
	build build-nc pull up up-d down stop restart \
	$(addprefix restart-,$(STACK_SERVICES)) \
	logs logs-json \
	$(addprefix logs-,$(STACK_SERVICES)) \
	ps shell-backend shell-frontend psql \
	rebuild destroy clean clean-docker \
	test test-backend lint lint-backend lint-frontend lint-mobile \
	format format-backend ci status curl-health

# =============================================================================
# Help
# =============================================================================

help: ## Красивый список целей (секции, по-русски) — см. scripts/make_help.py
	$(Q)python3 "$(PROJECT_ROOT)scripts/make_help.py" "$(abspath $(lastword $(MAKEFILE_LIST)))"

# =============================================================================
# Environment checks
# =============================================================================

doctor: ## Версии docker, compose, python, node, npm, flutter
	$(call log_info,Environment probe)
	$(Q)printf '\n  \033[1m--- Versions ---\033[0m\n'
	$(Q)if ! command -v docker >/dev/null 2>&1; then \
		printf '\033[31m[%s]\033[0m \033[1m✗\033[0m docker not found\n' "$$(date '+%H:%M:%S')" >&2; \
		exit 1; \
	fi
	$(Q)docker --version
	$(Q)docker compose version 2>/dev/null || docker-compose version 2>/dev/null || true
	$(Q)command -v $(PYTHON) >/dev/null && $(PYTHON) --version || true
	$(Q)command -v node >/dev/null && node --version || printf '  (node not on PATH — OK if you only use Docker for frontend)\n'
	$(Q)command -v npm >/dev/null && npm --version || true
	$(Q)command -v flutter >/dev/null && flutter --version | head -n 1 || printf '  (flutter not on PATH)\n'
	$(Q)printf '\n'
	$(call log_ok,doctor finished)

env-check: ## Ошибка, если нет .env в корне (нужен для compose)
	$(Q)if [ ! -f .env ]; then \
		printf '\033[31m[%s]\033[0m \033[1m✗\033[0m Missing .env — copy from .env.example\n' "$$(date '+%H:%M:%S')" >&2; \
		exit 1; \
	fi
	$(call log_ok,.env present)

# =============================================================================
# Dependencies (host)
# =============================================================================

install: install-backend install-frontend install-mobile ## Зависимости локально: backend, frontend, mobile
	$(call log_ok,install complete)

install-backend: ## pip install -e "backend[dev]" (редактируемая установка + dev)
	$(call log_info,pip install -e backend[dev])
	$(Q)cd backend && $(PYTHON) -m pip install -e ".[dev]"
	$(call log_ok,backend ready)

install-frontend: ## npm ci в каталоге frontend
	$(call log_info,npm ci — frontend)
	$(Q)cd frontend && npm ci
	$(call log_ok,frontend node_modules ready)

install-mobile: ## flutter pub get в каталоге mobile
	$(call log_info,flutter pub get — mobile)
	$(Q)cd mobile && flutter pub get
	$(call log_ok,mobile deps ready)

# =============================================================================
# Docker — build & registry
# =============================================================================

build: ## Собрать все образы docker compose
	$(call log_info,docker compose build)
	$(Q)$(COMPOSE) build
	$(call log_ok,build finished)

build-nc: ## Сборка без кэша (чисто, дольше)
	$(call log_warn,Building without cache — may take a while)
	$(Q)$(COMPOSE) build --no-cache
	$(call log_ok,build-nc finished)

pull: ## Скачать базовые образы для сервисов compose
	$(call log_info,docker compose pull)
	$(Q)$(COMPOSE) pull
	$(call log_ok,pull finished)

# =============================================================================
# Docker — lifecycle
# =============================================================================

up: env-check ## Запуск стека в foreground (логи в терминале; Ctrl+C останавливает)
	$(call log_info,Starting stack — foreground attach to compose)
	$(Q)$(COMPOSE) up --build
	$(call log_warn,compose up exited)

up-d: env-check ## Сборка и запуск стека в фоне (detached)
	$(call log_info,Starting stack — detached)
	$(Q)$(COMPOSE) up -d --build
	$(call log_ok,Stack running — make ps | make logs | http://localhost:3000)
	$(Q)$(COMPOSE) ps

down: ## Остановить и удалить контейнеры (именованные volumes сохраняются)
	$(call log_info,docker compose down)
	$(Q)$(COMPOSE) down
	$(call log_ok,down complete)

stop: ## Только остановить контейнеры (не удалять)
	$(call log_info,docker compose stop)
	$(Q)$(COMPOSE) stop
	$(call log_ok,stop complete)

restart: env-check ## Перезапустить все сервисы compose (без пересборки образов)
	$(call log_info,Restarting all services: $(STACK_SERVICES))
	$(Q)$(COMPOSE) restart $(STACK_SERVICES)
	$(call log_ok,restart complete)

restart-%: env-check ## Перезапуск одного сервиса, напр. make restart-backend
	$(call log_info,Restarting service: $*)
	$(Q)$(COMPOSE) restart $*
	$(call log_ok,service $* restarted)

rebuild: env-check ## Полная пересборка образов и up -d
	$(call log_warn,Full rebuild + up -d — databases keep data on named volumes)
	$(Q)$(COMPOSE) build --no-cache
	$(Q)$(COMPOSE) up -d
	$(call log_ok,rebuild complete)
	$(Q)$(COMPOSE) ps

destroy: ## Удалить контейнеры и volumes (БД и данные; CONFIRM=YES — без вопроса)
	$(call log_warn,This runs: docker compose down -v)
	$(Q)if [ "$(CONFIRM)" = "YES" ]; then \
		:; \
	else \
		read -r -p "Type YES to delete volumes: " confirm && [ "$$confirm" = "YES" ] || { echo Aborted.; exit 1; }; \
	fi
	$(Q)$(COMPOSE) down -v
	$(call log_ok,destroy complete — data volumes removed)

# =============================================================================
# Docker — observability & shells
# =============================================================================

ps: ## Статус контейнеров (docker compose ps -a)
	$(call log_info,docker compose ps)
	$(Q)$(COMPOSE) ps -a

status: env-check ## ps + быстрый запрос /health бэкенда (если поднят)
	$(call log_info,Stack status)
	$(Q)$(COMPOSE) ps -a
	$(Q)printf '\n  \033[1mBackend /health\033[0m → '
	$(Q)if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null; then \
		printf '\033[32mOK\033[0m (http://localhost:8000/health)\n'; \
	else \
		printf '\033[33munreachable\033[0m (start with: make up-d)\n'; \
	fi

curl-health: ## GET /health с хоста (бэкенд на порту 8000)
	$(call log_info,curl http://127.0.0.1:8000/health)
	$(Q)curl -sS -f http://127.0.0.1:8000/health | (command -v jq >/dev/null && jq . || cat -)
	$(Q)printf '\n'

logs: ## Хвост логов всех сервисов (сколько строк: переменная LOG_TAIL, по умолчанию 200)
	$(call log_info,Tailing all logs — Ctrl+C to stop — tail=$(LOG_TAIL))
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL)

logs-json: ## Как logs, но с таймстемпами Docker (удобно grep)
	$(call log_info,Tailing all logs with timestamps)
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL) -t

logs-%: ## Логи одного сервиса, напр. make logs-backend LOG_TAIL=500
	$(call log_info,Tailing logs: $* — tail=$(LOG_TAIL))
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL) $*

shell-backend: ## Интерактивный shell в контейнере backend
	$(call log_info,exec backend — shell)
	$(Q)$(COMPOSE) exec backend sh -c 'if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi'

shell-frontend: ## Интерактивный shell в контейнере frontend
	$(call log_info,exec frontend — shell)
	$(Q)$(COMPOSE) exec frontend sh

psql: ## psql в postgres (пользователь agent, БД agent_db)
	$(call log_info,psql agent_db)
	$(Q)$(COMPOSE) exec postgres psql -U agent -d agent_db

# =============================================================================
# Quality — tests & lint
# =============================================================================

test: test-backend ## Запуск тестов (сейчас только backend)

test-backend: ## pytest в backend/ (доп. аргументы: ARGS='-v -k имя')
	$(call log_info,pytest backend)
	$(Q)cd backend && $(PYTHON) -m pytest $(ARGS)
	$(call log_ok,pytest done)

lint: lint-backend lint-frontend lint-mobile ## Все линтеры подряд
	$(call log_ok,lint complete)

lint-backend: ## ruff check в backend
	$(call log_info,ruff check)
	$(Q)cd backend && $(PYTHON) -m ruff check app tests
	$(call log_ok,ruff ok)

lint-frontend: ## next lint во frontend
	$(call log_info,npm run lint — frontend)
	$(Q)cd frontend && npm run lint
	$(call log_ok,next lint ok)

lint-mobile: ## flutter analyze в mobile
	$(call log_info,flutter analyze — mobile)
	$(Q)cd mobile && flutter analyze
	$(call log_ok,flutter analyze ok)

format: format-backend ## Форматирование кода (сейчас backend через ruff)

format-backend: ## ruff format в backend
	$(call log_info,ruff format)
	$(Q)cd backend && $(PYTHON) -m ruff format app tests
	$(call log_ok,ruff format done)

ci: lint test ## Как в CI: сначала lint, затем test
	$(call log_ok,ci pipeline finished)

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Удалить локальные кэши Python/Node/Flutter (не docker volumes)
	$(call log_info,Cleaning local caches under backend/ frontend/ mobile/)
	$(Q)find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)rm -rf frontend/.next frontend/node_modules/.cache
	$(Q)rm -rf mobile/build mobile/.dart_tool
	$(call log_ok,clean done)

clean-docker: ## docker image prune -f (неиспользуемые образы)
	$(call log_warn,Pruning dangling Docker images)
	$(Q)docker image prune -f
	$(call log_ok,clean-docker done)
