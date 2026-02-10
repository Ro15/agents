"""Cloud storage connector — reads files from S3, GCS, or Azure Blob."""
from __future__ import annotations

import io
import logging
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class CloudStorageConnector(BaseConnector):
    connector_type = "cloud_storage"

    def __init__(self, config: dict):
        super().__init__(config)
        self.provider = config.get("provider", "s3")  # "s3", "gcs", "azure"
        self.bucket = config.get("bucket", "")
        self.prefix = config.get("prefix", "")
        self.region = config.get("region", "us-east-1")
        # Auth
        self.access_key = config.get("access_key")
        self.secret_key = config.get("secret_key")
        self.connection_string = config.get("connection_string")
        self.credentials_json = config.get("credentials_json")

    def _list_s3(self) -> List[str]:
        try:
            import boto3
        except ImportError:
            raise RuntimeError("Install 'boto3' to use S3 connector")
        kwargs = {"region_name": self.region}
        if self.access_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        s3 = boto3.client("s3", **kwargs)
        resp = s3.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix, MaxKeys=100)
        return [obj["Key"] for obj in resp.get("Contents", []) if not obj["Key"].endswith("/")]

    def _read_s3(self, key: str) -> bytes:
        import boto3
        kwargs = {"region_name": self.region}
        if self.access_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        s3 = boto3.client("s3", **kwargs)
        obj = s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def _list_gcs(self) -> List[str]:
        try:
            from google.cloud import storage as gcs
        except ImportError:
            raise RuntimeError("Install 'google-cloud-storage' to use GCS connector")
        client = gcs.Client()
        blobs = client.list_blobs(self.bucket, prefix=self.prefix, max_results=100)
        return [b.name for b in blobs if not b.name.endswith("/")]

    def _read_gcs(self, key: str) -> bytes:
        from google.cloud import storage as gcs
        client = gcs.Client()
        blob = client.bucket(self.bucket).blob(key)
        return blob.download_as_bytes()

    def _list_azure(self) -> List[str]:
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            raise RuntimeError("Install 'azure-storage-blob' to use Azure connector")
        service = BlobServiceClient.from_connection_string(self.connection_string)
        container = service.get_container_client(self.bucket)
        return [b.name for b in container.list_blobs(name_starts_with=self.prefix)]

    def _read_azure(self, key: str) -> bytes:
        from azure.storage.blob import BlobServiceClient
        service = BlobServiceClient.from_connection_string(self.connection_string)
        blob = service.get_blob_client(self.bucket, key)
        return blob.download_blob().readall()

    def test_connection(self) -> tuple[str, str]:
        try:
            files = self.fetch_tables()
            return "connected", f"Found {len(files)} files in {self.provider}://{self.bucket}/{self.prefix}"
        except Exception as e:
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        if self.provider == "s3":
            return self._list_s3()
        elif self.provider == "gcs":
            return self._list_gcs()
        elif self.provider == "azure":
            return self._list_azure()
        raise ValueError(f"Unknown cloud provider: {self.provider}")

    def fetch_schema(self, table: str) -> List[dict]:
        df = self.extract_data(table, limit=10)
        return [{"name": c, "type": str(df[c].dtype), "nullable": True} for c in df.columns]

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        key = table_or_query
        if self.provider == "s3":
            content = self._read_s3(key)
        elif self.provider == "gcs":
            content = self._read_gcs(key)
        elif self.provider == "azure":
            content = self._read_azure(key)
        else:
            raise ValueError(f"Unknown cloud provider: {self.provider}")

        # Parse based on extension
        from app.parsers import parse_file
        df = parse_file(content, key)
        if limit:
            df = df.head(limit)
        return df
