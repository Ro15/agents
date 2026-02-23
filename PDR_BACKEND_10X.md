# Agent-X Backend 10x PDR
### Product Development Requirements — "Better Than ChatGPT for Data Analytics"
**Version 1.0 | February 2026**

---

## Executive Summary

ChatGPT gives generic answers from pretrained knowledge. Agent-X sits on top of *your actual data* — but currently it operates like a smarter chatbot bolted onto SQL. This PDR defines 6 initiatives (21 tasks) that transform the backend into a **true analytical co-pilot**: one that streams answers, explains causality, forecasts trends, detects anomalies with root causes, enforces data governance, and continuously gets smarter from every interaction.

**What makes this 10x better than ChatGPT:**
| Dimension | ChatGPT | Agent-X Today | Agent-X After PDR |
|-----------|---------|--------------|-------------------|
| Data access | Generic knowledge | Your data via SQL | Your data, live, federated |
| Response latency | Streams tokens | Blocks until done | Streams tokens + partial rows |
| SQL correctness | Often wrong | 3-attempt self-correction | Cost-aware routing + semantic cache |
| Analytics depth | Explains numbers | Returns numbers | Root cause, forecast, cohort |
| Governance | None | None | PII-aware, lineage, audit log |
| Autonomy | Single turn | Goals with steps | Multi-step decomposition + self-improving |
| Trust | No evidence | SQL trace | EXPLAIN plans + confidence intervals |

---

## Current State (Baseline)

**What works:**
- NL → SQL → narrative pipeline with 3-attempt self-correction
- 12-connector data ingestion (Postgres, Snowflake, BigQuery, S3, Sheets, etc.)
- RAG grounding with schema + business glossary + example retrieval
- Conversational memory (16-message window, thread-based)
- Automated insights (threshold + comparison + z-score anomaly)
- WebSocket push for insight notifications
- Agent goals with 7-step toolchain

**Critical gaps (why we lose to ChatGPT):**
1. **No streaming** — users wait 8–15 seconds for a full response
2. **No root cause** — tells you revenue dropped, not *why*
3. **No forecasting** — can't say "at this rate, you'll hit X in 30 days"
4. **No cross-dataset federation** — can't join two uploaded CSVs
5. **No PII protection** — will happily return credit card numbers
6. **No self-improvement** — every query starts from scratch
7. **No query cost guard** — expensive queries run unchecked
8. **No schema drift** — data changes silently break queries

---

## Initiative 1 — Streaming Intelligence Layer
*Make the platform feel instant and dramatically more trustworthy*

### Task 1.1 — Server-Sent Events (SSE) Streaming

**Problem:** The `/chat` endpoint returns nothing for 8–15 seconds then dumps the full answer. Users abandon the session.

**Solution:** Convert `/chat` to an SSE endpoint that streams in phases:

```
Phase 1 (0.1s):  {"event": "thinking",   "data": {"status": "Planning query..."}}
Phase 2 (0.5s):  {"event": "sql_ready",  "data": {"sql": "SELECT ...", "cost_estimate": "~12ms"}}
Phase 3 (1.2s):  {"event": "rows",       "data": {"rows": [...first 50...], "total": 1240}}
Phase 4 (1.8s):  {"event": "narrative",  "data": {"token": "Revenue"}}
Phase 5 (1.9s):  {"event": "narrative",  "data": {"token": " dropped"}}
...
Phase N:         {"event": "done",       "data": {"confidence": "high", "assumptions": [...]}}
```

**Backend changes:**
- New endpoint: `GET /chat/stream` (SSE via `StreamingResponse`)
- Wrap `chat_endpoint` logic into an async generator
- Each pipeline stage emits an event before awaiting next
- SQL execution streams partial rows as they arrive (server-side cursor)
- LLM narrative streamed token-by-token via `stream=True` on OpenAI / Gemini

**Acceptance criteria:**
- [ ] Time-to-first-byte < 300ms for all queries
- [ ] First row chunk delivered < 2s for any dataset
- [ ] Narrative streams token-by-token (not word-by-word)
- [ ] Frontend displays typed-out narrative in chat bubbles
- [ ] Old `/chat` endpoint preserved for backward compatibility

---

### Task 1.2 — Semantic Query Cache with Smart Invalidation

**Problem:** Identical questions rerun the same LLM + SQL pipeline. Cache exists but is hash-based (wording change = cache miss).

**Solution:** Two-tier cache:
1. **Exact hash cache** (existing): TTL 3600s, plugin+dataset+normalized_question
2. **Semantic cache** (new): Embed the question with a cheap embedding model, find nearest neighbor (cosine > 0.94 threshold) → return cached answer with "Similar to your previous question about X"

**Backend changes:**
- New file: `backend/app/semantic_cache.py`
  - `SemanticCache` class using `pgvector` extension (already in Postgres)
  - `store(question, answer, embedding)` — store with dataset_id + plugin
  - `find_similar(question, dataset_id, threshold=0.94)` → `CacheHit | None`
