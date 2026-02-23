"""
PII Classifier — Task 3.2
Auto-detects PII columns at upload time and masks values in query results.
Detects: email, phone, SSN, credit card, IP address, name fields.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PIILabel:
    pii_type: str                  # email | phone | ssn | credit_card | ip | name | none
    confidence: float              # 0.0 – 1.0
    action: str = "mask"           # mask | redact | none
    sample_count: int = 0          # how many sample values matched


# ── Regex patterns ───────────────────────────────────────────────────────

_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I
    ),
    "phone": re.compile(
        r"(?:\+?\d[\d\s\-().]{7,}\d)", re.I
    ),
    "ssn": re.compile(
        r"\b\d{3}[-\u2013]\d{2}[-\u2013]\d{4}\b"
    ),
    "credit_card": re.compile(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    ),
    "ip_address": re.compile(
        r"\b\d{1,3}(?:\.\d{1,3}){3}\b"
    ),
}

# Column name heuristics → likely PII types
_COLUMN_NAME_HINTS: dict[str, str] = {
    "email": "email",
    "mail": "email",
    "phone": "phone",
    "mobile": "phone",
    "cell": "phone",
    "tel": "phone",
    "ssn": "ssn",
    "social_security": "ssn",
    "credit_card": "credit_card",
    "card_number": "credit_card",
    "cc_number": "credit_card",
    "ip": "ip_address",
    "ip_address": "ip_address",
    "first_name": "name",
    "last_name": "name",
    "fname": "name",
    "lname": "name",
    "full_name": "name",
    "customer_name": "name",
    "user_name": "name",
    "contact_name": "name",
    "name": "name",
}

_MASK_TEMPLATES: dict[str, str] = {
    "email": "***@***.***",
    "phone": "***-***-****",
    "ssn": "***-**-****",
    "credit_card": "****-****-****-****",
    "ip_address": "***.***.*.*",
    "name": "*** ***",
}


def _mask_value(value: str, pii_type: str) -> str:
    """Mask a single PII value."""
    if pii_type == "email":
        parts = str(value).split("@")
        if len(parts) == 2:
            user = parts[0]
            masked_user = user[0] + "***" if len(user) > 1 else "***"
            domain_parts = parts[1].split(".")
            masked_domain = domain_parts[0][0] + "***" + "." + ".".join(domain_parts[1:]) if domain_parts else "***"
            return f"{masked_user}@{masked_domain}"
    if pii_type == "phone":
        digits = re.sub(r"\D", "", str(value))
        return "*" * max(0, len(digits) - 4) + digits[-4:] if len(digits) > 4 else "****"
    if pii_type == "ssn":
        return "***-**-" + str(value)[-4:] if len(str(value)) >= 4 else "***-**-****"
    if pii_type == "credit_card":
        digits = re.sub(r"\D", "", str(value))
        return "****-****-****-" + digits[-4:] if len(digits) >= 4 else "****-****-****-****"
    if pii_type == "name":
        words = str(value).split()
        return " ".join(w[0] + "***" if w else "***" for w in words[:2])
    return _MASK_TEMPLATES.get(pii_type, "***MASKED***")


class PIIClassifier:
    """
    Classifies DataFrame columns as PII using:
    1. Column name heuristics (fast, high confidence)
    2. Sample value regex matching (slower, content-based)
    """

    def __init__(self, sample_size: int = 200, match_threshold: float = 0.3):
        self.sample_size = sample_size
        self.match_threshold = match_threshold  # fraction of samples that must match

    def classify_columns(self, df: pd.DataFrame) -> dict[str, PIILabel]:
        """
        Returns a mapping of column_name → PIILabel for all PII-positive columns.
        Non-PII columns are returned with pii_type='none', action='none'.
        """
        results: dict[str, PIILabel] = {}
        for col in df.columns:
            label = self._classify_column(df[col], col)
            results[col] = label
        return results

    def _classify_column(self, series: pd.Series, col_name: str) -> PIILabel:
        col_lower = col_name.lower().replace(" ", "_")

        # 1. Name-based heuristic
        for hint_key, hint_type in _COLUMN_NAME_HINTS.items():
            if hint_key in col_lower:
                return PIILabel(pii_type=hint_type, confidence=0.85, action="mask")

        # 2. Content-based regex sampling (only for string-like columns)
        if series.dtype not in (object, "string"):
            return PIILabel(pii_type="none", confidence=1.0, action="none")

        sample = series.dropna().astype(str).head(self.sample_size)
        if len(sample) == 0:
            return PIILabel(pii_type="none", confidence=1.0, action="none")

        best_type = None
        best_confidence = 0.0
        best_count = 0

        for pii_type, pattern in _PATTERNS.items():
            matches = sum(1 for v in sample if pattern.search(v))
            ratio = matches / len(sample)
            if ratio >= self.match_threshold and ratio > best_confidence:
                best_type = pii_type
                best_confidence = ratio
                best_count = matches

        if best_type:
            return PIILabel(
                pii_type=best_type,
                confidence=round(best_confidence, 3),
                action="mask",
                sample_count=best_count,
            )

        return PIILabel(pii_type="none", confidence=1.0, action="none")

    def mask_results(
        self,
        rows: list[dict],
        pii_labels: dict[str, PIILabel],
    ) -> tuple[list[dict], list[str]]:
        """
        Mask PII values in a list of result-row dicts.
        Returns (masked_rows, list_of_masked_column_names).
        """
        masked_cols = [col for col, label in pii_labels.items() if label.action == "mask"]
        if not masked_cols:
            return rows, []

        out = []
        for row in rows:
            new_row = dict(row)
            for col in masked_cols:
                if col in new_row and new_row[col] is not None:
                    pii_type = pii_labels[col].pii_type
                    try:
                        new_row[col] = _mask_value(str(new_row[col]), pii_type)
                    except Exception:
                        new_row[col] = "***MASKED***"
            out.append(new_row)
        return out, masked_cols


# ── Module-level singleton ───────────────────────────────────────────────

_classifier = PIIClassifier()


def classify_dataframe(df: pd.DataFrame) -> dict[str, PIILabel]:
    """Classify all columns of a DataFrame for PII. Returns {col_name: PIILabel}."""
    return _classifier.classify_columns(df)


def mask_rows(rows: list[dict], pii_labels: dict[str, PIILabel]) -> tuple[list[dict], list[str]]:
    """Mask PII values in chat result rows. Returns (masked_rows, masked_col_names)."""
    return _classifier.mask_results(rows, pii_labels)


def pii_labels_from_profiles(col_profiles) -> dict[str, PIILabel]:
    """
    Reconstruct PIILabel dict from persisted ColumnProfile ORM objects.
    Used at query time (after ingestion already classified PII).
    """
    labels: dict[str, PIILabel] = {}
    for cp in col_profiles:
        pii_type = getattr(cp, "pii_type", None) or "none"
        pii_confidence = float(getattr(cp, "pii_confidence", 0.0) or 0.0)
        pii_action = getattr(cp, "pii_action", "none") or "none"
        labels[cp.column_name] = PIILabel(
            pii_type=pii_type,
            confidence=pii_confidence,
            action=pii_action,
        )
    return labels
