import io
import pandas as pd
from google.cloud import storage

BUCKET_NAME = "your-gcs-bucket-name"  # Replace with your actual GCS bucket name

def get_gcs_bucket():
    """Initializes GCS client using default Cloud Run credentials."""
    client = storage.Client()
    return client.bucket(BUCKET_NAME)

def read_excel_from_gcs(blob_path: str) -> pd.DataFrame:
    """Reads an Excel file from GCS directly into a Pandas DataFrame."""
    bucket = get_gcs_bucket()
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return pd.DataFrame()
    
    content = blob.download_as_bytes()
    return pd.read_excel(io.BytesIO(content))

def save_excel_to_gcs(df: pd.DataFrame, blob_path: str, index: bool = False):
    """Writes a Pandas DataFrame to GCS as an Excel file without touching local disk."""
    bucket = get_gcs_bucket()
    blob = bucket.blob(blob_path)
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=index)
    
    blob.upload_from_string(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

def list_gcs_files(prefix: str = "") -> list:
    """Lists file paths (blob names) in GCS matching a given prefix/folder."""
    bucket = get_gcs_bucket()
    blobs = bucket.list_blobs(prefix=prefix)
    return [blob.name for blob in blobs]
