import traceback
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from app.main import Dataset, IngestionRun, SalesTransaction, InsightEngine, persist_generated_insights, update_job_status, get_dataset_or_400
from app import nl_to_sql
import pandas as pd
from datetime import datetime


def ingest_sales_job(job_id: UUID, plugin_id: str, file_path: str, dataset_name: str, db_url: str):
    engine = create_engine(db_url)
    SessionLocal = Session(bind=engine)
    db = SessionLocal
    try:
        update_job_status(db, job_id, "RUNNING", progress=5)
        # ensure plugin active
        nl_to_sql.set_active_plugin(plugin_id)
        contents = open(file_path, "rb").read()
        df = pd.read_csv(pd.io.common.BytesIO(contents))
        DEFAULT_COLUMN_MAPPING = {
            'order_id': 'order_id',
            'order_datetime': 'order_datetime',
            'item_name': 'item_name',
            'category': 'category',
            'quantity': 'quantity',
            'item_price': 'item_price',
            'total_line_amount': 'total_line_amount',
            'payment_type': 'payment_type',
            'discount_amount': 'discount_amount',
            'tax_amount': 'tax_amount',
        }
        REQUIRED_COLUMNS = ['order_id', 'order_datetime', 'item_name', 'quantity', 'item_price', 'total_line_amount']
        df.rename(columns=DEFAULT_COLUMN_MAPPING, inplace=True)
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
        df['order_datetime'] = pd.to_datetime(df['order_datetime'])

        dataset_obj = Dataset(plugin_id=plugin_id, dataset_name=dataset_name, created_at=datetime.utcnow())
        db.add(dataset_obj)
        db.commit()
        db.refresh(dataset_obj)
        df['dataset_id'] = dataset_obj.dataset_id
        df.to_sql(SalesTransaction.__tablename__, engine, if_exists='append', index=False)
        dataset_obj.last_ingested_at = datetime.utcnow()
        dataset_obj.row_count = len(df)
        dataset_obj.version = (dataset_obj.version or 1) + 1
        db.add(dataset_obj)

        ingestion_record = IngestionRun(
            dataset_name="sales",
            filename=file_path,
            row_count=len(df),
            plugin_id=plugin_id,
            dataset_id=dataset_obj.dataset_id,
        )
        db.add(ingestion_record)
        db.commit()

        result = {
            "dataset_id": str(dataset_obj.dataset_id),
            "row_count": dataset_obj.row_count,
            "plugin": plugin_id,
            "ingested_at": dataset_obj.last_ingested_at.isoformat(),
        }
        update_job_status(db, job_id, "SUCCEEDED", result=result, progress=100)
    except Exception as e:
        update_job_status(db, job_id, "FAILED", failure=str(e), trace=traceback.format_exc())
    finally:
        db.close()


def run_insights_job(job_id: UUID, plugin_id: str, dataset_id: str, limit: int, db_url: str):
    engine = create_engine(db_url)
    SessionLocal = Session(bind=engine)
    db = SessionLocal
    try:
        update_job_status(db, job_id, "RUNNING", progress=5)
        nl_to_sql.set_active_plugin(plugin_id)
        ds = get_dataset_or_400(db, dataset_id, plugin_id)
        engine_i = InsightEngine(nl_to_sql.get_active_plugin())
        generated = engine_i.run_all_insights(db, dataset_id=str(ds.dataset_id))
        if limit:
            generated = generated[:limit]
        run_id = persist_generated_insights(db, generated, plugin_id, dataset_id)
        result = {"insights_run_id": str(run_id), "count": len(generated)}
        update_job_status(db, job_id, "SUCCEEDED", result=result, progress=100)
    except Exception as e:
        update_job_status(db, job_id, "FAILED", failure=str(e), trace=traceback.format_exc())
    finally:
        db.close()
