# Phase 5: Plugin Architecture - Quick Reference

## Files Added/Modified

### New Code Module
- ✅ `backend/app/plugin_loader.py` - Plugin configuration loader and manager

### Plugin Configurations (3 sectors × 4 files = 12 files)
- ✅ `plugins/restaurant/` - Restaurant sector (refactored from hard-coded)
- ✅ `plugins/retail/` - Retail sector (new)
- ✅ `plugins/manufacturing/` - Manufacturing sector (new)

Each plugin contains:
- `schema.yaml` - Table and column definitions
- `metrics.yaml` - KPI definitions
- `questions.yaml` - Question patterns
- `policy.yaml` - Security policies

### Modified Code Modules
- ✅ `backend/app/nl_to_sql.py` - Plugin-based SQL generation
- ✅ `backend/app/llm_service.py` - Plugin-aware schema context
- ✅ `backend/app/main.py` - Plugin endpoints and switching

## Same Question, Different Plugins

### Question: "What was the total revenue yesterday?"

#### Restaurant Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "restaurant"}'
```

**Generated SQL:**
```sql
SELECT SUM(total_line_amount) 
FROM sales_transactions 
WHERE DATE(order_datetime) = CURRENT_DATE - 1
```

**Response:**
```json
{
  "answer_type": "number",
  "answer": 1250.50,
  "sql": "SELECT SUM(total_line_amount) FROM sales_transactions WHERE DATE(order_datetime) = CURRENT_DATE - 1",
  "plugin": "restaurant"
}
```

---

#### Retail Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "retail"}'
```

**Generated SQL:**
```sql
SELECT SUM(total_amount) 
FROM sales_transactions 
WHERE DATE(transaction_date) = CURRENT_DATE - 1
```

**Response:**
```json
{
  "answer_type": "number",
  "answer": 5432.75,
  "sql": "SELECT SUM(total_amount) FROM sales_transactions WHERE DATE(transaction_date) = CURRENT_DATE - 1",
  "plugin": "retail"
}
```

---

