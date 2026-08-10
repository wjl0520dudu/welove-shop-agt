# ai-service AGENTS.md

This file extends the root `AGENTS.md` for the `ai-service` directory. When instructions conflict, this file wins for work under `ai-service/`.

## Service Overview

`ai-service` is a FastAPI AI service called by `services/chat-service`, listening on port `8000` by default. It provides:

- **Assistant Graph**: request analysis, routing, complex task orchestration, subtask execution, and response synthesis.
- **Shopping**: product recommendation, comparison, detail retrieval, user context, and multimodal search.
- **Knowledge / RAG**: knowledge base parsing, chunking, vector retrieval, reranking, Q&A, and web search fallback.
- **Context**: Router/Chitchat shared visible context built from chat-service's persisted rolling summary plus recent messages; task-scoped product cards, user preferences and knowledge entities.
- **Infrastructure**: LLM, DashScope, Milvus, pgvector, PostgreSQL, Java API, and LangGraph runtime.

## Startup

`main.py` stays at `ai-service/` root. Do **not** move it into `app/` or change the `main:app` entry point.

```powershell
cd ai-service
uvicorn main:app
```

The `SelectorEventLoop` setting ensures psycopg async works on Windows. On startup the app loads config, registers middleware, initializes the LangGraph runtime (degrading to in-memory when PostgreSQL is unavailable), and registers routes.

## Architecture

Source code lives under `app/` with a layered structure:

- **`app/api/`** — HTTP layer only: routes, request/response schemas, SSE encoding, CORS, trace IDs, and error mapping. Must not directly implement Milvus queries, database transactions, or business logic.
- **`app/application/assistant/`** — Assistant main graph, routing, orchestration (DAG), context resolution, and cross-domain coordination.
- **`app/domain/shopping/`** — Shopping business logic: agent, capability dispatch, retrieval, multimodal search, ranking, personalization, cards, and tools.
- **`app/domain/knowledge/`** — Knowledge business logic: agent, document pipeline, query planning, and RAG tools.
- **`app/infrastructure/`** — External technology implementations: config, persistence, LLM, retrieval, vector stores, and clients. Must not reverse-depend on `app/api/`.
- **`app/legacy/`** — Historical modules (cart, chains) not yet integrated into the main Assistant design. Do **not** add new business logic here.
- **`app/prompts/`** — Centralized prompts for chitchat, knowledge Q&A, shopping, and Assistant Agents.

`evals/`, `scripts/`, and `tests/` stay at the `ai-service/` root.

## Skills-Driven Domain Agents

`ShoppingAgent` and `KnowledgeAgent` use `deepagents==0.7.1` by default. Their detailed workflows belong in `skills/`, not in a growing system prompt:

```text
skills/
├─ shopping-agent/
│  ├─ discover-products/
│  ├─ compare-products/
│  ├─ inspect-product/
│  ├─ use-shopping-profile/
│  └─ multimodal-consistency/
└─ knowledge-agent/
   ├─ answer-with-evidence/
   └─ answer-safety-question/
```

- New Agent skills go under `skills/<agent-name>/<skill-name>/SKILL.md` and require YAML `name` and `description` frontmatter.
- Keep a Skill focused on one capability. It must describe allowed inputs, ordered use of real tools, error/empty behavior, factual boundaries and final-response boundaries.
- Existing domain tool contracts remain authoritative. Do not invent product facts, product IDs, sources or internal state inside a Skill.
- Shopping `scripts/` are optional deterministic helpers, run only through `run_shopping_skill_script` and the fixed whitelist. Never add or expose a generic shell, `execute`, filesystem-write or subagent tool.
- DeepAgent permissions are deliberately read-only to the agent's own Skill path. Preserve the blocked built-in surface (`execute`, writes, deletes, `task`, generic search and todos).
- Router resolves cross-turn references and product bindings. Skills consume the resolved current task; Shopping/Knowledge must not receive or reread full conversation history.
- If a tool, Skill path, middleware or runtime switch changes, update the matching unit tests and `.env.example` documentation.

## Context, State and SSE

- `chat-service` owns the full durable visible transcript in `chat_svc.message`, the rolling summary and its coverage watermark. `ai-service` does not persist summary text directly during a user turn.
- `resolve_context` is the only shared preparation point for Router and Chitchat. It injects the persisted summary once and appends recent visible messages.
- `AssistantState.messages` is graph working state. It is refreshed from chat-service's visible history per request and is not a substitute for database conversation truth.
- Shopping and Knowledge should receive only the Router-resolved current question, bound entities/product IDs, allowed image scope, explicit dependency artifacts and relevant soft preferences.
- Keep `start`, `route`, `token`, `product_cards`, `orchestrator_plan`, `subtask_result`, `final`, `error` and `done` SSE semantics stable. Do not emit Agent tool calls, Candidate Judge JSON or internal model chunks as visible user tokens.
- Complex DAG nodes may execute concurrently, but visible token release follows Planner order. Do not add a final summary model merely to concatenate answers unless the public contract explicitly changes.

## Import Rules

New and modified code must use `app.*` absolute imports:

```python
from app.domain.shopping.agent import ShoppingAgent
from app.infrastructure.persistence.runtime import init_runtime
```

Do **not** recreate old top-level packages (`shopping/`, `rag/`, `core/`, `prompts/`, etc.) or use old import paths.

## External Dependencies

Key services (all addresses from config / environment variables):

- **PostgreSQL**: LangGraph checkpoint/store, business data, pgvector.
- **Milvus**: Knowledge and Product vector collections.
- **DashScope**: text embedding, rerank, multimodal embedding, VL rerank.
- **Java API**: product, user, favorites, orders, and related business interfaces.
- **Bocha MCP**: KnowledgeAgent web search fallback.
- **LangSmith**: optional tracing.

Preserve existing degradation behavior when services are unavailable: PostgreSQL down → in-memory runtime; LLM not configured → stable error response; Java API down → existing error or empty-result semantics.

## API Contracts

Do **not** arbitrarily modify:

- Assistant request/response fields and `image_url` semantics.
- SSE event names, event order, and `done` termination semantics.
- Product card fields.
- RAG `sources`, `documents`, and `knowledge_context` fields.
- Stable error codes and HTTP status codes.

When modifying product cards, conversation history, user preferences, or chat persistence, also check `services/chat-service` and frontend DTOs.

## Verification

```powershell
cd ai-service
python -m compileall -q .
python -m pytest -q
```

Key targeted tests:

```powershell
python -m pytest -q `
  tests/test_api_contract.py `
  tests/test_context_resolver.py `
  tests/test_assistant_graph.py `
  tests/test_shopping_capabilities.py `
  tests/test_shopping_ranking_and_cards.py `
  tests/test_multimodal_retrieval_v2.py
```

Post-startup:

```powershell
curl.exe http://127.0.0.1:8000/health/live
curl.exe http://127.0.0.1:8000/health
```

If tests fail due to unavailable external services (Milvus, DashScope, etc.), document this as an environment condition. Do **not** alter degradation logic just to make tests pass.

## Pre-Modification Checklist

- Determine which layer the change belongs to.
- Prefer modifying the owner module over adding branching in the route layer.
- Check whether `services/chat-service` product cards, SSE events, or data contracts are affected.
- Check for reverse dependencies (`api → infrastructure` or other prohibited directions).
- New code uses `app.*` imports only.
- After modification, run `compileall` and targeted tests for the affected domain.
