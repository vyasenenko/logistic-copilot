# Logistic Copilot - development, environment, Docker, and deployment workflow
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
.PHONY: help doctor env-init env-check env-set install install-backend install-frontend \
	build build-nc pull up up-d down stop restart \
	$(addprefix restart-,$(STACK_SERVICES)) \
	logs logs-json \
	$(addprefix logs-,$(STACK_SERVICES)) \
	ps shell-backend shell-frontend psql \
	rebuild destroy clean clean-docker \
	test test-backend lint lint-backend lint-frontend \
	format format-backend ci status curl-health \
	k8s-vars k8s-context \
	k8s-buildx-backend k8s-buildx-frontend k8s-buildx-all k8s-release \
	k8s-apply-namespace k8s-apply-secrets k8s-apply-config k8s-apply-databases \
	k8s-apply-app k8s-apply-ingress k8s-apply-letsencrypt-issuer \
	k8s-apply-base k8s-apply-full k8s-apply-dry-run \
	k8s-secret-from-env \
	k8s-rollout-restart k8s-rollout-restart-backend k8s-rollout-restart-frontend \
	k8s-status k8s-get k8s-logs-backend k8s-logs-frontend k8s-describe-backend k8s-events \
	k8s-certificates k8s-port-forward-backend \
	k8s-do-kubeconfig k8s-helm-cert-manager k8s-helm-ingress-nginx \
	k8s-bootstrap-infra k8s-ship-images

# =============================================================================
# Help
# =============================================================================

help: ## Show grouped command help.
	$(Q)python3 "$(PROJECT_ROOT)scripts/make_help.py" "$(PROJECT_ROOT)Makefile"

# =============================================================================
# Environment checks
# =============================================================================

doctor: ## Print local tool versions and runtime availability.
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
	$(Q)printf '\n'
	$(call log_ok,doctor finished)

env-init: ## Create .env from .env.example if it does not exist.
	$(Q)if [ -f .env ]; then \
		printf '\033[33m[%s]\033[0m \033[1m!\033[0m .env already exists; not overwriting\n' "$$(date '+%H:%M:%S')" >&2; \
	else \
		cp .env.example .env; \
		printf '\033[32m[%s]\033[0m \033[1m✓\033[0m created .env from .env.example\n' "$$(date '+%H:%M:%S')" >&2; \
	fi
	$(Q)$(PYTHON) "$(PROJECT_ROOT)scripts/check_env.py" --env "$(PROJECT_ROOT).env" --example "$(PROJECT_ROOT).env.example" || true

env-check: ## Validate .env against .env.example with required/optional/secret metadata.
	$(Q)$(PYTHON) "$(PROJECT_ROOT)scripts/check_env.py" --env "$(PROJECT_ROOT).env" --example "$(PROJECT_ROOT).env.example" --show-extra

env-set: ## Set one .env value safely: make env-set KEY=NAME VALUE='secret'
	$(Q)if [ -z "$(KEY)" ]; then \
		printf '\033[31mSet KEY, example: make env-set KEY=API_SECRET_KEY VALUE=...\033[0m\n' >&2; \
		exit 1; \
	fi
	$(Q)if [ -z "$(VALUE)" ]; then \
		printf '\033[31mSet VALUE, example: make env-set KEY=%s VALUE=...\033[0m\n' "$(KEY)" >&2; \
		exit 1; \
	fi
	$(Q)$(PYTHON) "$(PROJECT_ROOT)scripts/set_env_value.py" --file "$(PROJECT_ROOT).env" --key "$(KEY)" --value "$(VALUE)" --create
	$(Q)$(PYTHON) "$(PROJECT_ROOT)scripts/check_env.py" --env "$(PROJECT_ROOT).env" --example "$(PROJECT_ROOT).env.example" --show-extra || true

# =============================================================================
# Dependencies (host)
# =============================================================================

install: install-backend install-frontend ## Install dependencies locally: backend and frontend
	$(call log_ok,install complete)

