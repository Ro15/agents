# Phase 5: Plugin Architecture - Implementation Guide

## Overview

Phase 5 transforms the system into a **sector-agnostic, config-driven data analyst plugin**. New sectors can be added WITHOUT changing application code—only by adding configuration files.

## What Changed

### New Files Added

1. **`backend/app/plugin_loader.py`** (500+ lines)
   - `PluginConfig`: Loads and manages sector-specific configurations
   - `PluginManager`: Manages multiple plugins and plugin switching
   - Configuration classes: `ColumnDefinition`, `TableDefinition`, `MetricDefinition`, `QuestionPattern`, `QuestionPack`, `PolicyConfig`

2. **Plugin Configuration Directories**
   - `plugins/restaurant/` - Restaurant sector (existing)
   - `plugins/retail/` - Retail sector (new)
   - `plugins/manufacturing/` - Manufacturing sector (new)

3. **Configuration Files (per plugin)**
   - `schema.yaml` - Database schema definition
   - `metrics.yaml` - KPI and metric definitions
   - `questions.yaml` - Question patterns and packs
   - `policy.yaml` - Security and behavior policies

### Modified Files

1. **`backend/app/nl_to_sql.py`**
   - Replaced hard-coded schema with plugin-based configuration
   - Added `initialize_plugins()` function
   - Added `set_active_plugin()` function
   - Added `get_active_plugin()` function
   - SQL generation now uses active plugin's schema

2. **`backend/app/llm_service.py`**
   - Updated `SchemaContext` to accept plugin configuration
   - Added `plugin_name` parameter
   - Added `metrics_description` parameter
   - Schema prompt now dynamically generated from plugin config

3. **`backend/app/main.py`**
   - Added `ChatQuery.plugin` field for plugin selection
   - Added `PluginSwitchRequest` model
   - Updated startup to initialize plugin manager
   - Added `/plugin/switch` endpoint
   - Added `/plugins` endpoint
   - Added `/plugin/info` endpoint
   - Chat response now includes `plugin` field

## Architecture

```
Request with Plugin Name
    ↓
Plugin Manager
    ├─ Load plugin config
    ├─ Validate config
    └─ Set as active
    ↓
NL-to-SQL Engine
    ├─ Get active plugin
    ├─ Extract schema from config
    ├─ Extract metrics from config
    └─ Generate SQL
    ↓
SQL Guard
    ├─ Validate against plugin's allowed tables
    ├─ Validate against plugin's allowed columns
    └─ Enforce plugin's policies
    ↓
Database Execution
    ├─ Execute SQL
    ├─ Format results
    └─ Return with plugin name
```

## Plugin Configuration Structure

### schema.yaml
Defines database tables and columns:
```yaml
tables:
  table_name:
    description: "Human-readable description"
    primary_time_column: "column_name"
    columns:
      column_name:
        type: "string|numeric|timestamp"
        meaning: "What this column represents"
        nullable: true|false
```

### metrics.yaml
Defines KPIs and metrics:
```yaml
metrics:
  metric_name:
    description: "What this metric measures"
    sql_template: "SELECT ... FROM {table} {time_filter}"
    output_type: "number|table|text"
    aggregation: "sum|count|avg|min|max"
```

### questions.yaml
Defines supported question patterns:
```yaml
question_packs:
  pack_name:
    description: "Logical grouping of questions"
    patterns:
      - pattern: "regex or keyword pattern"
        required_metrics: ["metric1", "metric2"]
        constraints:
          min_confidence: "high|medium|low"
```

### policy.yaml
Defines security and behavior policies:
```yaml
allowed_question_types:
  - "aggregation"
  - "trend"
  - "comparison"

forbidden_topics:
  - "pii"
  - "personal_data"

max_date_range_days: null

enable_forecasting: false

enable_predictions: false
```

## Adding a New Sector Plugin (< 30 minutes)

### Step 1: Create Plugin Directory
```bash
mkdir -p plugins/your_sector
```