- Embed questions with a tiny local model (`sentence-transformers/all-MiniLM-L6-v2`) or OpenAI `text-embedding-3-small` (cheap)
- Cache invalidation: when dataset is re-uploaded or deleted, wipe all cache entries for that `dataset_id`
- Add `cache_hit: bool` and `cache_similarity: float` to chat response

**New DB table:**
```sql
CREATE TABLE query_semantic_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id VARCHAR NOT NULL,
    dataset_id VARCHAR,
    question_text TEXT NOT NULL,
    question_embedding vector(384) NOT NULL,
    answer_json JSONB NOT NULL,
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ
);
CREATE INDEX ON query_semantic_cache USING ivfflat (question_embedding vector_cosine_ops);
```

**Acceptance criteria:**
- [ ] Semantically similar questions (>94% cosine similarity) return cached result with < 50ms latency
- [ ] Cache shows `cache_hit: true, cache_similarity: 0.97` in response
- [ ] Dataset re-upload invalidates all semantic cache entries for that dataset
- [ ] Cache hit rate logged and visible in `/usage` page
- [ ] Cache can be manually cleared per plugin via `DELETE /cache/{plugin_id}`

---

### Task 1.3 — Multi-Model LLM Router

**Problem:** Simple questions ("what are my top 5 products?") use the same expensive model as complex multi-table analytics. No fallback when model fails.

**Solution:** Classify query complexity → route to appropriate model → fallback chain on failure.

```
Complexity → Model
simple (lookup, count) → gemini-flash / gpt-4o-mini   (~0.1¢)
medium (joins, window)  → gemini-pro / gpt-4o          (~0.5¢)
complex (multi-table, subqueries, CASE WHEN) → gemini-ultra / claude-3-5-sonnet (~3¢)

Fallback chain: primary → secondary → HTTP direct → cached partial
```

**Backend changes in `llm_service.py`:**
- `classify_complexity(question, schema)` → `"simple" | "medium" | "complex"`
  - Heuristics: number of tables referenced, aggregation keywords, subquery words, schema size
- `LLMRouter` class:
  - `route(complexity)` → picks model config
  - `call_with_fallback(prompt, complexity)` → tries primary, catches errors, tries fallback
- Add `circuit_breaker` per model (if 3 consecutive failures → skip that model for 60s)
- Log model used + tokens + cost for every request

**Acceptance criteria:**
- [ ] Simple queries routed to cheap model 90% of the time
- [ ] Complex queries never sent to cheap model
- [ ] If primary model times out or errors, fallback used within 2s
- [ ] Circuit breaker prevents cascading failures
- [ ] Per-query model cost logged, visible in Usage page

---

### Task 1.4 — Query Cost Estimator + EXPLAIN Guard

**Problem:** Users can accidentally ask queries that scan millions of rows. No warning before execution.

**Solution:** Before executing any SQL, run `EXPLAIN (FORMAT JSON)` and:
1. Parse estimated rows + estimated cost from plan
2. If estimated rows > 500K → warn user and ask to confirm
3. If query has no LIMIT and result > 1K rows → auto-add LIMIT 5000 with notice
4. Show "Query cost: ~240ms, scanning ~18K rows" in response

**Backend changes in `routes_core.py`:**
- `_estimate_query_cost(sql, db)` → `QueryCostEstimate(rows: int, cost_units: float, plan: dict)`
- Before `conn.execute(sql)` → run EXPLAIN, check thresholds
- Add `query_cost_estimate` to chat response JSON
- Add `RISKY_QUERY_ROW_THRESHOLD = 500_000` config constant
- If risky: return `{"requires_confirmation": true, "cost_estimate": {...}}` without executing
- Frontend: show "This query will scan ~500K rows. Continue?" dialog

