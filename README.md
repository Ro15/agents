# Restaurant Data Analyst Chat

This project is a proof-of-concept for a chat application that allows users to ask questions about restaurant sales data in plain English.

## Tech Stack

- **Backend:** Python FastAPI
- **Database:** PostgreSQL
- **Containerization:** Podman (podman compose)

## Getting Started

### Prerequisites

- Podman with `podman compose` (or `podman-compose`) available
- An OpenAI API key (for Phase 4)

### Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-name>
    ```

2.  **Create an environment file:**
    Create a `.env` file in the root directory:
    ```bash
    cat > .env << EOF
    POSTGRES_USER=user
    POSTGRES_PASSWORD=password
    POSTGRES_DB=restaurant_db
    DATABASE_URL=postgresql://user:password@db:5432/restaurant_db
    OPENAI_API_KEY=your_openai_api_key_here
    LLM_MODEL=gpt-3.5-turbo
    LLM_TEMPERATURE=0
    LLM_MAX_TOKENS=500
    EOF
    ```
    
    **Environment Variables:**
    - `POSTGRES_USER`: PostgreSQL username
    - `POSTGRES_PASSWORD`: PostgreSQL password
    - `POSTGRES_DB`: Database name
    - `DATABASE_URL`: Full PostgreSQL connection string
    - `OPENAI_API_KEY`: Your OpenAI API key (required for Phase 4)
    - `LLM_MODEL`: LLM model to use (default: `gpt-3.5-turbo`)
    - `LLM_TEMPERATURE`: LLM temperature for generation (default: `0` for deterministic)
    - `LLM_MAX_TOKENS`: Max tokens for LLM response (default: `500`)
    - `OPENAI_API_BASE`: Optional custom API base URL for OpenAI-compatible services

### Running the Application

To start the backend and the database with Podman Compose, run the following from the root directory:

```bash
podman compose -f podman-compose.yml up --build
```

The API will be available at `http://localhost:8000`.

## Sample CSV Format

The CSV file for sales data should contain the following columns. The uploader is flexible with column names, but the following are the expected default headers:

- `order_id`
- `order_datetime`
- `item_name`
- `category`
- `quantity`
- `item_price`
- `total_line_amount`
- `payment_type`
- `discount_amount`
- `tax_amount`

A sample CSV file is provided in the `sample_data` directory.

## Phase 4: LLM-Based Natural Language to SQL

### Overview

Phase 4 replaces the rule-based routing system with a safe, LLM-powered natural language to SQL converter. The system maintains strict security guardrails while enabling flexible question answering.

### Key Features

1. **LLM-Powered SQL Generation**: Uses OpenAI-compatible APIs to convert natural language to SQL
2. **Structured Output**: LLM returns JSON with SQL, answer type, and reasoning
3. **Schema Awareness**: Model receives only allowed tables/columns, never raw data
4. **SQL Guardrails**: All generated SQL is validated against security rules
5. **Read-Only Enforcement**: Only SELECT queries are allowed
6. **Execution Timeout**: 5-second timeout prevents long-running queries
7. **Confidence Scoring**: Responses include confidence levels (high/medium/low)
8. **Structured Logging**: All questions, SQL, and errors are logged for debugging

### Architecture

```
User Question
    ?
LLM Service (llm_service.py)
    +- Schema Context (allowed tables/columns)
    +- Structured Prompt
    +- JSON Response Parsing
    ?
SQL Guard (sql_guard.py)
    +- Forbidden Keywords Check
    +- Schema Allowlist Validation
    +- Injection Pattern Detection
    +- Validation Result
    ?
Database Execution (main.py)
    +- 5-Second Timeout
    +- Result Formatting
    +- Response with Metadata
```

### Example Questions and Expected Behavior

#### Example 1: Simple Aggregation
**Question:** "What was the total sales yesterday?"