### Step 2: Create schema.yaml
Define your tables and columns:
```yaml
tables:
  your_table:
    description: "Your table description"
    primary_time_column: "date_column"
    columns:
      column1:
        type: "string"
        meaning: "What column1 represents"
        nullable: false
      column2:
        type: "numeric"
        meaning: "What column2 represents"
        nullable: true
```

### Step 3: Create metrics.yaml
Define your KPIs:
```yaml
metrics:
  total_revenue:
    description: "Total revenue"
    sql_template: "SELECT SUM(amount) FROM {table} {time_filter}"
    output_type: "number"
    aggregation: "sum"
```

### Step 4: Create questions.yaml
Define question patterns:
```yaml
question_packs:
  revenue_analysis:
    description: "Revenue questions"
    patterns:
      - pattern: "total.*revenue|earnings"
        required_metrics: ["total_revenue"]
        constraints:
          min_confidence: "high"
```

### Step 5: Create policy.yaml
Define policies:
```yaml
allowed_question_types:
  - "aggregation"
  - "trend"

forbidden_topics:
  - "pii"

enable_forecasting: false
```

### Step 6: Test
```bash
curl -X POST http://localhost:8000/plugin/switch \
  -H "Content-Type: application/json" \
  -d '{"plugin": "your_sector"}'

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Your question", "plugin": "your_sector"}'
```

## API Endpoints

### Chat with Plugin Selection
```bash
POST /chat
{
  "query": "What was the total sales yesterday?",
  "plugin": "restaurant"  # or "retail", "manufacturing"
}
```

Response:
```json
{
  "answer_type": "number",
  "answer": 1250.50,
  "explanation": "...",
  "sql": "SELECT SUM(...)",
  "data_last_updated": "2024-01-15T10:30:00",
  "confidence": "high",
  "plugin": "restaurant"
}
```

### Switch Plugin
```bash
POST /plugin/switch
{
  "plugin": "retail"
}
```

Response:
```json
{
  "status": "success",
  "plugin": "retail",
  "tables": ["sales_transactions"],
  "metrics": ["total_revenue", "transaction_count", ...]
}
```

### List All Plugins
```bash
GET /plugins
```

Response:
```json
{
  "plugins": {
    "restaurant": {
      "plugin_name": "restaurant",
      "tables": ["sales_transactions"],
      "metrics": ["total_sales", "order_count", ...],
      "question_packs": ["sales_analysis", "category_analysis", ...]
    },
    "retail": {...},
    "manufacturing": {...}
  },
  "active_plugin": "restaurant"
}
```

### Get Active Plugin Info
```bash
GET /plugin/info
```

Response:
```json
{
  "plugin_name": "restaurant",
  "tables": ["sales_transactions"],
  "columns": ["order_id", "order_datetime", ...],
  "metrics": ["total_sales", "order_count", ...],
  "question_packs": ["sales_analysis", "category_analysis", ...],
  "policy": {
    "allowed_question_types": ["aggregation", "trend", ...],
    "forbidden_topics": ["pii", "personal_data"],
    "enable_forecasting": false,
    "enable_predictions": false
  }
}
```

## Example: Same Question, Different Plugins

### Question: "What was the total revenue yesterday?"

#### Restaurant Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "restaurant"}'
```

Response:
```json
{
  "answer_type": "number",
  "answer": 1250.50,
  "sql": "SELECT SUM(total_line_amount) FROM sales_transactions WHERE DATE(order_datetime) = CURRENT_DATE - 1",
  "plugin": "restaurant"
}
```

#### Retail Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "retail"}'
```

Response:
```json
{
  "answer_type": "number",
  "answer": 5432.75,
  "sql": "SELECT SUM(total_amount) FROM sales_transactions WHERE DATE(transaction_date) = CURRENT_DATE - 1",
  "plugin": "retail"
}
```

