"""
LLM Service for Natural Language to SQL conversion.

Supports OpenAI ChatCompletion (legacy) and Gemini (google-generativeai).
The default provider is Gemini to leverage the free tier.
"""

import os
import json
import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

import openai  # kept for backward compatibility
import google.generativeai as genai

logger = logging.getLogger(__name__)


def _extract_openai_text(response: Any) -> str:
    """Extract text content from both legacy and v1 OpenAI response shapes."""
    try:
        if not response or not getattr(response, "choices", None):
            return ""
        msg = response.choices[0].message
        if isinstance(msg, dict):
            return (msg.get("content") or "").strip()
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            # Multimodal content blocks; keep text blocks only.
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return " ".join([p for p in parts if p]).strip()
        return (content or "").strip()
    except Exception:
        return ""


def _openai_major_version() -> int:
    try:
        ver = getattr(openai, "__version__", "0")
        return int(str(ver).split(".", 1)[0])
    except Exception:
        return 0


def _openai_http_chat_text(
    config: "LLMConfig",
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Direct HTTP fallback for OpenAI-compatible chat completions."""
    endpoint = config.api_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urlrequest.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {config.api_key}")
    timeout = float(os.getenv("LLM_HTTP_TIMEOUT_SECONDS", "30"))
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        choices = parsed.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in response from {endpoint}")
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        return (msg.get("content") or "").strip()
    except HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {endpoint}: {details[:400]}") from e
    except URLError as e:
        raise RuntimeError(f"Network error calling {endpoint}: {e}") from e


def _openai_chat_text(
    config: "LLMConfig",
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call OpenAI-compatible chat endpoint for both SDK generations."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # openai>=1.x path
    if getattr(config, "openai_client", None) is not None:
        resp = config.openai_client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _extract_openai_text(resp)

    # For openai>=1 where client init fails (SDK/httpx mismatch), use direct HTTP.
    if _openai_major_version() >= 1:
        return _openai_http_chat_text(
            config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Legacy fallback (openai<1.0)
    if hasattr(openai, "ChatCompletion"):
        resp = openai.ChatCompletion.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _extract_openai_text(resp)

    return _openai_http_chat_text(
        config,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class LLMConfig:
    """Configuration for LLM service."""
    
    def __init__(self):
        # Provider can be "gemini" (default) or "openai"
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower()

        # Keys (LLM_API_KEY takes precedence to avoid host overrides)
        if self.provider == "gemini":
            self.api_key = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
        else:
            self.api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

        # Models
        self.model = os.getenv("LLM_MODEL", "gemini-2.0-flash" if self.provider == "gemini" else "gpt-3.5-turbo")

        # Endpoints
        self.api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        # For google-generativeai, api_endpoint should be just the host (no scheme/path)
        self.gemini_api_base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))
        self.available = bool(self.api_key)
        self.openai_client = None

        if not self.available:
            logger.warning("LLM not configured (missing API key); falling back to safe failure.")
            return

        if self.provider == "openai":
            # Prefer openai>=1.x client API if available.
            try:
                if hasattr(openai, "OpenAI"):
                    self.openai_client = openai.OpenAI(
                        api_key=self.api_key,
                        base_url=self.api_base,
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI v1 client; falling back to legacy mode: {e}")
                self.openai_client = None

            if self.openai_client is None:
                # Legacy mode for older SDK versions.
                openai.api_key = self.api_key
                if self.api_base != "https://api.openai.com/v1":
                    # Older SDK uses api_base; keep backward compatibility.
                    openai.api_base = self.api_base
        else:
            parsed = urlparse(self.gemini_api_base)
            api_endpoint = parsed.netloc or parsed.path or self.gemini_api_base
            genai.configure(api_key=self.api_key, client_options={"api_endpoint": api_endpoint})


class SchemaContext:
    """Encapsulates database schema information for LLM prompting."""

    def __init__(self, schema: Dict[str, Any], allowed_tables: set, allowed_columns: set,
                 plugin_name: str = "", metrics_description: str = "",
                 views: Optional[List[str]] = None,
                 dynamic_columns: Optional[List[Dict[str, Any]]] = None,
                 dynamic_table: Optional[str] = None,
                 focus_columns: Optional[List[str]] = None,
                 business_glossary: Optional[List[Dict[str, str]]] = None,
                 relationships_description: str = "",
                 schema_description: str = ""):
        """
        Args:
            schema: Dict mapping table names to TableDefinition objects (from plugin_loader)
            allowed_tables: Set of allowed table names
            allowed_columns: Set of allowed column names
            plugin_name: Name of the active plugin
            metrics_description: Human-readable metrics description
            dynamic_columns: Column profiles for dynamic datasets [{name, data_type, description, ...}]
            dynamic_table: The dynamic table name (e.g. "ds_abc123def456")
            relationships_description: Human-readable table relationships for JOIN guidance
            schema_description: Full human-readable schema description (all tables + columns)
        """
        self.schema = schema
        self.allowed_tables = allowed_tables
        self.allowed_columns = allowed_columns
        self.plugin_name = plugin_name
        self.metrics_description = metrics_description
        self.views = views or []
        self.dynamic_columns = dynamic_columns
        self.dynamic_table = dynamic_table
        self.focus_columns = focus_columns or []
        self.business_glossary = business_glossary or []
        self.relationships_description = relationships_description
        self.schema_description = schema_description

    def to_prompt_string(self) -> str:
        """
        Converts schema to a human-readable format for the LLM prompt.
        For dynamic datasets, includes full column details.
        For static (plugin) datasets, includes metric views, full table schemas, and relationships.
        """
        # Dynamic dataset: provide explicit table + column schema
        if self.dynamic_table is not None and self.dynamic_columns is not None:
            schema_text = f"## Database Schema\n\n"
            schema_text += f"Table: `{self.dynamic_table}`\n"
            schema_text += "Columns:\n"
            for col in self.dynamic_columns:
                name = col.get("column_name", col.get("name", ""))
                dtype = col.get("data_type", col.get("type", "TEXT"))
                desc = col.get("description", "")
                desc_str = f" — {desc}" if desc else ""
                schema_text += f"  - `{name}` ({dtype}){desc_str}\n"
            schema_text += f"\nIMPORTANT: Only use the table `{self.dynamic_table}` in your SQL.\n"
            schema_text += "Do NOT add WHERE clauses for dataset_id; the system handles filtering.\n"
            if self.focus_columns:
                schema_text += f"\nFocus columns for this question: {', '.join(self.focus_columns[:20])}\n"
            if self.business_glossary:
                schema_text += "\n## Business Glossary\n"
                for item in self.business_glossary[:25]:
                    term = item.get("term", "").strip()
                    definition = item.get("definition", "").strip()
                    if term and definition:
                        schema_text += f"- `{term}`: {definition}\n"
            return schema_text

        # Static (plugin) dataset
        schema_text = ""

        # Include full table schema so the LLM knows all tables and columns for JOINs
        if self.schema_description:
            schema_text += self.schema_description + "\n"

        # Include metric views
        if self.views:
            schema_text += f"## {self.plugin_name.upper()} Metric Views\n\n"
            schema_text += "For simple metric queries, prefer these pre-built views:\n"
            for view in sorted(self.views):
                schema_text += f"- View: `{view}`\n"
            schema_text += "\n"

        if self.metrics_description:
            schema_text += "# Metric descriptions\n" + self.metrics_description + "\n"

        # Include relationship info for multi-table JOINs
        if self.relationships_description:
            schema_text += "\n" + self.relationships_description + "\n"

        if self.focus_columns:
            schema_text += "\n## Focus Columns For This Question\n"
            schema_text += ", ".join(self.focus_columns[:25]) + "\n"

        if self.business_glossary:
            schema_text += "\n## Business Glossary\n"
            for item in self.business_glossary[:40]:
                term = item.get("term", "").strip()
                definition = item.get("definition", "").strip()
                if term and definition:
                    schema_text += f"- `{term}`: {definition}\n"

        schema_text += "\nRemember: do NOT filter dataset_id; system injects it."
        return schema_text


class LLMResponse:
    """Structured response from LLM."""
    
    def __init__(self, sql: str, answer_type: str, notes: str = "", assumptions: Optional[List[str]] = None,
                 model_name: Optional[str] = None, chart_hint: str = "none", summary: str = ""):
        self.sql = sql
        self.answer_type = answer_type  # "number", "table", or "text"
        self.notes = notes
        self.assumptions = assumptions or []
        self.model_name = model_name
        self.chart_hint = chart_hint
        self.summary = summary
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "answer_type": self.answer_type,
            "notes": self.notes,
            "assumptions": self.assumptions,
            "model_name": self.model_name,
            "chart_hint": self.chart_hint,
            "summary": self.summary,
        }


def generate_text_response(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
    temperature: float = 0,
    max_tokens: int = 300,
) -> str:
    """
    Generic provider-agnostic text generation helper.
    """
    if config is None:
        config = LLMConfig()
    if not config.available:
        return ""
    if config.provider == "openai":
        return _openai_chat_text(
            config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    model_name = config.model
    if not model_name.startswith("models/"):
        model_name = f"models/{model_name}"
    model = genai.GenerativeModel(model_name)
    gen_response = model.generate_content(
        (system_prompt or "") + "\n\n" + (user_prompt or ""),
        generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
    )
    text_out = ""
    if getattr(gen_response, "candidates", None):
        for part in gen_response.candidates[0].content.parts:
            if hasattr(part, "text"):
                text_out = part.text
                break
    if not text_out:
        text_out = (getattr(gen_response, "text", "") or "").strip()
    return text_out


def generate_narrative(
    question: str,
    sql: str,
    result_data: Any,
    answer_type: str,
    config: Optional[LLMConfig] = None,
) -> str:
    """
    Send query results back to the LLM to produce a human-friendly narrative.
    E.g. "Revenue increased 12% week-over-week, driven primarily by Electronics…"
    """
    if config is None:
        config = LLMConfig()
    if not config.available:
        return ""

    # Build a compact representation of the result
    if answer_type == "number" or (isinstance(result_data, (int, float, str)) and not isinstance(result_data, list)):
        data_summary = f"Result: {result_data}"
    elif isinstance(result_data, list):
        # Truncate large result sets for the LLM context
        preview = result_data[:20]
        data_summary = f"Result ({len(result_data)} rows, showing first {len(preview)}):\n{json.dumps(preview, default=str)}"
    else:
        data_summary = f"Result: {json.dumps(result_data, default=str)[:2000]}"

    system_prompt = (
        "You are a data analyst assistant. Given a user's question, the SQL that answered it, "
        "and the query results, write a concise 1-3 sentence narrative that explains the data "
        "in plain business English. Focus on insights, trends, and key takeaways. "
        "Do NOT include SQL or technical jargon. Return ONLY the narrative text."
    )
    user_prompt = f"Question: {question}\nSQL: {sql}\n{data_summary}"

    try:
        if config.provider == "openai":
            return _openai_chat_text(
                config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=300,
            )
        else:
            model_name = config.model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
            model = genai.GenerativeModel(model_name)
            gen_response = model.generate_content(
                system_prompt + "\n\n" + user_prompt,
                generation_config={"temperature": 0.3, "max_output_tokens": 300},
            )
            text_out = ""
            if getattr(gen_response, "candidates", None):
                for part in gen_response.candidates[0].content.parts:
                    if hasattr(part, "text"):
                        text_out = part.text
                        break
            if not text_out:
                text_out = (getattr(gen_response, "text", "") or "").strip()
            return text_out
    except Exception as e:
        logger.warning(f"Narrative generation failed: {e}")
        return ""


def generate_sql_with_llm(
    question: str,
    schema_context: SchemaContext,
    config: Optional[LLMConfig] = None,
    feedback: Optional[Dict[str, Any]] = None,
    extra_context: Optional[str] = None,
    timezone: str = "UTC",
    today_iso: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[LLMResponse]:
    """
    Generates SQL from a natural language question using an LLM.
    
    Args:
        question: Natural language question from the user
        schema_context: SchemaContext object with database schema info
        config: LLMConfig object (created if not provided)
    
    Returns:
        LLMResponse object with sql, answer_type, and notes, or None if generation fails
    """
    if config is None:
        config = LLMConfig()
    if not config.available:
        logger.error("LLM unavailable; generate_sql_with_llm returning None")
        return None
    
    schema_prompt = schema_context.to_prompt_string()
    
    feedback_block = ""
    if feedback:
        feedback_block = f"\n\nPrevious attempt failed. Error: {feedback.get('error')}\nAllowed tables: {', '.join(sorted(feedback.get('allowed_tables', [])))}\nAllowed columns: {', '.join(sorted(feedback.get('allowed_columns', [])))}\nTime column: {feedback.get('time_column')}"
        learning_examples = (feedback.get("learning_examples") or "").strip()
        if learning_examples:
            feedback_block += f"\n\nLearned corrections from prior feedback:\n{learning_examples[:2500]}"

    system_prompt = """You are a PostgreSQL expert assistant that converts natural language questions into SQL queries.

IMPORTANT RULES:
1. Generate ONLY valid PostgreSQL SELECT statements
2. Do NOT include any explanations, comments, or markdown formatting
3. Do NOT use any tables or columns not provided in the schema
4. Always use proper SQL syntax and PostgreSQL functions
5. For date/time operations, use PostgreSQL functions like DATE(), EXTRACT(), CURRENT_DATE, INTERVAL
6. Return your response as a JSON object with this exact structure:
{
    "sql": "SELECT ...",
    "answer_type": "number|table|text",
    "chart_hint": "line|bar|pie|area|none",
    "summary": "One-sentence plain-English summary of the expected answer",
    "assumptions": ["optional reasoning or assumptions"]
}
- chart_hint: suggest the best chart for the result. Use "line" for time-series, "bar" for comparisons, "pie" for composition (<=8 groups), "area" for multi-metric time-series, "none" for scalars or text.
- summary: a short human-friendly explanation of what the data means.
7. Do NOT include dataset_id filters; the system injects them automatically.

MULTI-TABLE JOIN RULES:
- When the question involves data from multiple tables, use JOINs to combine them.
- Use the relationships defined in the schema to determine the correct JOIN conditions.
- Prefer LEFT JOIN when the relationship is many_to_one (to preserve all rows from the main table).
- Use INNER JOIN when both sides must match (e.g., one_to_many lookups).
- Always qualify column names with table names or aliases when using JOINs to avoid ambiguity.
- For simple single-table metric queries, prefer the pre-built metric views if available.

ALLOWED OPERATIONS:
- SELECT, FROM, WHERE, GROUP BY, ORDER BY, LIMIT, OFFSET
- JOINs: INNER JOIN, LEFT JOIN, RIGHT JOIN, FULL OUTER JOIN, CROSS JOIN
- Aggregation functions: SUM, COUNT, AVG, MIN, MAX
- Date functions: DATE(), EXTRACT(), CURRENT_DATE, INTERVAL
- String functions: UPPER, LOWER, CONCAT, SUBSTRING
- Math functions: ROUND, ABS, CEIL, FLOOR

FORBIDDEN OPERATIONS:
- INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE
- Any modification of data
- Any access to system tables or functions
"""
    
    # Build conversation context block for multi-turn
    conversation_block = ""
    if conversation_history:
        conversation_block = "\n## Conversation History (for context — answer the latest question)\n"
        for turn in conversation_history[-10:]:  # last 10 messages
            role = turn.get("role", "user")
            content = (turn.get("content") or "")[:500]  # truncate long answers
            conversation_block += f"- {role}: {content}\n"

    extra_context_block = ""
    if extra_context:
        extra_context_block = f"## Extra Guidance\n{extra_context}\n"

    user_prompt = f"""{schema_prompt}

## Question
{question}
{conversation_block}
{extra_context_block}
## Context
- Timezone: {timezone}
- Today: {today_iso or "unknown"}
{feedback_block}

Generate a PostgreSQL query to answer this question. Return ONLY a valid JSON object with the structure shown above."""
    
    try:
        logger.info(f"Calling LLM provider={config.provider} model={config.model} for question: {question}")

        if config.provider == "openai":
            response_text = _openai_chat_text(
                config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        else:  # gemini
            model_name = config.model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
            model = genai.GenerativeModel(model_name)
            gen_response = model.generate_content(
                system_prompt + "\n\n" + user_prompt,
                generation_config={
                    "temperature": config.temperature,
                    "max_output_tokens": config.max_tokens,
                },
            )
            response_text = ""
            if getattr(gen_response, "candidates", None):
                for part in gen_response.candidates[0].content.parts:
                    if hasattr(part, "text"):
                        response_text = part.text
                        break
            if not response_text:
                response_text = (getattr(gen_response, "text", "") or "").strip()

        logger.debug(f"LLM raw response: {response_text}")
        
        # Parse JSON response
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from code blocks or the first {...} blob
            extracted = None
            if "```json" in response_text:
                extracted = response_text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in response_text:
                extracted = response_text.split("```", 1)[1].split("```", 1)[0].strip()
            else:
                m = re.search(r"\{.*\}", response_text, re.S)
                if m:
                    extracted = m.group(0)
            if extracted:
                try:
                    response_json = json.loads(extracted)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse extracted JSON: {e}; raw text: {response_text[:400]}")
                    return None
            else:
                logger.error(f"Failed to parse LLM response as JSON; raw text: {response_text[:400]}")
                return None
        
        sql = response_json.get("sql", "").strip()
        answer_type = response_json.get("answer_type", "text")
        notes = response_json.get("notes", "") or response_json.get("explanation", "")
        assumptions = response_json.get("assumptions") or []
        chart_hint = response_json.get("chart_hint", "none") or "none"
        summary = response_json.get("summary", "") or ""
        
        if not sql:
            logger.error("LLM returned empty SQL")
            return None
        
        logger.info(f"Generated SQL: {sql}")
        return LLMResponse(
            sql=sql, answer_type=answer_type, notes=notes, assumptions=assumptions,
            model_name=config.model, chart_hint=chart_hint, summary=summary,
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        return None


def verify_sql_with_llm(
    question: str,
    sql: str,
    schema_context: SchemaContext,
    config: Optional[LLMConfig] = None,
) -> Dict[str, Any]:
    """
    Second-pass SQL validator.
    Returns {"approved": bool, "reason": str, "corrected_sql": Optional[str]}.
    """
    if config is None:
        config = LLMConfig()
    if not config.available:
        return {"approved": True, "reason": "verifier_unavailable", "corrected_sql": None}

    schema_prompt = schema_context.to_prompt_string()
    system_prompt = (
        "You are a strict SQL verifier for PostgreSQL analytics queries. "
        "Check whether SQL matches the business question and schema. "
        "Return ONLY JSON with keys approved (bool), reason (string), corrected_sql (string|null). "
        "Use corrected_sql only if a clear safe fix exists."
    )
    user_prompt = (
        f"{schema_prompt}\n\n"
        f"Question: {question}\n"
        f"Candidate SQL: {sql}\n"
        "Validate joins, filters, grouping, and metric interpretation."
    )
    try:
        if config.provider == "openai":
            response_text = _openai_chat_text(
                config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
                max_tokens=min(350, config.max_tokens),
            )
        else:
            model_name = config.model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
            model = genai.GenerativeModel(model_name)
            gen_response = model.generate_content(
                system_prompt + "\n\n" + user_prompt,
                generation_config={"temperature": 0, "max_output_tokens": min(350, config.max_tokens)},
            )
            response_text = ""
            if getattr(gen_response, "candidates", None):
                for part in gen_response.candidates[0].content.parts:
                    if hasattr(part, "text"):
                        response_text = part.text
                        break
            if not response_text:
                response_text = (getattr(gen_response, "text", "") or "").strip()

        parsed = {}
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", response_text, re.S)
            if m:
                parsed = json.loads(m.group(0))
        approved = bool(parsed.get("approved", True))
        reason = str(parsed.get("reason") or "").strip()[:500]
        corrected = parsed.get("corrected_sql")
        if corrected is not None:
            corrected = str(corrected).strip() or None
        return {"approved": approved, "reason": reason, "corrected_sql": corrected}
    except Exception as e:
        logger.warning(f"SQL verifier skipped due to error: {e}")
        return {"approved": True, "reason": "verifier_error", "corrected_sql": None}
