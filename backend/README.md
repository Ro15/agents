# Backend (FastAPI) - Production-grade POC

Upgrades delivered:
- Plugin governance with validation and discovery endpoints.
- Dataset registry + soft delete + health check.
- Safer NL?SQL pipeline (intent gate, repair loop, SQL guard, defaults).
- Audit trail for chat/insights runs.

## Environment variables
- `DATABASE_URL` (e.g., `postgresql://user:pass@localhost:5432/dbname`)
- `OPENAI_API_KEY` (optional; if missing, chat falls back to safe failures)
- `LLM_MODEL` (default `gpt-3.5-turbo`)
- `LLM_PROVIDER` (default `openai`)
- `OPENAI_API_BASE` (override for compatible providers)

## Run locally
```bash
# from repo root
podman compose -f podman-compose.yml up -d db
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Adding a plugin
Place configs under `plugins/<id>/` with `schema.yaml`, `metrics.yaml`, `questions.yaml`, `policy.yaml`, `insights.yaml`. Invalid plugins are logged and skipped from discovery; fix validation errors to load.

## Working with multiple datasets
- Upload CSVs with `POST /upload/sales` and header `x-plugin: <plugin_id>`; each upload creates/updates a dataset and stores `dataset_id`.
- Queries must specify `dataset_id`; the backend injects `dataset_id = :dataset_id` into every SQL to prevent cross-dataset leakage.
- List datasets per plugin: `GET /datasets?plugin_id=retail`
- Get one dataset: `GET /datasets/{dataset_id}`
- Soft delete: `DELETE /datasets/{dataset_id}`

## Key endpoints (new/updated)
- `GET /plugins` – lightweight catalog (excludes invalid plugins)
- `GET /plugins/{id}` – full plugin detail
- `GET /plugins/{id}/questions` – question packs
- `POST /upload/sales` – upload CSV, bind to plugin, create/update dataset record
- `GET /datasets` – list datasets (filter by `plugin_id`)
- `GET /datasets/{dataset_id}` – dataset meta
- `DELETE /datasets/{dataset_id}` – soft delete
- `POST /chat` – intent-gated NL?SQL with audit logging
- `POST /insights/run` / `GET /insights/latest`
- `GET /health` – includes plugin count

## Curl examples
```bash
# 1) list plugins
curl -s http://localhost:8000/plugins

# 2) upload CSV for a plugin (binds dataset)
curl -X POST -H "x-plugin: retail" -F "file=@sample.csv" http://localhost:8000/upload/sales

# 3) list datasets (for retail)
curl "http://localhost:8000/datasets?plugin_id=retail"

# 4) chat query (dataset_id optional)
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query":"total revenue last 7 days","plugin":"retail","dataset_id":"<UUID>"}'

# 5) unsafe query blocked (shows explanation)
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query":"delete from sales","plugin":"retail","dataset_id":"<UUID>"}'

