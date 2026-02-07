"""
Backward-compat re-export — all models now live in app.models.
"""
from app.models import (  # noqa: F401
    ConversationThread, ConversationMessage,
    QueryHistoryEntry, QueryFeedback,
    CustomDashboard, DashboardWidget,
    ScheduledReport, DataConnector,
    ColumnProfile, RateLimitLog, LLMCostLog,
)
