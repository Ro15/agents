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

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    dataset_id: UUID
    table_name: str
    rows_loaded: int
    load_errors: int
    column_schemas: List[ColumnSchema]
    dataset: Dataset


def save_column_profiles(db: Session, dataset_id: UUID, col_schemas: List[ColumnSchema]):
    """Persist detected column profiles; replaces any existing ones."""
    db.query(ColumnProfile).filter(ColumnProfile.dataset_id == dataset_id).delete()
    for cs in col_schemas:
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

    # 2. Create dynamic table
    tbl_name = create_dataset_table(engine, ds_id, col_schemas, drop_existing=True)

    # 3. Load data
    load_result = load_dataframe(engine, tbl_name, df)

    # 4. Save column profiles
    save_column_profiles(db, ds_id, col_schemas)

    # 5. Register dataset
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

    # 6. Ingestion run record
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
    )
