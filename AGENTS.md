# AGENTS.md

This file defines repository-level guidance for `welove-shop-agt`. More specific `AGENTS.md` files extend it; the deepest applicable file wins when instructions conflict.

## Project Map

WeLoveShop is a Java microservice shopping system with a Python AI orchestration service and two frontend applications.

- `gateway`: Spring Cloud Gateway, port `8080`.
- `common`: shared Java result, exception, security, DB, web and storage modules.
- `services/user-service`: login, JWT, profile, addresses, favorites, browsing history and isolated test-login accounts.
- `services/product-service`: categories, products, SKUs, images, reviews, FAQ, product search and recommendation logs.
- `services/trade-service`: cart, orders and payment simulation.
- `services/chat-service`: conversations, messages, chat/image SSE, uploads, knowledge documents, QA/Agent logs, per-conversation turn locks and rolling-summary persistence.
- `admin-bff`: admin authentication and aggregation through Feign clients.
- `ai-service`: FastAPI + LangGraph; Router, Planner/DAG, Shopping/Knowledge DeepAgents, RAG, multimodal retrieval and LangSmith tracing.
- `web/welove-shop`: uni-app + Vue 3 user-facing H5.
- `web/admin-web`: React + Vite admin console.
- `infra`: local Docker Compose for PostgreSQL, Redis, Milvus, Nacos and optional RocketMQ/MySQL.
- `deploy`: production images, Compose files and environment templates.

## System Boundaries

Main client traffic goes through the Gateway:

- `/api/user/**` -> `user-service`
- `/api/product/**` -> `product-service`
- `/api/trade/**` -> `trade-service`
- `/api/chat/**` -> `chat-service`
- `/api/admin/**` -> `admin-bff`

`chat-service` calls `ai-service` through `AI_SERVICE_URL` (default `http://127.0.0.1:8000/api`). Browser clients must use the chat-service Gateway APIs rather than call AI Service directly. In production, Nginx terminates HTTPS, serves both frontends and proxies `/api/**` to Gateway.

PostgreSQL schemas are `user_svc`, `product_svc`, `trade_svc`, `chat_svc` and `admin_svc`. New business writes belong to the owning Java service and its schema. MySQL is historical migration infrastructure, not the active source of truth.

## Current AI Architecture

The `AssistantGraph` has this ownership model:

1. `resolve_context` creates one visible context from persisted rolling summary plus recent user/assistant messages, persisted product-card artifacts and business memory.
2. The structured Router LLM resolves references, bound products, image scope and `shopping` / `knowledge` / `chitchat` / `unknown` / `complex`. Router is a graph node, not a DeepAgent.
3. Simple requests go to the appropriate domain node. Shopping and Knowledge are DeepAgents; Chitchat and Unknown use their dedicated expression paths.
4. Complex requests go to Planner only after Router marks them complex. Planner emits a bounded DAG (at most five tasks); sibling tasks may run concurrently but their visible SSE tokens are published in Planner order.
5. `format_response` preserves the established response, product-card and SSE contracts.

Shopping and Knowledge are Skills-driven by default (`deepagents==0.7.1`). A new domain capability should normally add or revise a focused `ai-service/skills/<agent-name>/<skill-name>/SKILL.md` and its explicit tool contract. Do not turn a Skill workflow back into a long hard-coded system prompt or add unbounded generic agent tools.

DeepAgents must stay confined to their allowed surface:

- Skill filesystem access is read-only and restricted to the agent's own virtual skill path.
- Generic shell execution, file writes/deletes, generic filesystem search, subagents and planning tools are blocked.
- Shopping deterministic scripts run only through the fixed whitelist runner; never expose a generic shell tool.
- Router owns cross-turn reference resolution. Shopping/Knowledge subagents must not inspect full conversation history or infer product IDs from arbitrary historical text.

## Context, State and Streaming

- `chat_svc.message` is the complete, durable user-visible transcript. Do not overwrite it with a summary.
- `conversation_context` holds a durable rolling summary and coverage watermark. Summary generation happens asynchronously after assistant persistence and must not delay the current SSE response.
- `state["messages"]` is LangGraph working state, not the business source of truth. The runtime is refreshed from chat-service visible history per turn.
- Router and Chitchat share the same summary + recent visible messages. Shopping and Knowledge receive only current resolved task context, Router bindings, allowed image scope, dependency artifacts and relevant soft preferences.
- Treat SSE as a three-service contract: `ai-service` emits semantic events, `chat-service` persists/forwards them, and `web/welove-shop` renders them. Preserve event names, ordering, token single-delivery, `final`/`done`, product-card and truncated/stop behavior.
- `chat-service` permits one visible turn per conversation. Preserve `clientRequestId`/`turnId` idempotency and Redis lock release semantics when touching stream code.

## Backend Conventions

- Keep data ownership boundaries intact. Java services own business facts and writes; AI may retrieve and express facts but must not bypass domain APIs to mutate carts, orders or user data.
- Use `common-core` envelopes and exception types. Preserve the local layers: `controller`, `service`, `service.impl`, `mapper`, `entity`, `dto`, `vo`, `feign`, `config`.
- Use service-local Flyway migrations for active schema changes. Never edit an already-applied migration; add the next versioned migration.
- Keep cross-service Java calls behind Feign clients. Do not bypass `UserContext` or security interceptors for authenticated APIs.
- Chat, product-card, image and conversation changes require inspection of both `services/chat-service` and `ai-service`; frontend DTO/rendering must also be checked when their payload changes.

## Frontend Conventions

- Keep `admin-web` and `welove-shop` separate. Calls go through Gateway paths and existing API modules, never raw requests scattered through page components.
- `web/welove-shop/src/pages/chat/chat.vue`, `src/store/chat.js` and `src/utils/sse.js` are sensitive integrations. Preserve background stream continuation, stop/retry states, request IDs, product cards and assistant Markdown rendering.
- Do not parse product cards from LLM text. Consume structured SSE events and preserve their fields.
- Do not edit generated `dist` files or `node_modules`.

## Configuration and Secrets

- Use `ai-service/.env.example` as the local AI configuration template. Never commit `.env` or real API keys.
- Keep `CONVERSATION_SUMMARY_*` settings aligned between `ai-service` and `chat-service`.
- LangSmith tracing is optional. Enable it only with `LANGSMITH_TRACING=true` and a valid key; retain masked input/output defaults unless debugging explicitly requires otherwise.
- Production secrets live in `deploy`'s separate secrets env file, never in Nacos or frontend runtime config.

## Verification

Use the fastest verification that covers the modified ownership boundary:

- Java: `mvn -pl <module> -am test`, or `mvn -pl <module> -am package -DskipTests` when tests are impractical.
- AI service: from `ai-service`, run `python -m compileall -q .` and focused `pytest` tests. Run a real service smoke test only when required dependencies are available.
- User frontend: from `web/welove-shop`, run `npm run build:h5`.
- Admin frontend: from `web/admin-web`, run `npm run build`.
- Documentation-only changes: run `git diff --check` and verify links/commands against current files.

If PostgreSQL, Redis, Nacos, Milvus, DashScope, Bocha or other runtime dependencies are unavailable, state that condition instead of weakening production behavior merely to make a test pass.