**Acceptance criteria:**
- [ ] Every SQL response includes `query_cost_estimate.estimated_rows`
- [ ] Queries with >500K estimated rows require confirmation
- [ ] No-LIMIT queries auto-clamped to 5000 rows with user notice
- [ ] EXPLAIN fails gracefully (connector doesn't support it → skip check)

---

## Initiative 2 — Advanced Analytics Engine
*What no chatbot can do — genuine analytical intelligence on your data*

### Task 2.1 — Root Cause Analysis (RCA) Engine

**Problem:** Users see "revenue dropped 23% this week" but can't dig further without manual follow-up questions.

**Solution:** After any insight or chat response with a numeric change > 10%, automatically offer RCA. RCA uses a chain of pre-built analytical queries to find the biggest contributor.

**RCA Algorithm:**
```
1. Identify the metric that changed (e.g., revenue)
2. For each dimension (product, region, channel, day-of-week):
   a. Run: SELECT dim, SUM(metric) FROM t WHERE period=current GROUP BY dim
   b. Run: SELECT dim, SUM(metric) FROM t WHERE period=previous GROUP BY dim
   c. Compute dimension-level delta
3. Find top-3 contributors by absolute delta
4. For top contributor: drill one level deeper (sub-dimension)
5. Return structured RCA report
```

**New file: `backend/app/rca_engine.py`**
```python
class RCAEngine:
    def analyze(self, metric_col, value_col, date_col, table, db) -> RCAReport:
        dimensions = self._discover_categorical_dims(table, db)
        contributions = []
        for dim in dimensions[:5]:  # cap at 5 dims
            delta = self._compute_dim_delta(dim, metric_col, value_col, date_col, table, db)
            contributions.append(delta)
        return RCAReport(
            top_contributors=sorted(contributions, key=abs)[:3],
            explanation=self._generate_explanation(contributions),
            follow_up_questions=[...]
        )
```

**Integration:** After any answer with `answer_type="chart"` or `answer_type="table"` that has a time dimension and shows a change, auto-trigger `rca_engine.analyze()` and append `rca_summary` to chat response.

**Acceptance criteria:**
- [ ] RCA triggered automatically when metric shows >10% change
- [ ] Top 3 contributing dimensions identified with % share
- [ ] RCA adds < 1s to response time (runs in parallel with narrative)
- [ ] RCA section visible in chat with "Why did this happen?" header
- [ ] Suggested drill-down follow-up questions auto-populated from RCA findings

---

### Task 2.2 — Forecasting Engine

**Problem:** Users ask "will I hit my Q2 target?" — current system can only show historical data.

**Solution:** Detect time-series questions and respond with a 30/60/90-day forecast.

**Approach:**
- No heavy ML library — use `statsmodels` (already common in Python analytics)
- Methods available: Holt-Winters exponential smoothing, simple linear regression, moving average
- Method selected based on data: Holt-Winters for seasonal data, linear regression for trending, MA for noisy

**New file: `backend/app/forecast_engine.py`**
```python
class ForecastEngine:
    def forecast(self, dates: list, values: list, horizon: int = 30) -> ForecastResult:
        series = pd.Series(values, index=pd.to_datetime(dates))
        method = self._select_method(series)  # seasonal, trending, noisy
        model = self._fit(series, method)
        predictions = model.predict(horizon)
        ci = model.confidence_intervals(0.95)
        return ForecastResult(
            predictions=predictions,
            confidence_interval_lower=ci[0],
            confidence_interval_upper=ci[1],
            method=method,
            r_squared=self._goodness_of_fit(series, model),
        )
```

**Intent detection:** Add `"forecast"` to intent classifier in `nl_to_sql.py`:
- Triggers: "will", "predict", "forecast", "next month", "by Q2", "going forward", "trend"

**Integration:** When intent is `"forecast"`:
1. First run historical SQL query
2. Feed results to `ForecastEngine.forecast()`
3. Return `answer_type: "forecast"` with historical + predicted rows + confidence bands

**Acceptance criteria:**
- [ ] Forecast triggered for questions containing forecast-intent keywords
- [ ] 3 methods available (Holt-Winters, linear, MA) with auto-selection
- [ ] Response includes confidence intervals (95%)
- [ ] Forecast chart shows dashed line for predicted + shaded confidence band
- [ ] `r_squared` and `method_used` included in response for transparency
- [ ] Graceful fallback to "insufficient data (need 14+ data points)" if series too short

---

### Task 2.3 — Cross-Dataset Federation

**Problem:** Users upload Sales CSV + Products CSV but can't join them. Every query is single-table.

**Solution:** Auto-detect joinable columns across datasets (same plugin, matching column names/types) and make joins available in NL→SQL.

**New file: `backend/app/federation_service.py`**
```python
class FederationService:
    def discover_joins(self, plugin_id: str, db: Session) -> list[JoinHint]:
        """Find columns that appear in multiple datasets with matching types."""
        datasets = db.query(Dataset).filter_by(plugin_id=plugin_id).all()
        profiles = {d.dataset_id: d.column_profiles for d in datasets}
        return self._find_matching_columns(profiles)

    def build_federation_schema(self, dataset_ids: list, db: Session) -> str:
        """Return schema context with JOIN hints included."""
        hints = self.discover_joins(...)
        return format_schema_with_join_hints(hints)
```

**Schema context enhancement:** When RAG grounding assembles schema, include:
```
-- JOIN HINTS (auto-detected):
-- dataset_sales.product_id ↔ dataset_products.product_id (VARCHAR, 98% overlap)
-- You can JOIN these tables to answer cross-dataset questions.
```

**SQL Guard update:** `sql_guard.py` must allow cross-dataset joins when `allow_cross_dataset=True` is set for a plugin.

**Acceptance criteria:**
- [ ] Joinable columns auto-detected after upload via column name + type matching
- [ ] JOIN hints included in schema context for RAG grounding
- [ ] LLM generates valid cross-dataset JOIN SQL
- [ ] SQL guard allows permitted cross-dataset joins
- [ ] `/api/datasets/federation-hints?plugin_id=X` endpoint returns detected joins
- [ ] Works for 2-way joins; 3-way joins as stretch goal

---

### Task 2.4 — Cohort & Retention Analysis

**Problem:** "What's my 30-day retention?" is impossible to answer today.

**Solution:** Pre-built cohort analysis templates that activate when retention/cohort/funnel keywords detected.

**New file: `backend/app/cohort_engine.py`**
```python
class CohortEngine:
    TEMPLATES = {
        "retention": """
            WITH cohorts AS (
                SELECT user_id,
                       DATE_TRUNC('month', MIN({date_col})) AS cohort_month
                FROM {table}
                GROUP BY user_id
            ),
            activity AS (
                SELECT t.{user_col},
                       DATE_TRUNC('month', t.{date_col}) AS activity_month,
                       c.cohort_month,
                       DATE_PART('month', AGE(DATE_TRUNC('month', t.{date_col}), c.cohort_month)) AS period_number
                FROM {table} t
                JOIN cohorts c ON t.{user_col} = c.user_id
            )
            SELECT cohort_month, period_number, COUNT(DISTINCT {user_col}) AS users
            FROM activity
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
        "funnel": "...",
        "ltv": "...",
        "churn": "..."
    }

    def build_query(self, template, columns: ColumnMap) -> str:
        return self.TEMPLATES[template].format(**columns)
```

**Column map detection:** Use `ColumnProfile` data to find likely user_id, date, event columns.

**Acceptance criteria:**
- [ ] Retention analysis triggered by keywords: "retention", "cohort", "churn", "returning users"
- [ ] Returns pivot table: cohort_month × period with retention %
- [ ] Frontend renders cohort heatmap (new `CohortHeatmap` component)
- [ ] Funnel analysis triggered by: "funnel", "conversion", "drop-off"
- [ ] LTV analysis triggered by: "lifetime value", "LTV", "customer value"

---

## Initiative 3 — Data Quality & Governance
*Enterprise trust that ChatGPT will never have*

### Task 3.1 — Schema Drift Detection

**Problem:** A connector syncs nightly, a column gets renamed or dropped, and every query silently breaks. No alert, no diagnosis.

**Solution:** After every connector sync or file upload, compare schema fingerprint to previous version. Alert on: removed columns, type changes, renamed columns, new nullability.

**New file: `backend/app/schema_drift.py`**
```python
class SchemaDriftDetector:
    def compare(self, old_schema: list[ColumnProfile], new_schema: list[ColumnProfile]) -> DriftReport:
        removed = {c.column_name for c in old_schema} - {c.column_name for c in new_schema}
        added   = {c.column_name for c in new_schema} - {c.column_name for c in old_schema}
        type_changes = [...]
        null_pct_spike = [c for c in new_schema if self._null_spike(c, old_schema)]
        return DriftReport(removed=removed, added=added, type_changes=type_changes, null_spikes=null_pct_spike)
```

**Integration points:**
- `ingestion_service.py`: After ingestion, call `SchemaDriftDetector.compare()` and store `DriftReport` in DB
- `routes_core.py`: Include `schema_drift_warnings` in `/upload` response
- WebSocket: Broadcast `{"type": "schema_drift", "severity": "high", "details": {...}}` if critical columns removed
- `/api/datasets/{id}/drift-history` endpoint for audit trail

**New DB table:**
```sql
CREATE TABLE schema_drift_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ DEFAULT now(),
    drift_type VARCHAR NOT NULL,  -- 'column_removed', 'type_changed', 'null_spike'
    column_name VARCHAR,
    old_value TEXT,
    new_value TEXT,
    severity VARCHAR DEFAULT 'medium'
);
```

**Acceptance criteria:**
- [ ] Drift detection runs on every upload and connector sync
- [ ] Critical drifts (column removed, type change) broadcast via WebSocket as toast
- [ ] Drift history viewable in Data Sources page (per dataset)
- [ ] Queries that reference drifted columns show a warning badge in chat
- [ ] Semantic cache entries for drifted columns are invalidated

---

### Task 3.2 — PII Auto-Classification

**Problem:** A user uploads a CSV with emails, phone numbers, SSNs. The system returns them verbatim in chat responses. This is a compliance disaster.

**Solution:** Auto-classify columns as PII at upload time. Mask or redact PII in chat responses. Never store PII in cache.

**New file: `backend/app/pii_classifier.py`**
```python
PII_PATTERNS = {
    "email":   r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    "phone":   r"(\+?\d[\d\s\-().]{7,}\d)",
    "ssn":     r"\b\d{3}[-–]\d{2}[-–]\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "ip_address": r"\b\d{1,3}(\.\d{1,3}){3}\b",
    "name_heuristic": "..."  # column name contains: name, fname, lname, customer, user
}

class PIIClassifier:
    def classify_columns(self, df: pd.DataFrame) -> dict[str, PIILabel]:
        results = {}
        for col in df.columns:
            results[col] = self._check_column(df[col], col)
        return results  # {"email": PIILabel(type="email", confidence=0.99, action="mask")}

    def mask_results(self, rows: list[dict], pii_cols: dict) -> list[dict]:
        """Replace PII values with masked representation."""
        for row in rows:
            for col, label in pii_cols.items():
                if col in row and label.action == "mask":
                    row[col] = self._mask(row[col], label.type)
        return rows
```

**Integration:**
- Run classifier during `ingestion_service.py` after schema detection
- Store PII classification in `ColumnProfile.pii_type` (new column)
- In `routes_core.py`: before returning SQL results, run `mask_results()` on PII columns
- Add `pii_columns_masked: list[str]` to chat response so UI can show a notice
- Never cache results that contain unmasked PII columns

**Migration:**
```sql
ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_type VARCHAR;
ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_confidence FLOAT;
ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_action VARCHAR DEFAULT 'none';
```

**Acceptance criteria:**
- [ ] Email, phone, SSN, credit card auto-detected at upload with >95% precision
- [ ] PII columns masked in all chat responses (shown as `j***@example.com`)
- [ ] `pii_columns_masked` list included in every chat response
- [ ] UI shows "2 PII columns masked for privacy" notice below results
- [ ] PII classification visible in Data Catalog page
- [ ] Admin can override masking per column via API

---

### Task 3.3 — Audit Log Engine

**Problem:** No record of who queried what data, when, and what SQL was executed. Impossible to comply with SOC 2 or GDPR.

**Solution:** Immutable audit log for every query execution, data export, and schema change.

**New DB table (append-only):**
```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR NOT NULL,  -- 'query', 'export', 'upload', 'delete', 'schema_change'
    plugin_id VARCHAR,
    dataset_id VARCHAR,
    sql_executed TEXT,
    rows_returned INTEGER,
    user_session_id VARCHAR,
    ip_address VARCHAR,
    duration_ms INTEGER,
    pii_columns_accessed TEXT[],
    created_at TIMESTAMPTZ DEFAULT now()
);
-- Never UPDATE or DELETE from this table
```

**New file: `backend/app/audit_service.py`**
```python
class AuditService:
    def log(self, db, event_type, **kwargs) -> None:
        entry = AuditLog(event_type=event_type, **kwargs)
        db.add(entry)
        db.commit()  # immediate commit, not part of request transaction
```

**Integration:**
- `routes_core.py`: Log every SQL execution with `event_type="query"`
- `ingestion_service.py`: Log every upload with `event_type="upload"`
- Add `GET /audit-log?plugin_id=X&start=Y&end=Z` endpoint (admin only)
- Export audit log as CSV via `GET /audit-log/export`

**Acceptance criteria:**
- [ ] Every SQL execution logged within the request lifecycle
- [ ] Every file upload/delete logged
- [ ] Audit log is append-only (no UPDATE/DELETE endpoints exist)
- [ ] `GET /audit-log` endpoint with date range + plugin filters
- [ ] Audit log includes PII columns accessed per query
- [ ] Retention: 90 days default, configurable via env var `AUDIT_RETENTION_DAYS`

---

## Initiative 4 — Autonomous Multi-Step Reasoning Agent
*True autonomy — not just question-answering*

### Task 4.1 — Chain-of-Thought Query Decomposition

**Problem:** "Compare sales by region and show me which regions are underperforming against target" requires 3+ queries but the agent runs one query and stops.

**Solution:** Add a decomposition step before SQL generation that breaks complex questions into sub-questions, executes them in parallel, then synthesizes.

**New file: `backend/app/query_decomposer.py`**
```python
class QueryDecomposer:
    def decompose(self, question: str, schema: SchemaContext, llm: LLMService) -> list[SubQuery]:
        """Ask LLM: does this need multiple queries? If so, list them."""
        prompt = f"""
        Question: {question}
        Schema: {schema.summary}

        Does this question require multiple SQL queries to answer?
        If yes, list each sub-question. Each must be answerable with one SQL query.
        Return JSON: {{"needs_decomposition": bool, "sub_questions": [...]}}
        """
        result = llm.generate_text(prompt)
        if not result.needs_decomposition:
            return [SubQuery(question=question, depends_on=[])]
        return [SubQuery(q=sq, depends_on=...) for sq in result.sub_questions]

    def synthesize(self, sub_results: list[SubResult], original_question: str, llm) -> str:
        """Merge multiple query results into one coherent answer."""
```

**DAG execution:**
- Build dependency graph from `depends_on` links
- Execute independent sub-queries in parallel (`asyncio.gather`)
- Pass results of dependency queries as context to dependent queries
- Synthesize final answer from all sub-results

**Integration:** In `routes_core.py` `chat_endpoint`, before SQL generation:
1. Call `QueryDecomposer.decompose(question)`
2. If `needs_decomposition=True` → execute DAG, synthesize, return
3. Else → existing single-query path

**Acceptance criteria:**
- [ ] Questions requiring 2+ queries auto-decomposed
- [ ] Sub-queries executed in parallel (not sequentially)
- [ ] Final synthesis is coherent narrative covering all sub-results
- [ ] `decomposed: true, sub_questions: [...]` in response metadata
- [ ] Total time ≤ single longest sub-query + 30% overhead
- [ ] Falls back to single-query path if decomposition fails

---

### Task 4.2 — Prompt Self-Optimization (Learning Loop)

**Problem:** Every query starts from the same static prompts. Failed queries → corrected SQL never improves future prompts. The system doesn't get smarter.

**Solution:** After every feedback submission (thumbs up/down + correction), analyze what went wrong and update prompt examples.

**New file: `backend/app/prompt_optimizer.py`**
```python
class PromptOptimizer:
    def ingest_feedback(self, original_sql, corrected_sql, question, plugin_id, db):
        """Analyze the diff between original and corrected SQL."""
        diff_type = self._classify_diff(original_sql, corrected_sql)
        # diff_type: 'wrong_column', 'wrong_aggregation', 'missing_filter', 'wrong_join', 'wrong_date'

        # Store as a RAG example with HIGH priority
        example = RAGExample(
            question=question,
            sql=corrected_sql,
            plugin_id=plugin_id,
            source="user_correction",
            priority=10,  # higher than auto-generated examples
            diff_type=diff_type
        )
        self._store_example(example, db)

        # If same diff_type seen 5+ times → update system prompt segment
        if self._diff_frequency(diff_type, plugin_id, db) >= 5:
            self._generate_prompt_rule(diff_type, plugin_id, llm, db)
```

**Dynamic prompt rules:** Stored in a new table, injected into system prompt:
```sql
CREATE TABLE prompt_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id VARCHAR NOT NULL,
    rule_text TEXT NOT NULL,           -- "When user asks about 'last month', use DATE_TRUNC('month', NOW() - INTERVAL '1 month')"
    trigger_pattern VARCHAR,           -- regex or keyword
    learned_from_diff_type VARCHAR,
    applied_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Acceptance criteria:**
- [ ] Every feedback submission analyzed and stored as RAG example with high priority
- [ ] After 5 corrections of same type → a prompt rule auto-generated
- [ ] Prompt rules injected into LLM system prompt for subsequent queries
- [ ] `prompt_rules_applied: ["Rule #3: date handling"]` visible in chat response debug
- [ ] Correction-derived examples outrank auto-generated examples in RAG retrieval
- [ ] A/B test endpoint: `GET /prompt-optimizer/test?plugin_id=X` runs golden question suite

---

### Task 4.3 — Autonomous Report Builder

**Problem:** Users manually build dashboards widget by widget. There's no "just build me a sales report" flow.

**Solution:** Given a goal, the agent automatically generates a complete dashboard with multiple charts, KPIs, and narrative.

**New endpoint:** `POST /agent/generate-report`
```json
{
  "goal": "Give me a complete sales performance report for last quarter",
  "plugin_id": "restaurant",
  "dataset_id": "ds_xxx",
  "output_type": "dashboard"  // or "pdf" | "email"
}
```

**Agent logic:**
1. Decompose goal into standard report sections (KPIs, trends, breakdowns, anomalies)
2. For each section: generate SQL → execute → chart recommendation
3. Auto-create a `CustomDashboard` with recommended widgets
4. Generate executive summary narrative covering all sections
5. Return dashboard_id + shareable link

**Acceptance criteria:**
- [ ] Report generated from natural language goal in < 30s
- [ ] Report contains: 3+ KPI cards, 2+ trend charts, 1+ breakdown table, executive summary
- [ ] Generated dashboard immediately visible in Dashboard Builder
- [ ] `POST /agent/generate-report` returns `{dashboard_id, share_url, sections: [...]}`
- [ ] Email delivery option: sends rendered HTML report to provided email

---

## Initiative 5 — Real-Time & Performance
*Make it fast enough to be a live analytics companion*

### Task 5.1 — Redis Result Cache + Smart Invalidation

**Problem:** Current SQL cache is in-memory (lost on restart), single-process, and doesn't support TTL-based invalidation. The semantic cache uses Postgres which is slower than a dedicated cache.

**Solution:** Add Redis as a fast cache layer for SQL results.

**New file: `backend/app/result_cache.py`**
```python
class ResultCache:
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)

    async def get(self, key: str) -> CachedResult | None:
        data = await self.redis.get(key)
        return CachedResult(**json.loads(data)) if data else None

    async def set(self, key: str, result: CachedResult, ttl: int = 3600):
        await self.redis.setex(key, ttl, json.dumps(result.dict()))

    async def invalidate_dataset(self, dataset_id: str):
        """Delete all cache keys tagged with this dataset_id."""
        keys = await self.redis.keys(f"result:*:{dataset_id}:*")
        if keys:
            await self.redis.delete(*keys)
