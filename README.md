# AI Agent

Универсальный ИИ-агент с архитектурой ReAct (Reason + Act) — один агент с набором инструментов, долговременной памятью и потоковым чат-интерфейсом.

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   Next.js + Tailwind                         │
│              SSE streaming, Markdown render                  │
└──────────────────────┬───────────────────────────────────────┘
                       │ SSE / REST
┌──────────────────────▼───────────────────────────────────────┐
│                        Backend                               │
│                   FastAPI (async)                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              LangGraph ReAct Agent                     │  │
│  │                                                        │  │
│  │   User → [agent_node] → LLM думает → tool_calls?      │  │
│  │                │              │                        │  │
│  │           нет tools      есть tools                    │  │
│  │                │              │                        │  │
│  │              END      [tools_node] → выполняет         │  │
│  │                              │                        │  │
│  │                        обратно в agent_node (цикл)     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Tools: web_search, http_request, calculate,                 │
│         current_datetime, save_to_memory, search_memory      │
└──────────┬─────────────────────┬─────────────────────────────┘
           │                     │
    ┌──────▼──────┐     ┌───────▼───────┐
    │  PostgreSQL │     │    Qdrant     │
    │  (история)  │     │  (RAG память) │
    └─────────────┘     └───────────────┘
```

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| LLM | Claude Sonnet 4.5 (основной) + GPT-4o-mini (fallback) |
| Agent Framework | LangGraph (Python) |
| Backend | FastAPI, async, SSE streaming |
| Memory (vectors) | Qdrant |
| Memory (structured) | PostgreSQL + SQLAlchemy |
| Frontend | Next.js 15, React 19, Tailwind CSS |
| Observability | LangSmith |
| Deploy | Docker + Kubernetes |

## Быстрый старт (локальная разработка)

### Предварительные требования

- Docker & Docker Compose
- API ключи: Anthropic и/или OpenAI

### Запуск

```bash
# 1. Клонировать и перейти в папку
cd Agent

# 2. Создать .env из примера
cp .env.example .env
# Заполнить .env реальными ключами

# 3. Запустить всё
docker compose up --build

# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
# Qdrant:   http://localhost:6333/dashboard
```

## Структура проекта

```
Agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # Ядро агента
│   │   │   ├── graph.py    # LangGraph ReAct цикл
│   │   │   ├── llm.py      # Провайдеры LLM
│   │   │   ├── prompts.py  # Системный промпт
│   │   │   └── state.py    # Состояние графа
│   │   ├── api/            # REST API
│   │   │   ├── chat.py     # POST /api/chat (SSE streaming)
│   │   │   ├── conversations.py
│   │   │   └── health.py
│   │   ├── memory/         # Памяти
│   │   │   ├── database.py # PostgreSQL (история)
│   │   │   └── vector_store.py # Qdrant (RAG)
│   │   ├── tools/          # Инструменты агента
│   │   │   ├── builtin.py  # web_search, calculate, ...
│   │   │   ├── memory_tools.py
│   │   │   └── registry.py # Реестр всех tools
│   │   ├── config.py       # Настройки
│   │   ├── schemas.py      # Pydantic модели
│   │   └── main.py         # Точка входа FastAPI
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router
│   │   └── components/     # Chat, Sidebar
│   ├── Dockerfile
│   └── package.json
├── k8s/                    # Kubernetes манифесты
│   ├── namespace.yaml
│   ├── secrets.yaml
│   ├── configmap.yaml
│   ├── databases.yaml      # Qdrant StatefulSet (Postgres = external / managed DB)
│   ├── app.yaml            # Backend + Frontend Deployments
│   └── ingress.yaml        # Nginx Ingress + TLS
├── docker-compose.yaml     # Локальная разработка
├── .env.example
└── README.md
```

## Деплой на DigitalOcean (Kubernetes)

PostgreSQL в кластере **не** поднимается: managed Postgres и параметры подключения задаются в `k8s/configmap.yaml` / `k8s/secrets.yaml`. Для DO Managed DB включите `POSTGRES_SSL=true` в ConfigMap (и при необходимости разрешите исходящий трафик с нод кластера к БД в панели DO).

Образы по умолчанию — **Docker Hub** `issist/logistic-copilot-backend` и `issist/logistic-copilot-frontend` (тег в `k8s/app.yaml`). Перед `apply` заполните плейсхолдеры в ConfigMap (Spaces, Azure, TMS) и все секреты в `k8s/secrets.yaml` из вашего `.env`.

```bash
# 1. Кластер DOKS + kubectl context

# 2. Собрать и запушить образы (подставьте свой тег)
docker build -t issist/logistic-copilot-backend:TAG ./backend
docker build -t issist/logistic-copilot-frontend:TAG ./frontend
docker push issist/logistic-copilot-backend:TAG
docker push issist/logistic-copilot-frontend:TAG
# Обновите image: в k8s/app.yaml на тот же TAG (или используйте :latest).

# 3. Применить манифесты
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/databases.yaml
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/ingress.yaml

# 4. Ingress + cert-manager + ClusterIssuer (email в letsencrypt-clusterissuer.yaml)
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true
kubectl apply -f k8s/letsencrypt-clusterissuer.yaml
```

## Добавление новых инструментов

```python
# backend/app/tools/builtin.py
@tool
async def my_new_tool(param: str) -> str:
    """Description of what this tool does — the LLM reads this!"""
    # ...implementation...
    return result

# backend/app/tools/registry.py — добавить в get_all_tools()
```

## Масштабирование до Multi-Agent

Когда один агент упрётся в потолок — легко масштабировать:

1. Создать специализированных агентов (coder, researcher, reviewer)
2. Добавить Orchestrator-агента, который раздаёт задачи
3. LangGraph поддерживает sub-graphs для этого из коробки
