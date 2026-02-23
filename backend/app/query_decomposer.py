"""
Query Decomposer — Task 4.1
Breaks complex multi-part questions into parallel sub-queries,
executes them concurrently, then synthesizes a unified answer.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DECOMPOSE_THRESHOLD_WORDS = 2   # keywords that suggest multi-part question
_MAX_SUBQUERIES = 5

MULTI_PART_KEYWORDS = [
    " and ", " vs ", " versus ", " compared to ", " compare ",
    " also ", " additionally ", " as well as ",
    " both ", " each ", " per ", " breakdown ",
    " by region and ", " by category and ", " by product and ",
]


@dataclass
class SubQuery:
    question: str
    index: int
    result: Optional[Any] = None
    error: Optional[str] = None
    sql: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "question": self.question,
            "sql": self.sql,
            "error": self.error,
            "has_result": self.result is not None,
        }


@dataclass
class DecomposedResult:
    original_question: str
    sub_queries: list[SubQuery] = field(default_factory=list)
    synthesized_answer: str = ""
    needs_decomposition: bool = False
    synthesis_sql: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "original_question": self.original_question,
            "needs_decomposition": self.needs_decomposition,
            "sub_queries": [sq.to_dict() for sq in self.sub_queries],
            "synthesized_answer": self.synthesized_answer,
        }


class QueryDecomposer:
    """
    Decomposes complex questions into sub-questions using LLM assistance.
    Falls back to heuristic splitting if LLM unavailable.
    """

    def should_decompose(self, question: str) -> bool:
        """Quick heuristic check before calling LLM."""
        q = question.lower()
        hits = sum(1 for kw in MULTI_PART_KEYWORDS if kw in q)
        return hits >= _DECOMPOSE_THRESHOLD_WORDS

    def decompose_with_llm(
        self,
        question: str,
        schema_summary: str,
        llm_config=None,
    ) -> list[str]:
        """
        Ask LLM to decompose the question into sub-questions.
        Returns list of sub-question strings.
        Falls back to heuristic if LLM unavailable.
        """
        if llm_config is None:
            return self._heuristic_decompose(question)
        try:
            from app.llm_service import generate_text_response
            system = (
                "You are an analytics query planner. "
                "Given a complex question, determine if it needs multiple SQL queries to answer. "
                "If yes, list each sub-question (max 4). Each must be answerable with a single SQL query. "
                "Return JSON: {\"needs_decomposition\": bool, \"sub_questions\": [\"...\", ...]}"
            )
            user = (
                f"Schema summary:\n{schema_summary[:2000]}\n\n"
                f"Question: {question}\n\n"
                "Does this question require multiple SQL queries? If yes, list sub-questions."
            )
            raw = generate_text_response(system, user, config=llm_config, max_tokens=400)
            import json, re
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                parsed = json.loads(m.group(0))
                if parsed.get("needs_decomposition") and parsed.get("sub_questions"):
                    subs = [s for s in parsed["sub_questions"] if s.strip()]
                    return subs[:_MAX_SUBQUERIES]
        except Exception as e:
            logger.debug(f"LLM decomposition failed, using heuristic: {e}")
        return []

    @staticmethod
    def _heuristic_decompose(question: str) -> list[str]:
        """Simple heuristic decomposition — split on 'and' for compound questions."""
        q = question.strip()
        # Split on " and " at the top level (not inside phrases)
        parts = [p.strip() for p in q.split(" and ") if p.strip()]
        if len(parts) < 2:
            return []
        # Reconstruct as standalone questions if needed
        result = []
        for i, part in enumerate(parts[:_MAX_SUBQUERIES]):
            if not part.endswith("?") and not any(
                part.lower().startswith(w) for w in ("show", "what", "how", "which", "give", "list")
            ):
                part = "Show me " + part
            result.append(part)
        return result

    def synthesize(
        self,
        original_question: str,
        sub_results: list[SubQuery],
        llm_config=None,
    ) -> str:
        """Merge results of multiple sub-queries into one coherent narrative."""
        successful = [sq for sq in sub_results if sq.result is not None and not sq.error]
        if not successful:
            return "Unable to answer all parts of the question due to errors."

        if len(successful) == 1:
            return str(successful[0].result)[:500]

        if llm_config is None:
            # Simple text concatenation fallback
            parts = []
            for sq in successful:
                parts.append(f"**{sq.question}**: {str(sq.result)[:200]}")
            return "\n\n".join(parts)

        try:
            from app.llm_service import generate_text_response
            system = (
                "You are a data analyst. Synthesize multiple query results into one coherent answer. "
                "Write 2-4 sentences of plain English covering all the key findings. "
                "Be specific with numbers. Do not use SQL or technical jargon."
            )
            result_summary = "\n".join(
                f"Sub-question {i+1}: {sq.question}\nResult: {str(sq.result)[:300]}"
                for i, sq in enumerate(successful)
            )
            user = f"Original question: {original_question}\n\n{result_summary}"
            return generate_text_response(system, user, config=llm_config, max_tokens=350)
        except Exception as e:
            logger.warning(f"Synthesis LLM call failed: {e}")
            parts = [f"{sq.question}: {str(sq.result)[:150]}" for sq in successful]
            return " | ".join(parts)


async def execute_sub_queries_async(
    sub_questions: list[str],
    execute_fn,   # async callable: (question: str) -> (result, sql, error)
) -> list[SubQuery]:
    """
    Execute sub-queries in parallel using asyncio.gather.
    execute_fn is an async function that runs a single question through the chat pipeline.
    """
    sub_queries = [SubQuery(question=q, index=i) for i, q in enumerate(sub_questions)]

    async def run_one(sq: SubQuery):
        try:
            result, sql, error = await execute_fn(sq.question)
            sq.result = result
            sq.sql = sql
            sq.error = error
        except Exception as e:
            sq.error = str(e)
            logger.warning(f"Sub-query {sq.index} failed: {e}")

    await asyncio.gather(*[run_one(sq) for sq in sub_queries])
    return sub_queries


# Module-level singleton
_decomposer = QueryDecomposer()


def should_decompose(question: str) -> bool:
    return _decomposer.should_decompose(question)


def decompose_question(question: str, schema_summary: str = "", llm_config=None) -> list[str]:
    return _decomposer.decompose_with_llm(question, schema_summary, llm_config)


def synthesize_results(original: str, sub_results: list[SubQuery], llm_config=None) -> str:
    return _decomposer.synthesize(original, sub_results, llm_config)
