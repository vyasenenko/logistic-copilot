"""S3-compatible storage service (works with MinIO/DO Spaces/AWS S3)."""

import io
from uuid import uuid4

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(signature_version="s3v4"),
        )
        # Ensure bucket exists
        try:
            _client.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            _client.create_bucket(Bucket=settings.s3_bucket)
    return _client


def upload_file(data: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
    """Upload a file to S3 and return the public URL.

    Returns the full path key (e.g., 'uploads/abc123/video.mp4').
    """
    client = _get_client()
    key = f"uploads/{uuid4().hex[:12]}/{filename}"

    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    return key


def upload_file_obj(file_obj: io.BytesIO, key: str, content_type: str = "application/octet-stream") -> str:
    """Upload a file-like object to S3."""
    client = _get_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=file_obj.getvalue(),
        ContentType=content_type,
    )
    return key


def get_public_url(key: str) -> str:
    """Get the public URL for a stored file."""
    return f"{settings.s3_public_url}/{key}"


def download_file(key: str) -> bytes:
    """Download a file from S3."""
    client = _get_client()
    response = client.get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()


def list_user_videos(prefix: str = "uploads/") -> list[dict]:
    """List all uploaded video files."""
    client = _get_client()
    response = client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix)

    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith((".mp4", ".mov", ".webm", ".avi")):
            files.append({
                "key": key,
                "url": get_public_url(key),
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            })
    return files
