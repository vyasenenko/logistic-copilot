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
│   ├── databases.yaml      # PostgreSQL + Qdrant StatefulSets
│   ├── app.yaml            # Backend + Frontend Deployments
│   └── ingress.yaml        # Nginx Ingress + TLS
├── docker-compose.yaml     # Локальная разработка
├── .env.example
└── README.md
```

## Деплой на DigitalOcean (Kubernetes)

```bash
# 1. Создать кластер DOKS в DigitalOcean

# 2. Создать Container Registry
doctl registry create ai-agent

# 3. Собрать и запушить образы
docker build -t registry.digitalocean.com/ai-agent/backend:latest ./backend
docker build -t registry.digitalocean.com/ai-agent/frontend:latest ./frontend
docker push registry.digitalocean.com/ai-agent/backend:latest
docker push registry.digitalocean.com/ai-agent/frontend:latest

# 4. Применить K8s манифесты
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml      # ← заполнить реальными ключами!
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/databases.yaml
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/ingress.yaml

# 5. Установить Nginx Ingress + cert-manager
helm install ingress-nginx ingress-nginx/ingress-nginx -n ai-agent
helm install cert-manager jetstack/cert-manager --set installCRDs=true
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
