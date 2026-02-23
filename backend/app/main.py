"""
Application entry point.
Registers routers, configures middleware, runs startup initialization.
"""
from __future__ import annotations

import os
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

load_dotenv()

from app.database import engine, Base
from app import nl_to_sql
from app.insight_engine import InsightEngine
from app.metrics.compiler import compile_metrics

# Import all models so Base.metadata sees every table
import app.models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s","module":"%(name)s"}',
)
logger = logging.getLogger(__name__)

# Insight engine cache (shared with routes_core)
INSIGHT_ENGINES: dict[str, InsightEngine] = {}


def _run_migrations(eng):
    """Add columns to existing tables that were created before the model was updated."""
    migrations = [
        ("datasets", "table_name",   "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS table_name VARCHAR"),
        ("datasets", "schema_type",  "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS schema_type VARCHAR DEFAULT 'static'"),
        ("datasets", "file_path",    "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS file_path VARCHAR"),
        ("datasets", "file_format",  "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS file_format VARCHAR"),
        ("datasets", "column_count", "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS column_count INTEGER"),
        ("conversation_threads", "is_pinned", "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT false"),
        ("conversation_threads", "archived", "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT false"),
        ("conversation_threads", "summary", "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS summary TEXT"),
        ("conversation_threads", "last_message_preview", "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS last_message_preview TEXT"),
        ("conversation_messages", "payload", "ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS payload JSON"),
        # PII classification columns on column_profiles
        ("column_profiles", "pii_type",       "ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_type VARCHAR"),
        ("column_profiles", "pii_confidence",  "ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_confidence FLOAT"),
        ("column_profiles", "pii_action",      "ALTER TABLE column_profiles ADD COLUMN IF NOT EXISTS pii_action VARCHAR DEFAULT 'none'"),
        # Audit log columns
        ("audit_log", "pii_columns_accessed", "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS pii_columns_accessed JSON"),
        ("audit_log", "duration_ms",          "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS duration_ms INTEGER"),
        # Prompt rules
        ("prompt_rules", "applied_count",     "ALTER TABLE prompt_rules ADD COLUMN IF NOT EXISTS applied_count INTEGER DEFAULT 0"),
    ]
    with eng.begin() as conn:
        for table, col, ddl in migrations:
            try:
                conn.execute(text(ddl))
                logger.info(f"Migration: ensured {table}.{col} exists")
            except Exception as e:
                logger.debug(f"Migration skip {table}.{col}: {e}")


def create_db_and_tables():
    try:
        logger.info("Connecting to database to create tables...")
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)
        logger.info("Tables created/migrated successfully.")

        plugins_dir = os.path.join(os.path.dirname(__file__), "..", "..", "plugins")
        nl_to_sql.initialize_plugins(plugins_dir)
        logger.info("Plugin manager initialized.")

        if nl_to_sql.PLUGIN_MANAGER:
            for name, plugin in nl_to_sql.PLUGIN_MANAGER.plugins.items():
                try:
                    with engine.connect() as conn:
                        missing = [t for t in plugin.get_allowed_tables() if not engine.dialect.has_table(conn, t)]
                    if missing:
                        logger.info(f"Skipping metric compilation for {name}; missing tables: {missing}")
                        continue
                    compiled = compile_metrics(plugin)
                    plugin.compiled_views = [c.view_name for c in compiled]
                    plugin.compiled_view_sql = [c.sql for c in compiled]
                    with engine.begin() as conn:
                        for c in compiled:
                            conn.execute(text(c.sql))
                    logger.info(f"Compiled {len(compiled)} metric views for plugin {name}")
                except Exception as e:
                    logger.error(f"Failed compiling metrics for plugin {name}: {e}")

        default_plugin_id = "restaurant"
        if default_plugin_id not in nl_to_sql.PLUGIN_MANAGER.get_plugin_names():
            names = nl_to_sql.PLUGIN_MANAGER.get_plugin_names()
            default_plugin_id = names[0] if names else None

        if default_plugin_id and nl_to_sql.set_active_plugin(default_plugin_id):
            dp = nl_to_sql.get_active_plugin()
            INSIGHT_ENGINES[dp.plugin_name] = InsightEngine(dp)
            logger.info(f"Insight engine initialized for default plugin '{dp.plugin_name}'.")
        else:
            logger.warning("No valid plugin could be activated at startup.")
    except Exception as e:
        logger.error(f"Error initializing plugins: {e}")


# ── App creation ────────────────────────────────────────────────────────

app = FastAPI(on_startup=[create_db_and_tables])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.routes_core import router as core_router  # noqa: E402
from app.routes_v2 import router as v2_router      # noqa: E402
from app.routes_rag import router as rag_router    # noqa: E402
from app.routes_agent import router as agent_router  # noqa: E402
from app.routes_analytics import router as analytics_router  # noqa: E402

# Share insight engines with the core router module
from app import routes_core  # noqa: E402
routes_core.INSIGHT_ENGINES = INSIGHT_ENGINES

app.include_router(core_router)
app.include_router(v2_router)
app.include_router(rag_router)
app.include_router(agent_router)
app.include_router(analytics_router)

# WebSocket endpoint for real-time push notifications
from app.ws_manager import manager as ws_manager  # noqa: E402


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive; clients may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
