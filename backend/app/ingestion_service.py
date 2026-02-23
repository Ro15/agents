"""
Ingestion service — shared pipeline used by both the /upload endpoint
and the /connectors/sync endpoint.  Keeps route handlers thin.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Dataset, ColumnProfile, IngestionRun
from app.schema_detector import detect_schema, ColumnSchema
from app.table_manager import create_dataset_table
from app.data_loader import load_dataframe
from app.pii_classifier import classify_dataframe
from app.schema_drift import compare_profiles_from_orm

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    dataset_id: UUID
    table_name: str
    rows_loaded: int
    load_errors: int
    column_schemas: List[ColumnSchema]
    dataset: Dataset
    drift_report: Optional[object] = None   # DriftReport or None
    pii_summary: Optional[dict] = None      # {col: pii_type}


def save_column_profiles(db: Session, dataset_id: UUID, col_schemas: List[ColumnSchema], pii_labels: Optional[dict] = None):
    """Persist detected column profiles with PII labels; replaces any existing ones."""
    db.query(ColumnProfile).filter(ColumnProfile.dataset_id == dataset_id).delete()
    for cs in col_schemas:
        pii = (pii_labels or {}).get(cs.name)
        db.add(ColumnProfile(
            dataset_id=dataset_id,
            column_name=cs.name,
            data_type=cs.pg_type,
            null_count=cs.null_count,
            distinct_count=cs.distinct_count,
            min_value=cs.min_value,
            max_value=cs.max_value,
            mean_value=cs.mean_value,
            sample_values=cs.sample_values,
            pii_type=pii.pii_type if pii and pii.pii_type != "none" else None,
            pii_confidence=pii.confidence if pii and pii.pii_type != "none" else None,
            pii_action=pii.action if pii and pii.pii_type != "none" else "none",
        ))


def register_dataset(
    db: Session,
    *,
    dataset_id: UUID,
    plugin_id: str,
    name: str,
    table_name: str,
    rows_loaded: int,
    column_count: int,
    source_filename: str,
    file_path: Optional[str] = None,
    file_format: Optional[str] = None,
) -> Dataset:
    """Create or update a Dataset record for a dynamic ingestion."""
    now = datetime.utcnow()
    existing = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if existing:
        ds = existing
    else:
        ds = Dataset(dataset_id=dataset_id, plugin_id=plugin_id, dataset_name=name, created_at=now)
    ds.plugin_id = plugin_id
    ds.dataset_name = name
    ds.last_ingested_at = now
    ds.row_count = rows_loaded
    ds.source_filename = source_filename
    ds.is_deleted = False
    ds.version = (ds.version or 0) + 1
    ds.table_name = table_name
    ds.schema_type = "dynamic"
    ds.file_path = file_path
    ds.file_format = file_format
    ds.column_count = column_count
    return db.merge(ds)


def run_ingestion_pipeline(
    engine: Engine,
    db: Session,
    df: pd.DataFrame,
    *,
    dataset_id: Optional[UUID] = None,
    plugin_id: str = "default",
    name: str = "Untitled",
    source_filename: str = "",
    file_path: Optional[str] = None,
    file_format: Optional[str] = None,
) -> IngestionResult:
    """
    Complete ingestion pipeline:
      1. Detect schema
      2. Create dynamic table
      3. Load data
      4. Save column profiles
      5. Register dataset metadata
      6. Record ingestion run

    Returns an IngestionResult with all the details.
    """
    ds_id = dataset_id or uuid4()

    # 1. Detect schema
    col_schemas = detect_schema(df)

    # 2. PII classification on the incoming DataFrame
    try:
        pii_labels = classify_dataframe(df)
        pii_summary = {
            col: label.pii_type
            for col, label in pii_labels.items()
            if label.pii_type != "none"
        }
        if pii_summary:
            logger.info(f"PII detected in dataset {ds_id}: {pii_summary}")
    except Exception as e:
        logger.warning(f"PII classification failed (non-blocking): {e}")
        pii_labels = {}
        pii_summary = {}

    # 3. Schema drift detection (compare to previous version if exists)
    drift_report = None
    old_row_count = 0
    try:
        existing_profiles = db.query(ColumnProfile).filter(
            ColumnProfile.dataset_id == ds_id
        ).all()
        existing_ds = db.query(Dataset).filter(Dataset.dataset_id == ds_id).first()
        old_row_count = (existing_ds.row_count or 0) if existing_ds else 0
        if existing_profiles:
            drift_report = compare_profiles_from_orm(
                dataset_id=str(ds_id),
                old_col_profiles=existing_profiles,
                new_col_schemas=col_schemas,
                old_row_count=old_row_count,
                new_row_count=len(df),
            )
            if drift_report.has_warnings:
                # Persist drift events
                from app.models import SchemaDriftEvent
                for evt in drift_report.events:
                    db.add(SchemaDriftEvent(
                        dataset_id=str(ds_id),
                        drift_type=evt.drift_type,
                        column_name=evt.column_name,
                        old_value=evt.old_value,
                        new_value=evt.new_value,
                        severity=evt.severity,
                    ))
    except Exception as e:
        logger.warning(f"Schema drift detection failed (non-blocking): {e}")

    # 4. Create dynamic table
    tbl_name = create_dataset_table(engine, ds_id, col_schemas, drop_existing=True)

    # 5. Load data
    load_result = load_dataframe(engine, tbl_name, df)

    # 6. Register dataset first so FK-dependent rows can reference it.
    ds_obj = register_dataset(
        db,
        dataset_id=ds_id,
        plugin_id=plugin_id,
        name=name,
        table_name=tbl_name,
        rows_loaded=load_result["rows_loaded"],
        column_count=len(col_schemas),
        source_filename=source_filename,
        file_path=file_path,
        file_format=file_format,
    )
    db.flush()

    # 7. Save column profiles with PII labels
    save_column_profiles(db, ds_id, col_schemas, pii_labels=pii_labels)

    # 8. Ingestion run record
    db.add(IngestionRun(
        dataset_name=name,
        filename=source_filename,
        row_count=load_result["rows_loaded"],
        plugin_id=plugin_id,
        dataset_id=ds_id,
    ))

    db.commit()
    db.refresh(ds_obj)

    return IngestionResult(
        dataset_id=ds_id,
        table_name=tbl_name,
        rows_loaded=load_result["rows_loaded"],
        load_errors=load_result["errors"],
        column_schemas=col_schemas,
        dataset=ds_obj,
        drift_report=drift_report,
        pii_summary=pii_summary,
    )