```

**Cache key structure:** `result:{plugin_id}:{dataset_id}:{sql_hash}`

**TTL strategy:**
- Real-time connectors (connector sync < 1h): TTL = 300s (5 min)
- Uploaded static files: TTL = 86400s (24h)
- Aggregate queries (SUM, COUNT): TTL = 1800s (30 min)
- Raw row queries: TTL = 60s

**podman-compose.yml update:** Add Redis service alongside Postgres.

**Acceptance criteria:**
- [ ] Redis container added to `podman-compose.yml`
- [ ] Repeated identical queries served from Redis in < 20ms
- [ ] Cache invalidated on dataset upload/delete
- [ ] Cache bypass via `?no_cache=true` query param
- [ ] Cache hit rate metric logged and visible in Usage page
- [ ] Graceful degradation: if Redis down, falls back to in-memory cache

---

### Task 5.2 — Background Job Queue (Celery + Redis)

**Problem:** Heavy operations (insight generation, RCA, report building) block the FastAPI event loop. Long-running uploads time out.

**Solution:** Move heavy operations to async Celery tasks. FastAPI returns a `job_id` immediately; client polls or receives WebSocket notification on completion.

**New file: `backend/app/celery_app.py`**
```python
from celery import Celery

celery_app = Celery(
    "agent_x",
    broker="redis://redis:6379/1",
    backend="redis://redis:6379/2",
    include=["app.tasks.insights", "app.tasks.reports", "app.tasks.rca"]
)

