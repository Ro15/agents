"""
Backward-compat re-export — all models now live in app.models.
"""
from app.models import (  # noqa: F401
    ConversationThread, ConversationMessage,
    ConversationMemory,
    KnowledgeDocument, KnowledgeChunk, RAGExample, HumanReviewQueue,
    AgentUserProfile, AgentGoal, AgentPlanStep, AgentAutomation,
    QueryHistoryEntry, QueryFeedback,
    CustomDashboard, DashboardWidget,
    ScheduledReport, DataConnector,
    ColumnProfile, RateLimitLog, LLMCostLog,
)