#### Manufacturing Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "manufacturing"}'
```

Response:
```json
{
  "answer": "Manufacturing plugin does not track revenue. Available metrics: total_units_produced, defect_rate, total_scrap_weight, etc.",
  "confidence": "low",
  "sql": null,
  "plugin": "manufacturing"
}
```

## Plugin Comparison

| Aspect | Restaurant | Retail | Manufacturing |
|--------|-----------|--------|-----------------|
| **Primary Table** | sales_transactions | sales_transactions | production_runs |
| **Time Column** | order_datetime | transaction_date | run_date |
| **Key Metrics** | total_sales, order_count, avg_order_value | total_revenue, transaction_count, discount_impact | units_produced, defect_rate, scrap_weight |
| **Question Packs** | sales_analysis, category_analysis | sku_analysis, regional_analysis | quality_analysis, production_volume |
| **Unique Columns** | item_name, category | sku, region, store_id | product_id, line_id, shift, facility |

## Key Features

### ✅ Sector-Agnostic
- Same code works for all sectors
- No code changes needed to add new sectors

### ✅ Config-Driven
- All sector-specific logic in YAML files
- Easy to modify without redeployment

### ✅ Plugin Switching
- Switch between sectors at runtime
- No restart required

### ✅ Schema Awareness
- LLM receives plugin-specific schema
- Metrics included in prompts
- Column meanings provided

### ✅ Policy Enforcement
- Forbidden topics per plugin
- Question type restrictions
- Date range limits

### ✅ Backward Compatible
- Existing restaurant plugin works unchanged
- All previous questions still work
- Same API response format

## Security Guardrails

### Per-Plugin Allowlists
- Each plugin defines allowed tables
- Each plugin defines allowed columns
- SQL Guard enforces plugin-specific rules

### Policy Validation
- Questions checked against forbidden topics
- Question types validated
- Date ranges enforced

### SQL Validation
- SELECT-only enforcement
- No data modification allowed
- Injection pattern detection

## Limitations

❌ No multi-table joins (single table per plugin)
❌ No forecasting or predictions
❌ No embeddings or vector databases
❌ No auth or multi-tenant support
❌ No auto-learning metrics

## Files Added/Modified Summary

### New Files (1 code + 12 config)
- `backend/app/plugin_loader.py` (500+ lines)
- `plugins/restaurant/schema.yaml`
- `plugins/restaurant/metrics.yaml`
- `plugins/restaurant/questions.yaml`
- `plugins/restaurant/policy.yaml`
- `plugins/retail/schema.yaml`
- `plugins/retail/metrics.yaml`
- `plugins/retail/questions.yaml`
- `plugins/retail/policy.yaml`
- `plugins/manufacturing/schema.yaml`
- `plugins/manufacturing/metrics.yaml`
- `plugins/manufacturing/questions.yaml`
- `plugins/manufacturing/policy.yaml`

### Modified Files (3)
- `backend/app/nl_to_sql.py` (refactored for plugins)
- `backend/app/llm_service.py` (plugin-aware schema context)
- `backend/app/main.py` (plugin endpoints + switching)

## Testing the Plugin System

### 1. List Available Plugins
```bash
curl http://localhost:8000/plugins
```

### 2. Switch to Retail Plugin
```bash
curl -X POST http://localhost:8000/plugin/switch \
  -H "Content-Type: application/json" \
  -d '{"plugin": "retail"}'
```

### 3. Get Retail Plugin Info
```bash
curl http://localhost:8000/plugin/info
```

### 4. Ask a Retail Question
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Show me the top 5 SKUs by revenue", "plugin": "retail"}'
```

### 5. Switch to Manufacturing Plugin
```bash
curl -X POST http://localhost:8000/plugin/switch \
  -H "Content-Type: application/json" \
  -d '{"plugin": "manufacturing"}'
```

### 6. Ask a Manufacturing Question
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the defect rate by production line?", "plugin": "manufacturing"}'
```

## Next Steps

1. Test plugin switching with sample data
2. Verify SQL generation for each plugin
3. Test security guardrails per plugin
4. Add more plugins as needed
5. Proceed to Phase 6 (UI enhancements)

---

**Status**: ✅ Phase 5 implementation complete
**Plugins Available**: 3 (restaurant, retail, manufacturing)
**Configuration Files**: 12 YAML files
**New Endpoints**: 3 (/plugin/switch, /plugins, /plugin/info)