celery_app.conf.task_routes = {
    "app.tasks.insights.*": {"queue": "insights"},
    "app.tasks.reports.*": {"queue": "reports"},
    "app.tasks.rca.*": {"queue": "rca"},
}
```

**Tasks to offload:**
- `tasks/insights.py`: `generate_insights_task.delay(plugin_id, dataset_id)`
- `tasks/reports.py`: `generate_report_task.delay(goal, plugin_id, dataset_id)`
- `tasks/rca.py`: `run_rca_task.delay(metric, table, plugin_id)`

**API contract:**
```
POST /insights/run → {"job_id": "abc123", "status": "queued"}
GET  /jobs/abc123  → {"status": "running", "progress": 0.4}
WS   /ws           → {"type": "job_complete", "job_id": "abc123", "result": {...}}
```

**Acceptance criteria:**
- [ ] All heavy operations return `job_id` within 200ms
- [ ] Job progress updates sent via existing WebSocket manager
- [ ] Celery workers added to `podman-compose.yml`
- [ ] Job status persisted in `jobs` table (already exists in `models.py`)
- [ ] Dead jobs (> 10 min) auto-marked as failed with error message
- [ ] Retry logic: failed jobs auto-retried once after 30s

---

## Initiative 6 — Observability & Robustness
*Know exactly what's happening and never go down*

### Task 6.1 — Structured Observability

**Problem:** Logs are JSON but there's no way to trace a full request lifecycle, measure LLM latency per step, or find the slowest queries.

**Solution:** Add OpenTelemetry (OTEL) tracing + structured metrics. No external dependency needed — export to stdout for now, easy to route to Grafana/Tempo later.

**New file: `backend/app/telemetry.py`**
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

tracer = trace.get_tracer("agent_x")

# Usage in routes_core.py:
with tracer.start_as_current_span("chat_request") as span:
    span.set_attribute("plugin_id", plugin_id)
    span.set_attribute("question_length", len(question))
    with tracer.start_as_current_span("llm_sql_generation"):
        sql = generate_sql_with_llm(...)
        span.set_attribute("tokens_used", result.token_count)
    with tracer.start_as_current_span("sql_execution"):
        rows = execute_sql(sql)
        span.set_attribute("rows_returned", len(rows))
```