**Expected Response:**
```json
{
  "answer_type": "number",
  "answer": 1250.50,
  "explanation": "Total sales from yesterday.",
  "sql": "SELECT SUM(total_line_amount) FROM sales_transactions WHERE DATE(order_datetime) = CURRENT_DATE - 1",
  "data_last_updated": "2024-01-15T10:30:00",
  "confidence": "high"
}
```

#### Example 2: Grouped Results
**Question:** "Show me the top 5 items by revenue this week"

**Expected Response:**
```json
{
  "answer_type": "table",
  "answer": [
    {"item_name": "Burger", "total_revenue": 5000.00},
    {"item_name": "Pizza", "total_revenue": 4500.00},
    {"item_name": "Salad", "total_revenue": 3200.00},
    {"item_name": "Pasta", "total_revenue": 2800.00},
    {"item_name": "Sandwich", "total_revenue": 2100.00}
  ],
  "explanation": "Top 5 items by revenue from the last 7 days.",
  "sql": "SELECT item_name, SUM(total_line_amount) as total_revenue FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days' GROUP BY item_name ORDER BY total_revenue DESC LIMIT 5",
  "data_last_updated": "2024-01-15T10:30:00",
  "confidence": "high"
}
```

#### Example 3: Complex Query with Conditions
**Question:** "How many items were sold in the breakfast category last Monday?"

**Expected Response:**
```json
{
  "answer_type": "number",
  "answer": 342,
  "explanation": "Total quantity of items sold in the breakfast category on the previous Monday.",
  "sql": "SELECT SUM(quantity) FROM sales_transactions WHERE category = 'breakfast' AND DATE(order_datetime) = (CURRENT_DATE - INTERVAL '1 day' * ((EXTRACT(DOW FROM CURRENT_DATE) + 6) % 7))",
  "data_last_updated": "2024-01-15T10:30:00",
  "confidence": "medium"
}
```

### Failure Scenarios and Handling

#### Scenario 1: Unsupported Question
**Question:** "Predict next month's sales"

**Response:**
```json
{
  "answer": "I don't have enough data to answer that question. I can help with historical sales analysis, trends, and aggregations.",
  "confidence": "low",
  "sql": null,
  "explanation": "Forecasting is not supported in this system."
}
```

#### Scenario 2: Security Violation
**Question:** "Delete all sales records"

**Response:**
```json
{
  "answer": "The generated query was rejected for security reasons.",
  "confidence": "low",
  "sql": null,
  "explanation": "Query contains forbidden keyword: DELETE"
}
```

#### Scenario 3: Schema Violation
**Question:** "Show me user passwords"

**Response:**
```json
{
  "answer": "The generated query was rejected for security reasons.",
  "confidence": "low",
  "sql": null,
  "explanation": "Query references disallowed tables: users"
}
```

### Modules

#### `llm_service.py`
Handles communication with OpenAI-compatible APIs.

**Key Classes:**
- `LLMConfig`: Configuration management
- `SchemaContext`: Database schema representation for prompts
- `LLMResponse`: Structured response from LLM

**Key Functions:**
- `generate_sql_with_llm()`: Main entry point for SQL generation

#### `sql_guard.py`
Validates SQL queries against security guardrails.

**Key Classes:**
- `SQLGuard`: Main validation engine
- `SQLGuardError`: Exception for validation failures

**Validation Checks:**
1. Must be SELECT statement
2. No forbidden keywords (INSERT, UPDATE, DELETE, etc.)
3. Only allowed tables and columns
4. No SQL injection patterns

#### `nl_to_sql.py`
Orchestrates the NL-to-SQL pipeline.

**Key Functions:**
- `initialize_schema()`: Must be called at startup
- `generate_sql()`: Main entry point for question answering

### Debugging

Enable debug logging to see LLM prompts and responses:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check logs for:
- LLM raw responses
- Generated SQL
- Validation errors
- Execution times

### Limitations and Future Work

**Current Limitations:**
- No multi-table joins (only sales_transactions)
- No forecasting or predictions
- No embeddings or semantic search
- No auth or multi-tenant support