# 6) (optional) fetch audit log via DB: SELECT * FROM ai_audit_log LIMIT 5;
```

## Tests
```bash
cd backend
pytest
```

## Plugin contract tests
- Validate every plugin under `/plugins` with sample CSVs under `/sample_data/<plugin>/`.
- Ensure TEST_DATABASE_URL (or DATABASE_URL) points to your Postgres (Podman DB works).
```bash
podman compose -f podman-compose.yml up -d db
export TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/yourdb
cd backend
pytest -q app/tests/test_plugin_contracts.py
```
Failing messages include plugin id, file, and missing references for quick fixes.

## Caching
- Env flags:
  - `CACHE_ENABLED` (default true)
  - `LLM_SQL_CACHE_TTL_SECONDS` (default 21600)
  - `DB_RESULT_CACHE_TTL_SECONDS` (default 120)
- In-memory TTL cache is used by default; Redis optional is not required.
- Cache keys include plugin_id + dataset_id + dataset_version to avoid cross-dataset leakage.

## Chat sessions and memory (new)
- `POST /conversations` - create a chat session
- `GET /conversations` - list sessions (supports `search`, `include_archived`, `limit`)
- `GET /conversations/{thread_id}` - get one session with messages
- `PUT /conversations/{thread_id}` - rename, pin/unpin, archive/unarchive
- `GET /conversations/{thread_id}/memory` - inspect learned session memory
- `DELETE /conversations/{thread_id}` - delete a session

### Flow
- Frontend creates a session and stores `thread_id`.
- Each follow-up call to `POST /chat` includes `conversation_id` (`thread_id`).
- Backend saves user and assistant messages in `conversation_messages`.
- Backend updates `conversation_memory` (session summary + preference hints).
- New follow-up prompts include that memory context so answers stay consistent.

## Accuracy upgrades (implemented)

The chat pipeline now includes:
- Follow-up resolver: short follow-up questions are expanded with recent user/assistant context.
- Clarification gate: ambiguous questions return a clarification prompt instead of guessing.
- Business glossary grounding: plugin metrics/column meanings are injected into SQL prompt.
- Dynamic schema focus: for dynamic datasets, only most relevant columns are emphasized per question.
- SQL verifier pass: optional second LLM pass checks SQL-question alignment and can propose safe fixes.
- Feedback learning: recent corrected SQL feedback is reused as prompt guidance for similar questions.
- Result sanity checks: detects suspicious numeric outputs and lowers confidence when needed.
- Stronger conversation history: assistant history includes summary + SQL used for better follow-ups.
- Golden intent test set: `app/tests/golden_questions.json` + `test_golden_questions.py`.

### New env flags
- `CHAT_SQL_MAX_ATTEMPTS` (default `3`) - generation/execution retry count.
- `DYNAMIC_PROMPT_MAX_COLUMNS` (default `20`) - relevant dynamic columns to include in prompt.
- `LLM_SQL_VERIFIER_ENABLED` (default `true`) - enable second-pass SQL verifier.- `CHAT_AUTO_CREATE_SESSION` (default `true`) - auto-create a conversation when `/chat` is called without `conversation_id`.

### New endpoint
- `GET /plugins/{plugin_id}/glossary` - returns business glossary terms used for prompt grounding.




## RAG system (implemented)

### New capabilities
- Knowledge-base ingestion and chunk retrieval (business docs, SOPs, glossary notes).
- Schema RAG retrieval before SQL generation.
- Example RAG retrieval from learned query examples and corrected feedback.
- Query rewrite step for follow-up/elliptical questions.
- Context reranking + token-budget context packing.
- Grounded answers with citations (`grounding.citations`) in `/chat` response.
- Post-execution learning loop: successful Q->SQL pairs are auto-added as RAG examples.
- Human review queue for low-confidence/failure cases.
- Lightweight eval framework (`/rag/eval`) using golden question set.

### New RAG endpoints
- `POST /rag/kb` - ingest a knowledge document.
- `GET /rag/kb` - list ingested knowledge documents.
- `GET /rag/kb/search` - retrieve top knowledge chunks for a question.
- `GET /rag/examples` - list/retrieve learned examples (optionally by question similarity).
- `GET /rag/review` - list human review queue items.
- `POST /rag/review/{review_id}/resolve` - resolve a review item and optionally promote approved SQL to examples.
- `GET /rag/eval` - run lightweight evaluation on golden questions.

### New RAG env flags
- `RAG_QUERY_REWRITE_ENABLED` (default `true`) - enable rewrite step.
- `RAG_TOP_K` (default `6`) - top retrieved items used for context.
- `RAG_CONTEXT_MAX_CHARS` (default `4200`) - packed context size budget.
- `RAG_CHUNK_SIZE` (default `900`) - KB chunk size.
- `RAG_CHUNK_OVERLAP` (default `120`) - KB chunk overlap.
- `RAG_URL_FETCH_TIMEOUT_SECONDS` (default `10`) - timeout when ingesting KB from `source_uri`.

## Agent mode (implemented)

### What is added
- User profile memory per plugin (`response_style`, KPI preferences, chart preferences).
- Goal planning with multi-step tool execution (schema, KB, examples, SQL, verification, execution, summary).
- Approval checkpoints for risky SQL before execution.
- Automation records for scheduled/recurring analyst goals.
- Agent quality metrics endpoint (accuracy proxy, clarification rate, correction rate, handoff rate).

### New agent endpoints
- `GET /agent/profile`
- `PUT /agent/profile`
- `POST /agent/profile/infer`
- `POST /agent/goals`
- `GET /agent/goals`
- `GET /agent/goals/{goal_id}`
- `POST /agent/goals/{goal_id}/run`
- `POST /agent/goals/{goal_id}/approve`
- `POST /agent/automations`
- `GET /agent/automations`
- `PUT /agent/automations/{automation_id}`
- `DELETE /agent/automations/{automation_id}`
- `POST /agent/automations/{automation_id}/run-now`
- `POST /agent/automations/run-due`
- `GET /agent/metrics`

### Optional agent env flag
- `AGENT_LLM_PLANNER_ENABLED` (default `true`) - use LLM to generate plan steps, fallback to heuristic planner on error.