**Metrics to track per request:**
- `llm_latency_ms` (per model)
- `sql_execution_ms`
- `rag_retrieval_ms`
- `total_request_ms`
- `tokens_input`, `tokens_output`
- `cache_hit` (bool)
- `correction_attempt_count`
- `model_used`

**New endpoint:** `GET /metrics` — Prometheus-format metrics for scraping

**Acceptance criteria:**
- [ ] Every chat request emits a complete trace with spans for each pipeline step
- [ ] P50/P95/P99 latency per step tracked and queryable
- [ ] `GET /metrics` returns Prometheus-format counters and histograms
- [ ] LLM token usage and estimated cost logged per request
- [ ] Slow query threshold: log WARNING if any step > 5s
- [ ] Error rate per endpoint tracked (4xx vs 5xx)

---

### Task 6.2 — Circuit Breaker + Health Escalation

**Problem:** If OpenAI or Gemini is down, all requests fail with unhelpful errors. No fallback, no degraded mode.

**Solution:** Circuit breaker per external dependency (LLM, DB, Redis). Graceful degradation: if LLM is down, return cached answer if available.

**New file: `backend/app/circuit_breaker.py`**
```python
class CircuitBreaker:
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject fast
    HALF_OPEN = "half_open" # Testing recovery

    def __init__(self, name, failure_threshold=3, recovery_timeout=60):
        self.state = self.CLOSED
        self.failures = 0
        ...

    def call(self, fn, *args, **kwargs):
        if self.state == self.OPEN:
            raise CircuitOpenError(f"{self.name} is unavailable")
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
```