install-backend: ## pip install -e "backend[dev]" (editable install + dev extras)
	$(call log_info,pip install -e backend[dev])
	$(Q)cd backend && $(PYTHON) -m pip install -e ".[dev]"
	$(call log_ok,backend ready)

install-frontend: ## npm ci in frontend directory
	$(call log_info,npm ci — frontend)
	$(Q)cd frontend && npm ci
	$(call log_ok,frontend node_modules ready)

# =============================================================================
# Docker — build & registry
# =============================================================================

build: ## Build all docker compose images
	$(call log_info,docker compose build)
	$(Q)$(COMPOSE) build
	$(call log_ok,build finished)

build-nc: ## Build without cache (clean, slower)
	$(call log_warn,Building without cache — may take a while)
	$(Q)$(COMPOSE) build --no-cache
	$(call log_ok,build-nc finished)

pull: ## Pull base images for compose services
	$(call log_info,docker compose pull)
	$(Q)$(COMPOSE) pull
	$(call log_ok,pull finished)

# =============================================================================
# Docker — lifecycle
# =============================================================================

up: env-check ## Run stack in foreground (logs in terminal; Ctrl+C stops)
	$(call log_info,Starting stack — foreground attach to compose)
	$(Q)$(COMPOSE) up --build
	$(call log_warn,compose up exited)

up-d: env-check ## Build and run stack in background (detached)
	$(call log_info,Starting stack — detached)
	$(Q)$(COMPOSE) up -d --build
	$(call log_ok,Stack running — make ps | make logs | http://localhost:3000)
	$(Q)$(COMPOSE) ps

down: ## Stop and remove containers (named volumes kept)
	$(call log_info,docker compose down)
	$(Q)$(COMPOSE) down
	$(call log_ok,down complete)

stop: ## Stop containers only (do not remove)
	$(call log_info,docker compose stop)
	$(Q)$(COMPOSE) stop
	$(call log_ok,stop complete)

restart: env-check ## Restart all compose services (no image rebuild)
	$(call log_info,Restarting all services: $(STACK_SERVICES))
	$(Q)$(COMPOSE) restart $(STACK_SERVICES)
	$(call log_ok,restart complete)

restart-%: env-check ## Restart one service, e.g. make restart-backend
	$(call log_info,Restarting service: $*)
	$(Q)$(COMPOSE) restart $*
	$(call log_ok,service $* restarted)

rebuild: env-check ## Full image rebuild and up -d
	$(call log_warn,Full rebuild + up -d — databases keep data on named volumes)
	$(Q)$(COMPOSE) build --no-cache
	$(Q)$(COMPOSE) up -d
	$(call log_ok,rebuild complete)
	$(Q)$(COMPOSE) ps

destroy: ## Remove containers and volumes (DB and data; CONFIRM=YES skips prompt)
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

ps: ## Container status (docker compose ps -a)
	$(call log_info,docker compose ps)
	$(Q)$(COMPOSE) ps -a

status: env-check ## ps + quick backend /health check (if up)
	$(call log_info,Stack status)
	$(Q)$(COMPOSE) ps -a
	$(Q)printf '\n  \033[1mBackend /health\033[0m → '
	$(Q)if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null; then \
		printf '\033[32mOK\033[0m (http://localhost:8000/health)\n'; \
	else \
		printf '\033[33munreachable\033[0m (start with: make up-d)\n'; \
	fi

curl-health: ## GET /health from host (backend on port 8000)
	$(call log_info,curl http://127.0.0.1:8000/health)
	$(Q)curl -sS -f http://127.0.0.1:8000/health | (command -v jq >/dev/null && jq . || cat -)
	$(Q)printf '\n'

logs: ## Tail logs for all services (line count: LOG_TAIL, default 200)
	$(call log_info,Tailing all logs — Ctrl+C to stop — tail=$(LOG_TAIL))
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL)

logs-json: ## Like logs, with Docker timestamps (handy for grep)
	$(call log_info,Tailing all logs with timestamps)
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL) -t

logs-%: ## Logs for one service, e.g. make logs-backend LOG_TAIL=500
	$(call log_info,Tailing logs: $* — tail=$(LOG_TAIL))
	$(Q)$(COMPOSE) logs -f --tail=$(LOG_TAIL) $*

