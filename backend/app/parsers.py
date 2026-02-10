"""
Universal file parser — dispatches by extension and returns a pandas DataFrame.
Supported formats: CSV, Excel (.xlsx/.xls), JSON, JSONL.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Extension → parser mapping
_EXT_MAP = {
    ".csv": "csv",
    ".tsv": "csv",
    ".xlsx": "excel",
    ".xls": "excel",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
}

SUPPORTED_EXTENSIONS = set(_EXT_MAP.keys())


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case, strip, replace spaces/hyphens with underscores."""
    df.columns = [
        re.sub(r"[^a-z0-9_]", "_", col.strip().lower()).strip("_")
        for col in df.columns
    ]
    # Deduplicate column names
    seen: dict[str, int] = {}
    new_cols = []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            new_cols.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            new_cols.append(c)
    df.columns = new_cols
    return df


def _parse_csv(buf: io.BytesIO, **kwargs) -> pd.DataFrame:
    sep = kwargs.get("sep")
    if sep is None:
        sample = buf.read(4096).decode("utf-8", errors="replace")
        buf.seek(0)
        if "\t" in sample and "," not in sample:
            sep = "\t"
        else:
            sep = ","
    return pd.read_csv(buf, sep=sep, low_memory=False)


def _parse_excel(buf: io.BytesIO, **kwargs) -> pd.DataFrame:
    sheet = kwargs.get("sheet_name", 0)
    return pd.read_excel(buf, sheet_name=sheet, engine="openpyxl")


def _parse_json(buf: io.BytesIO, **kwargs) -> pd.DataFrame:
    raw = buf.read()
    text = raw.decode("utf-8")
    try:
        return pd.read_json(io.StringIO(text))
    except ValueError:
        # Nested JSON → flatten
        import json as _json
        obj = _json.loads(text)
        if isinstance(obj, list):
            return pd.json_normalize(obj)
        elif isinstance(obj, dict):
            # Heuristic: find the first key whose value is a list
            for k, v in obj.items():
                if isinstance(v, list) and len(v) > 0:
                    return pd.json_normalize(v)
            return pd.json_normalize(obj)
        raise


def _parse_jsonl(buf: io.BytesIO, **kwargs) -> pd.DataFrame:
    return pd.read_json(buf, lines=True)


_PARSERS = {
    "csv": _parse_csv,
    "excel": _parse_excel,
    "json": _parse_json,
    "jsonl": _parse_jsonl,
}


def parse_file(
    content: bytes,
    filename: str,
    *,
    sheet_name: Optional[str | int] = None,
) -> pd.DataFrame:
    """
    Parse a file into a DataFrame.

    Raises ValueError if the file type is unsupported or parsing fails.
    """
    ext = Path(filename).suffix.lower()
    fmt = _EXT_MAP.get(ext)
    if not fmt:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    parser = _PARSERS[fmt]
    kwargs = {}
    if sheet_name is not None and fmt == "excel":
        kwargs["sheet_name"] = sheet_name

    try:
        buf = io.BytesIO(content)
        df = parser(buf, **kwargs)
    except Exception as e:
        raise ValueError(f"Failed to parse {filename}: {e}") from e

    if df.empty:
        raise ValueError(f"File {filename} produced an empty DataFrame")

    df = _normalise_columns(df)
    logger.info(f"Parsed {filename}: {len(df)} rows × {len(df.columns)} cols")
    return df