**Enhanced `/health` endpoint:**
```json
{
  "status": "degraded",
  "components": {
    "database": {"status": "ok", "latency_ms": 12},
    "llm_primary": {"status": "open", "failures": 3, "recovery_in": "45s"},
    "llm_fallback": {"status": "ok", "latency_ms": 234},
    "redis": {"status": "ok"},
    "semantic_cache": {"status": "ok"}
  }
}
```

**Acceptance criteria:**
- [ ] Circuit breaker per: primary LLM, fallback LLM, database, Redis
- [ ] After 3 failures in 60s → circuit opens (fast-fail for 60s)
- [ ] After recovery timeout → half-open (test one request)
- [ ] `/health` returns component-level status (not just "ok")
- [ ] When LLM circuit open → return semantic cache hit if available, else graceful error
- [ ] Circuit state logged and visible in Usage page

---

## Summary: Priority Matrix

| Task | Initiative | Impact | Effort | Priority |
|------|-----------|--------|--------|----------|
| 1.1 SSE Streaming | Intelligence | ★★★★★ | Medium | **P0** |
| 2.1 Root Cause Analysis | Analytics | ★★★★★ | Medium | **P0** |
| 3.2 PII Classification | Governance | ★★★★★ | Low | **P0** |
| 1.2 Semantic Cache | Intelligence | ★★★★☆ | Low | **P1** |
| 2.2 Forecasting | Analytics | ★★★★☆ | Medium | **P1** |
| 4.1 Query Decomposition | Agent | ★★★★☆ | Medium | **P1** |
| 5.1 Redis Cache | Performance | ★★★★☆ | Low | **P1** |
| 2.3 Cross-Dataset Federation | Analytics | ★★★★☆ | Medium | **P1** |
| 3.1 Schema Drift Detection | Governance | ★★★☆☆ | Low | **P2** |
| 1.3 LLM Router | Intelligence | ★★★☆☆ | Low | **P2** |
| 4.2 Prompt Self-Optimization | Agent | ★★★☆☆ | Medium | **P2** |
| 5.2 Job Queue (Celery) | Performance | ★★★☆☆ | Medium | **P2** |
| 1.4 EXPLAIN Guard | Intelligence | ★★★☆☆ | Low | **P2** |
| 2.4 Cohort Analysis | Analytics | ★★★☆☆ | Medium | **P2** |
| 4.3 Report Builder | Agent | ★★★☆☆ | High | **P3** |
| 3.3 Audit Log | Governance | ★★☆☆☆ | Low | **P3** |
| 6.1 Observability | Robustness | ★★☆☆☆ | Low | **P3** |
| 6.2 Circuit Breaker | Robustness | ★★☆☆☆ | Low | **P3** |