shell-backend: ## Interactive shell in backend container
	$(call log_info,exec backend — shell)
	$(Q)$(COMPOSE) exec backend sh -c 'if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi'

shell-frontend: ## Interactive shell in frontend container
	$(call log_info,exec frontend — shell)
	$(Q)$(COMPOSE) exec frontend sh

psql: ## psql in postgres (user agent, DB agent_db)
	$(call log_info,psql agent_db)
	$(Q)$(COMPOSE) exec postgres psql -U agent -d agent_db

# =============================================================================
# Quality — tests & lint
# =============================================================================

test: test-backend ## Run tests (backend only for now)

test-backend: ## pytest in backend/ (extra args: ARGS='-v -k name')
	$(call log_info,pytest backend)
	$(Q)cd backend && $(PYTHON) -m pytest $(ARGS)
	$(call log_ok,pytest done)

lint: lint-backend lint-frontend ## Run all linters
	$(call log_ok,lint complete)

lint-backend: ## ruff check in backend
	$(call log_info,ruff check)
	$(Q)cd backend && $(PYTHON) -m ruff check app tests
	$(call log_ok,ruff ok)

lint-frontend: ## next lint in frontend
	$(call log_info,npm run lint — frontend)
	$(Q)cd frontend && npm run lint
	$(call log_ok,next lint ok)

format: format-backend ## Format code (backend via ruff for now)

format-backend: ## ruff format in backend
	$(call log_info,ruff format)
	$(Q)cd backend && $(PYTHON) -m ruff format app tests
	$(call log_ok,ruff format done)

ci: lint test ## Like CI: lint then test
	$(call log_ok,ci pipeline finished)

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Remove local Python/Node caches (not docker volumes)
	$(call log_info,Cleaning local caches under backend/ and frontend/)
	$(Q)find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)find backend -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	$(Q)rm -rf frontend/.next frontend/node_modules/.cache
	$(Q)rm -f "$(PROJECT_ROOT).k8s-dotenv.mk"
	$(call log_ok,clean done)

clean-docker: ## docker image prune -f (unused images)
	$(call log_warn,Pruning dangling Docker images)
	$(Q)docker image prune -f
	$(call log_ok,clean-docker done)

# =============================================================================
# Kubernetes — production (DOKS, Docker Hub, cert-manager + Let’s Encrypt)
# =============================================================================
# Typical: TAG=v1.2.3 make k8s-buildx-all && make k8s-apply-full && make k8s-rollout-restart
# On Apple Silicon always set PLATFORM=linux/amd64 for DOKS nodes unless you use arm nodes.

K8S_DIR ?= k8s
K8S_NS ?= ai-agent
# Optional dotenv for k8s image builds (NEXT_PUBLIC_*, TAG, PLATFORM, DOCKER_REGISTRY). Override: K8S_BUILD_ENV=./prod.env
K8S_BUILD_ENV ?= $(PROJECT_ROOT).env
# $(shell) collapses newlines — write a small included makefile instead of $(eval $(shell ...)).
$(shell $(PYTHON) "$(PROJECT_ROOT)scripts/k8s_build_env_from_dotenv.py" "$(K8S_BUILD_ENV)" > "$(PROJECT_ROOT).k8s-dotenv.mk" 2>/dev/null)
-include $(PROJECT_ROOT).k8s-dotenv.mk