#### Manufacturing Plugin
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total revenue yesterday?", "plugin": "manufacturing"}'
```

**Generated SQL:**
```
(LLM cannot generate valid SQL - manufacturing doesn't track revenue)
```

**Response:**
```json
{
  "answer": "Manufacturing plugin does not track revenue. Available metrics: total_units_produced, defect_rate, total_scrap_weight, production_by_product, production_by_line, production_by_shift, daily_production_trend, total_production_cost",
  "confidence": "low",
  "sql": null,
  "plugin": "manufacturing"
}
```

---

## Key Differences Between Plugins

### Restaurant Plugin
- **Primary Table**: `sales_transactions`
- **Time Column**: `order_datetime`
- **Key Columns**: order_id, item_name, category, quantity, item_price, total_line_amount
- **Metrics**: total_sales, order_count, average_order_value, items_sold, top_items_by_revenue, sales_by_category, daily_sales_trend
- **Question Packs**: sales_analysis, category_analysis, volume_analysis

### Retail Plugin
- **Primary Table**: `sales_transactions`
- **Time Column**: `transaction_date`
- **Key Columns**: sku, product_name, category, subcategory, quantity, unit_price, total_amount, store_id, region, discount_percent
- **Metrics**: total_revenue, transaction_count, average_transaction_value, units_sold, top_skus_by_revenue, revenue_by_category, revenue_by_region, daily_revenue_trend, discount_impact
- **Question Packs**: sku_analysis, revenue_analysis, category_analysis, regional_analysis, discount_analysis, volume_analysis

### Manufacturing Plugin
- **Primary Table**: `production_runs`
- **Time Column**: `run_date`
- **Key Columns**: product_id, product_name, line_id, units_produced, units_defective, scrap_weight_kg, production_time_hours, material_cost, labor_cost, shift, facility
- **Metrics**: total_units_produced, total_defective_units, defect_rate, total_scrap_weight, total_production_hours, production_by_product, production_by_line, production_by_shift, daily_production_trend, total_production_cost
- **Question Packs**: production_volume, quality_analysis, product_analysis, line_analysis, shift_analysis, cost_analysis

## New API Endpoints

### 1. Switch Plugin
```bash
POST /plugin/switch
Content-Type: application/json

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

### 2. List All Plugins
```bash
GET /plugins
```

Response:
```json
{
  "plugins": {
    "restaurant": {...},
    "retail": {...},
    "manufacturing": {...}
  },
  "active_plugin": "restaurant"
}
```

### 3. Get Active Plugin Info
```bash
GET /plugin/info
```

Response:
```json
{
  "plugin_name": "retail",
  "tables": ["sales_transactions"],
  "columns": ["transaction_id", "transaction_date", ...],
  "metrics": ["total_revenue", "transaction_count", ...],
  "question_packs": ["sku_analysis", "revenue_analysis", ...],
  "policy": {
    "allowed_question_types": ["aggregation", "trend", ...],
    "forbidden_topics": ["pii", "personal_data", ...],
    "enable_forecasting": false,
    "enable_predictions": false
  }
}
```

### 4. Chat with Plugin Selection
```bash
POST /chat
Content-Type: application/json

{
  "query": "What was the total revenue yesterday?",
  "plugin": "retail"
}
```

Response includes `"plugin": "retail"` field.

## Adding a New Plugin (< 30 minutes)

### 1. Create Directory
```bash
mkdir -p plugins/logistics
```

### 2. Create schema.yaml
```yaml
tables:
  shipments:
    description: "Shipment records"
    primary_time_column: "shipment_date"
    columns:
      shipment_id:
        type: "string"
        meaning: "Unique shipment identifier"
        nullable: false
      shipment_date:
        type: "timestamp"
        meaning: "Date and time of shipment"
        nullable: false
      origin:
        type: "string"
        meaning: "Origin location"
        nullable: false
      destination:
        type: "string"
        meaning: "Destination location"
        nullable: false
      weight_kg:
        type: "numeric"
        meaning: "Shipment weight in kilograms"
        nullable: false
      cost:
        type: "numeric"
        meaning: "Shipping cost"
        nullable: false
```

### 3. Create metrics.yaml
```yaml
metrics:
  total_shipments:
    description: "Total number of shipments"
    sql_template: "SELECT COUNT(*) FROM {table} {time_filter}"
    output_type: "number"
    aggregation: "count"
  
  total_weight:
    description: "Total weight shipped"
    sql_template: "SELECT SUM(weight_kg) FROM {table} {time_filter}"
    output_type: "number"
    aggregation: "sum"
  
  total_cost:
    description: "Total shipping cost"
    sql_template: "SELECT SUM(cost) FROM {table} {time_filter}"
    output_type: "number"
    aggregation: "sum"
```

### 4. Create questions.yaml
```yaml
question_packs:
  shipment_analysis:
    description: "Questions about shipments"
    patterns:
      - pattern: "total.*shipment|shipment.*count"
        required_metrics: ["total_shipments"]
        constraints:
          min_confidence: "high"
```

### 5. Create policy.yaml
```yaml
allowed_question_types:
  - "aggregation"
  - "trend"

forbidden_topics:
  - "pii"

enable_forecasting: false
```

### 6. Test
```bash
curl -X POST http://localhost:8000/plugin/switch \
  -H "Content-Type: application/json" \
  -d '{"plugin": "logistics"}'

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "How many shipments yesterday?", "plugin": "logistics"}'
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    User Question                             │
│              + Plugin Name (optional)                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Plugin Manager                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Load plugin config from YAML files               │  │
│  │ 2. Validate config structure                         │  │
│  │ 3. Set as active plugin                              │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              NL-to-SQL Engine                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Get active plugin                                │  │
│  │ 2. Extract schema from plugin config                │  │
│  │ 3. Extract metrics from plugin config               │  │
│  │ 4. Validate question against plugin policy          │  │
│  │ 5. Call LLM with plugin-specific schema             │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              SQL Guard                                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Validate against plugin's allowed tables         │  │
│  │ 2. Validate against plugin's allowed columns        │  │
│  │ 3. Enforce plugin's security policies               │  │
│  │ 4. Check for injection patterns                      │  │
│  └──────────────────────────────────────────────────────┘  │
└──���─────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Database Execution                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Execute SQL with 5-second timeout                │  │
│  │ 2. Format results                                    │  │
│  │ 3. Get data freshness timestamp                      │  │
│  │ 4. Return with plugin name                           │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  API Response                                │
│  {                                                           │
│    "answer_type": "number|table|text",                      │
│    "answer": ...,                                           │
│    "explanation": "...",                                    │
│    "sql": "...",                                            │
│    "data_last_updated": "ISO timestamp",                    │
│    "confidence": "high|medium|low",                         │
│    "plugin": "restaurant|retail|manufacturing"              │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
```

## Backward Compatibility

✅ All existing endpoints work unchanged
✅ Default plugin is "restaurant"
✅ Existing questions still work
✅ Same response format (with added "plugin" field)
✅ No database schema changes

## Status

✅ **Phase 5 Complete**
- Plugin loader implemented
- 3 sector plugins configured
- Plugin switching endpoints added
- LLM integration updated
- SQL guard updated
- Backward compatible

---

**Ready to test?** Start with:
```bash
curl http://localhost:8000/plugins
```
