# Phase 4 Quick Start Guide

## What Changed?

The system now uses **LLM-powered natural language to SQL** instead of rule-based routing. This means:
- ✅ More flexible question answering
- ✅ Strict security guardrails
- ✅ Structured logging for debugging
- ✅ Confidence scoring
- ✅ Backward compatible with previous questions

## Quick Setup (5 minutes)

### 1. Create `.env` file
```bash
cd c:\Users\Ro\.qodo\agents
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

### 2. Start Services
```bash
podman compose -f podman-compose.yml up --build
```

Wait for: `Uvicorn running on http://0.0.0.0:8000`

### 3. Upload Sample Data
```bash
curl -X POST http://localhost:8000/upload/sales \
  -F "file=@sample_data/sales.csv"
```

Expected: `Successfully uploaded and ingested X rows`

### 4. Test Chat
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total sales yesterday?"}'
```

Expected: JSON response with answer, SQL, and confidence

## Files Modified/Added

| File | Status | Purpose |
|------|--------|---------|
| `backend/app/llm_service.py` | NEW | LLM communication |
| `backend/app/sql_guard.py` | NEW | SQL validation |
| `backend/app/nl_to_sql.py` | UPDATED | Orchestration |
| `backend/app/main.py` | UPDATED | Schema init |
| `README.md` | UPDATED | Documentation |

## 3 Example Questions to Test

### Question 1: Simple Aggregation
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What was the total sales yesterday?"}'
```

**Expected**: Single number with high confidence

### Question 2: Grouped Results
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Show me the top 5 items by revenue this week"}'
```

**Expected**: Table with 5 rows, high confidence

### Question 3: Complex Query
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "How many items were sold in the breakfast category last Monday?"}'
```

**Expected**: Single number with medium confidence

## Response Format

All responses follow this structure:
```json
{
  "answer_type": "number|table|text",
  "answer": "...",
  "explanation": "...",
  "sql": "SELECT ...",
  "data_last_updated": "2024-01-15T10:30:00",
  "confidence": "high|medium|low"
}
```

## Security Features

✅ **Forbidden Operations Blocked**
- INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE

✅ **Schema Allowlist**
- Only `sales_transactions` table
- Only allowed columns

✅ **Injection Detection**
- SQL comments blocked
- Multiple statements blocked
- Classic OR injection blocked

✅ **Execution Safety**
- 5-second timeout
- SELECT-only enforcement

## Debugging

### Check Logs
```bash
podman logs restaurant_backend
```

Look for:
- `LLM raw response:` - What the model returned
- `Generated SQL:` - The SQL that was generated
- `SQL validation passed:` - Validation succeeded
- `SQL validation failed:` - Validation failed

### Enable Debug Logging
Edit `backend/app/main.py`:
```python
logging.basicConfig(level=logging.DEBUG)
```

### Common Issues

**Issue**: "OPENAI_API_KEY environment variable not set"
- **Fix**: Add `OPENAI_API_KEY` to `.env`

**Issue**: "Query must be a SELECT statement"
- **Fix**: LLM generated non-SELECT, check LLM prompt

**Issue**: "Query references disallowed tables"
- **Fix**: LLM tried unauthorized table, check schema

**Issue**: "Query contains forbidden keyword"
- **Fix**: LLM generated write operation, check prompt

## Architecture Overview

```
Question
   ↓
LLM Service (generates SQL)
   ↓
SQL Guard (validates security)
   ↓
Database (executes with timeout)
   ↓
Response (with confidence & metadata)
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | REQUIRED | OpenAI API key |
| `LLM_MODEL` | gpt-3.5-turbo | Model to use |
| `LLM_TEMPERATURE` | 0 | Deterministic output |
| `LLM_MAX_TOKENS` | 500 | Max response length |
| `OPENAI_API_BASE` | (optional) | Custom API endpoint |

## What's NOT Supported

❌ Forecasting/predictions
❌ Multi-table joins
❌ Embeddings/semantic search
❌ User authentication
❌ Data modification

## Next Steps

1. **Test** the 3 example questions
2. **Verify** security with malicious queries
3. **Check** logs for debugging
4. **Proceed** to Phase 5 (UI polish)

## Documentation

- `README.md` - Full documentation
- `PHASE_4_IMPLEMENTATION.md` - Detailed implementation guide
- `PHASE_4_CHECKLIST.md` - Implementation checklist

## Support

For issues or questions:
1. Check logs: `podman logs restaurant_backend`
2. Review `PHASE_4_IMPLEMENTATION.md`
3. Check `README.md` for examples
4. Verify `.env` variables

---

**Ready to test?** Start with the 3 example questions above!