DOCKER_REGISTRY ?= issist
IMAGE_BACKEND ?= $(DOCKER_REGISTRY)/logistic-copilot-backend
IMAGE_FRONTEND ?= $(DOCKER_REGISTRY)/logistic-copilot-frontend
TAG ?= latest
PLATFORM ?= linux/amd64
# Root .env usually sets NEXT_PUBLIC_API_URL=http://localhost:* for docker-compose; that is merged above.
# Baking localhost into a prod frontend breaks login (browser calls user's loopback). Force public API unless unset was intentional non-loopback (e.g. staging).
ifeq ($(NEXT_PUBLIC_API_URL),)
NEXT_PUBLIC_API_URL := https://api.logisticopilot.com
else ifneq ($(findstring localhost,$(NEXT_PUBLIC_API_URL)),)
NEXT_PUBLIC_API_URL := https://api.logisticopilot.com
else ifneq ($(findstring 127.0.0.1,$(NEXT_PUBLIC_API_URL)),)
NEXT_PUBLIC_API_URL := https://api.logisticopilot.com
else ifneq ($(findstring [::1],$(NEXT_PUBLIC_API_URL)),)
NEXT_PUBLIC_API_URL := https://api.logisticopilot.com
endif
# Public site key — must match Cloudflare widget; baked in at Next.js build (Dockerfile builder stage).
NEXT_PUBLIC_TURNSTILE_SITE_KEY ?=
# Turnstile widget (see Cloudflare docs: theme, language, size).
NEXT_PUBLIC_TURNSTILE_THEME ?= light
NEXT_PUBLIC_TURNSTILE_LANGUAGE ?= en
NEXT_PUBLIC_TURNSTILE_SIZE ?= flexible
# buildx --provenance=false avoids unknown/unknown in Hub manifest lists for single-platform pushes
K8S_BUILDX_EXTRA ?= --provenance=false
# Path to env file for k8s-secret-from-env (only key=value lines, no export)
K8S_SECRET_ENV ?=
# DigitalOcean: cluster name or ID for doctl kubernetes cluster kubeconfig save
DO_CLUSTER ?=
# Helm release namespaces (common defaults)
HELM_NS_INGRESS ?= ingress-nginx
HELM_NS_CERT_MANAGER ?= cert-manager

k8s-vars: ## Show K8s/image variables (TAG, PLATFORM, K8S_NS, …)
	$(call log_info,Kubernetes / image variables)
	$(Q)printf '  K8S_BUILD_ENV=%s\n' "$(K8S_BUILD_ENV)"
	$(Q)printf '  K8S_DIR=%s K8S_NS=%s\n' "$(K8S_DIR)" "$(K8S_NS)"
	$(Q)printf '  IMAGE_BACKEND=%s:%s\n' "$(IMAGE_BACKEND)" "$(TAG)"
	$(Q)printf '  IMAGE_FRONTEND=%s:%s\n' "$(IMAGE_FRONTEND)" "$(TAG)"
	$(Q)printf '  PLATFORM=%s NEXT_PUBLIC_API_URL=%s\n' "$(PLATFORM)" "$(NEXT_PUBLIC_API_URL)"
	$(Q)if [ -z "$(NEXT_PUBLIC_TURNSTILE_SITE_KEY)" ]; then \
		printf '  NEXT_PUBLIC_TURNSTILE_SITE_KEY=(empty — pass for prod frontend build)\n'; \
	else \
		printf '  NEXT_PUBLIC_TURNSTILE_SITE_KEY=(set)\n'; \
	fi
	$(Q)printf '  DO_CLUSTER=%s K8S_SECRET_ENV=%s\n' "$(DO_CLUSTER)" "$(K8S_SECRET_ENV)"

k8s-context: ## Current kubectl context (check before deploy)
	$(call log_info,kubectl config current-context)
	$(Q)kubectl config current-context

k8s-buildx-backend: ## Build and push backend (linux/amd64 by default)
	$(call log_info,buildx push $(IMAGE_BACKEND):$(TAG))
	$(Q)docker buildx build --platform $(PLATFORM) -t $(IMAGE_BACKEND):$(TAG) \
		$(K8S_BUILDX_EXTRA) "$(PROJECT_ROOT)backend" --push