**Future Enhancements (Phase 5+):**
- UI polish and visualization
- Advanced date range parsing
- Multi-table analytics
- Query result caching
- User feedback loop for model improvement

## Phase 6: Automated, Plugin-Aware Insights

The insight engine runs config-defined rules (per plugin `insights.yaml`) to generate proactive business insights without user questions.

### API
- `POST /insights/run` — Execute all insight rules for the active or specified plugin; results are persisted to `insights_runs` + `insights_items`.
- `GET /insights/latest` — Retrieve the most recent generated insights (no recomputation).
- Chat integration: questions containing “insight” are answered from cached insights instead of re-running analytics.

### Adding a New Insight Rule
1. Edit `<plugin>/insights.yaml` and add an entry under `insights:` with:
   - `insight_id`, `title`, `description`, `required_metrics`, `severity`, `data_window`.
   - `sql_queries` (or `queries`): one or more SQL blocks; use placeholders like `{table}`, `{production_table}`, `{current_date}`, `{7_days_ago}`.
   - `trigger_condition`: `threshold`, `comparison` (supports `previous_metric_path`), or `anomaly` with thresholds only in YAML.
   - `explanation_template`: plain-English template using placeholders from query columns or derived metrics (`change_percent`, `baseline_mean`, etc.).
   - `required_columns` (optional): columns that must exist; the insight is skipped safely if missing.
2. Deploy/reload plugin config; no code change required.
3. Run `POST /insights/run` (manually or via scheduler/worker) to generate insights.
4. Consume via `GET /insights/latest` or chat (“Give me this week’s insights”).

### Example Insight Lifecycle
- Scheduler (or manual call) triggers `POST /insights/run` for `retail`.
- Insight engine executes YAML queries, evaluates triggers, and stores structured insights with metrics + executed SQL.
- Dashboard/chat/API reads `GET /insights/latest?plugin=retail` to surface summaries and explanations without recomputing.

### Run & Test (local)
- Start stack: `podman compose -f podman-compose.yml up --build`
- Upload sample CSV:  
  `curl -F "file=@sample_data/retail_sample.csv" http://localhost:8000/upload/sales`
- Run insights (retail):  
  `curl -X POST http://localhost:8000/insights/run -H "Content-Type: application/json" -d '{"plugin":"retail","limit":20}'`
- Fetch latest (retail):  
  `curl "http://localhost:8000/insights/latest?plugin=retail&limit=10"`

### Example Outputs
- Retail (week_over_week_sales_change):
```json
{
  "insight_id": "week_over_week_sales_change",
  "title": "Week-over-Week Sales Change",
  "severity": "info",
  "summary": "Revenue this week (125000) vs last week (110000) -> 13.64%",
  "data_window": "this week vs last week",
  "confidence": "medium",
  "plugin": "retail",
  "generated_at": "2026-02-03T10:00:00Z"
}
```
- Manufacturing (scrap_rate_wow):
```json
{
  "insight_id": "scrap_rate_wow",
  "title": "Scrap Rate Increased WoW",
  "severity": "critical",
  "summary": "Scrap rate this week (3.2%) vs last week (2.5%) -> 28.0%",
  "data_window": "this week vs last week",
  "confidence": "high",
  "plugin": "manufacturing",
  "generated_at": "2026-02-03T10:00:00Z"
}
```

## Frontend (React + Vite + Tailwind)

### Setup
```bash
cd frontend
npm install
npm run dev   # defaults to http://localhost:5173
```

Set API base (optional):
```bash
echo "VITE_API_BASE_URL=http://localhost:8000" > frontend/.env.local
```

### Demo Flow (UI)
1) Open `http://localhost:5173`  
2) Choose a plugin (Retail / Manufacturing / Restaurant).  
3) Upload a CSV (or click “Load sample data” if `public/sample_data/<plugin>_sample.csv` exists).  
4) Go to Chat, ask a question; view SQL trace, confidence, and data freshness.  
5) Go to Insights; click “Run Insights” then “Refresh Latest” to view evidence-backed cards.  