---

## Implementation Order (Recommended Sprints)

### Sprint 1 — "Feel Instant" (Week 1–2)
1. Task 1.1: SSE Streaming
2. Task 5.1: Redis Cache
3. Task 1.4: EXPLAIN Guard

### Sprint 2 — "Know Why" (Week 3–4)
4. Task 2.1: RCA Engine
5. Task 3.2: PII Classifier
6. Task 3.1: Schema Drift

### Sprint 3 — "Predict & Join" (Week 5–6)
7. Task 2.2: Forecasting Engine
8. Task 2.3: Cross-Dataset Federation
9. Task 1.2: Semantic Cache

### Sprint 4 — "Smarter Agent" (Week 7–8)
10. Task 4.1: Query Decomposition
11. Task 1.3: LLM Router
12. Task 4.2: Prompt Self-Optimization

### Sprint 5 — "Enterprise Ready" (Week 9–10)
13. Task 5.2: Job Queue (Celery)
14. Task 2.4: Cohort Analysis
15. Task 3.3: Audit Log
16. Task 6.1: Observability
17. Task 6.2: Circuit Breaker

---

## Success Metrics

| Metric | Baseline | Target After PDR |
|--------|----------|-----------------|
| Time-to-first-byte | 8–15s | < 300ms |
| Cache hit rate | ~0% | > 60% |
| SQL first-attempt accuracy | ~70% | > 90% |
| User questions requiring follow-up | ~40% | < 15% |
| PII data exposure incidents | Unknown | 0 |
| P95 full response latency | 15s | < 4s |
| Cost per query (LLM tokens) | ~3¢ | < 0.8¢ |
| Cross-dataset questions answerable | 0% | > 80% |
| Forecast questions answerable | 0% | > 90% |
| System uptime (LLM circuit breaker) | ~92% | > 99.5% |