k8s-buildx-frontend: ## Build and push frontend (NEXT_PUBLIC_* from env; Turnstile site key for prod)
	$(call log_info,buildx push $(IMAGE_FRONTEND):$(TAG))
	$(Q)docker buildx build --platform $(PLATFORM) \
		--build-arg NEXT_PUBLIC_API_URL=$(NEXT_PUBLIC_API_URL) \
		--build-arg NEXT_PUBLIC_TURNSTILE_SITE_KEY=$(NEXT_PUBLIC_TURNSTILE_SITE_KEY) \
		--build-arg NEXT_PUBLIC_TURNSTILE_THEME=$(NEXT_PUBLIC_TURNSTILE_THEME) \
		--build-arg NEXT_PUBLIC_TURNSTILE_LANGUAGE=$(NEXT_PUBLIC_TURNSTILE_LANGUAGE) \
		--build-arg NEXT_PUBLIC_TURNSTILE_SIZE=$(NEXT_PUBLIC_TURNSTILE_SIZE) \
		-t $(IMAGE_FRONTEND):$(TAG) $(K8S_BUILDX_EXTRA) "$(PROJECT_ROOT)frontend" --push

k8s-buildx-all: k8s-buildx-backend k8s-buildx-frontend ## Build and push both images
	$(call log_ok,k8s-buildx-all finished)

k8s-release: k8s-buildx-all ## Alias: full build+push images for TAG

k8s-apply-namespace: ## kubectl apply namespace
	$(call log_info,kubectl apply namespace)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/namespace.yaml"

k8s-apply-secrets: ## kubectl apply Secret from k8s/secrets.yaml
	$(call log_info,kubectl apply secrets)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/secrets.yaml"

k8s-apply-config: ## kubectl apply ConfigMap
	$(call log_info,kubectl apply configmap)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/configmap.yaml"

k8s-apply-databases: ## Qdrant StatefulSet + Service
	$(call log_info,kubectl apply databases)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/databases.yaml"

k8s-apply-app: ## backend + frontend Deployments/Services
	$(call log_info,kubectl apply app)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/app.yaml"

k8s-apply-ingress: ## Ingress (TLS via cert-manager → Let's Encrypt)
	$(call log_info,kubectl apply ingress)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/ingress.yaml"

k8s-apply-letsencrypt-issuer: ## ClusterIssuer letsencrypt-prod (after helm cert-manager; fix email in YAML)
	$(call log_info,kubectl apply ClusterIssuer)
	$(Q)kubectl apply -f "$(PROJECT_ROOT)$(K8S_DIR)/letsencrypt-clusterissuer.yaml"

k8s-apply-base: k8s-apply-namespace k8s-apply-config k8s-apply-databases k8s-apply-app k8s-apply-ingress ## Everything except Secret and ClusterIssuer

k8s-apply-full: k8s-apply-namespace k8s-apply-secrets k8s-apply-config k8s-apply-databases k8s-apply-app k8s-apply-ingress ## Full stack from YAML (including secrets.yaml)

k8s-apply-dry-run: ## client-side dry-run of all manifests in k8s/
	$(call log_info,kubectl apply --dry-run=client)
	$(Q)kubectl apply --dry-run=client -f "$(PROJECT_ROOT)$(K8S_DIR)/"

k8s-secret-from-env: ## Secret from file: K8S_SECRET_ENV=./prod.secrets.env make k8s-secret-from-env
	$(call log_info,kubectl create secret agent-secrets from env file)
	$(Q)if [ -z "$(K8S_SECRET_ENV)" ] || [ ! -f "$(K8S_SECRET_ENV)" ]; then \
		printf '\033[31mSet K8S_SECRET_ENV to an existing env file\033[0m\n' >&2; \
		exit 1; \
	fi
	$(Q)kubectl create secret generic agent-secrets --from-env-file="$(K8S_SECRET_ENV)" -n "$(K8S_NS)" --dry-run=client -o yaml | kubectl apply -f -
	$(call log_ok,secret agent-secrets applied)

k8s-rollout-restart-backend: ## rollout restart backend (pick up new image for TAG/latest)
	$(call log_info,kubectl rollout restart deployment/backend)
	$(Q)kubectl rollout restart deployment/backend -n "$(K8S_NS)"
	$(Q)kubectl rollout status deployment/backend -n "$(K8S_NS)" --timeout=180s

