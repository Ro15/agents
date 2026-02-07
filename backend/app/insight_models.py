"""
Insight models (dataclasses) shared by the insight engine.
Keeps business structures separate from transport / persistence concerns.
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass
class InsightMetric:
    """Represents a metric value within an insight."""
    name: str
    value: Any
    unit: str = ""
    change_percent: Optional[float] = None
    comparison_period: str = ""


@dataclass
class InsightDefinition:
    """Represents an insight rule from insights.yaml."""
    insight_id: str
    title: str
    description: str
    required_metrics: List[str]
    sql_queries: Dict[str, Any]  # query_id -> SQL block/template
    trigger_condition: Dict[str, Any]  # condition logic
    severity: str  # "info", "warning", "critical"
    explanation_template: str
    data_window: str  # e.g., "last 7 days vs previous 7 days"
    required_columns: List[str] = None


@dataclass
class GeneratedInsight:
    """Represents a generated insight."""
    insight_id: str
    title: str
    severity: str
    summary: str
    details: str
    metrics: Dict[str, Any]
    sql: Dict[str, str]
    data_window: str
    confidence: str
    plugin: str
    generated_at: str