k8s-rollout-restart-frontend: ## rollout restart frontend
	$(call log_info,kubectl rollout restart deployment/frontend)
	$(Q)kubectl rollout restart deployment/frontend -n "$(K8S_NS)"
	$(Q)kubectl rollout status deployment/frontend -n "$(K8S_NS)" --timeout=180s

k8s-rollout-restart: k8s-rollout-restart-backend k8s-rollout-restart-frontend ## Restart both deployments

k8s-status: ## pods, svc, ingress in namespace
	$(call log_info,kubectl get — $(K8S_NS))
	$(Q)kubectl get pods,svc,ingress -n "$(K8S_NS)" -o wide

k8s-get: ## All resources in namespace
	$(Q)kubectl get all -n "$(K8S_NS)"

k8s-logs-backend: ## Tail backend logs (LOG_TAIL=200)
	$(Q)kubectl logs deployment/backend -n "$(K8S_NS)" -f --tail=$(LOG_TAIL)

k8s-logs-frontend: ## Tail frontend logs
	$(Q)kubectl logs deployment/frontend -n "$(K8S_NS)" -f --tail=$(LOG_TAIL)

k8s-describe-backend: ## describe deployment + latest pod events
	$(Q)kubectl describe deployment/backend -n "$(K8S_NS)"
	$(Q)kubectl get pods -n "$(K8S_NS)" -l app=backend -o wide

k8s-events: ## Namespace events (debug Scheduling / Pull / TLS)
	$(Q)kubectl get events -n "$(K8S_NS)" --sort-by='.lastTimestamp' | tail -40

k8s-certificates: ## cert-manager: Certificate / Order / Challenge in namespace
	$(call log_info,cert-manager resources in $(K8S_NS))
	$(Q)-kubectl get certificate,order,challenge -n "$(K8S_NS)" 2>/dev/null || true
	$(Q)printf '\n  TLS secret (Ingress): kubectl describe secret agent-tls -n %s\n' "$(K8S_NS)"

k8s-port-forward-backend: ## Local http://127.0.0.1:8000 → backend in cluster
	$(call log_info,kubectl port-forward svc/backend 8000:8000 — $(K8S_NS))
	$(Q)kubectl port-forward -n "$(K8S_NS)" svc/backend 8000:8000

k8s-do-kubeconfig: ## DO: save kubeconfig (needs doctl; DO_CLUSTER=cluster name)
	$(call log_info,doctl kubernetes cluster kubeconfig save)
	$(Q)if [ -z "$(DO_CLUSTER)" ]; then \
		printf '\033[31mSet DO_CLUSTER to your DOKS cluster name or ID\033[0m\n' >&2; \
		exit 1; \
	fi
	$(Q)doctl kubernetes cluster kubeconfig save "$(DO_CLUSTER)"

k8s-helm-cert-manager: ## Install/upgrade cert-manager (helm; namespace $(HELM_NS_CERT_MANAGER))
	$(call log_info,helm upgrade — cert-manager)
	$(Q)helm repo add jetstack https://charts.jetstack.io --force-update 2>/dev/null || true
	$(Q)helm repo update
	$(Q)helm upgrade --install cert-manager jetstack/cert-manager \
		--namespace "$(HELM_NS_CERT_MANAGER)" --create-namespace \
		--set crds.enabled=true

k8s-helm-ingress-nginx: ## Install ingress-nginx (helm; namespace $(HELM_NS_INGRESS))
	$(call log_info,helm upgrade — ingress-nginx)
	$(Q)helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update 2>/dev/null || true
	$(Q)helm repo update
	$(Q)helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
		--namespace "$(HELM_NS_INGRESS)" --create-namespace

k8s-bootstrap-infra: k8s-helm-ingress-nginx k8s-helm-cert-manager k8s-apply-letsencrypt-issuer ## Once per cluster: ingress-nginx + cert-manager + ClusterIssuer (email in YAML!)
	$(call log_ok,k8s-bootstrap-infra — check TLS: make k8s-certificates)

k8s-ship-images: k8s-buildx-all k8s-rollout-restart ## Push TAG images and restart deployments (manifests already applied)
	$(call log_ok,k8s-ship-images done)
