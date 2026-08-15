import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, NotFoundError

settings = get_settings()


def get_s3_client() -> Any:
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        aws_session_token=settings.aws_session_token,
    )


def build_s3_key(project_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> str:
    return f"projects/{project_id}/documents/{document_id}/{filename}"


def upload_file_to_s3(
    file_data: bytes,
    s3_key: str,
    content_type: str,
) -> None:
    """Upload raw bytes to S3."""
    client = get_s3_client()
    try:
        client.put_object(
            Bucket=settings.s3_bucket_name,
            Key=s3_key,
            Body=file_data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
    except ClientError as e:
        raise BadRequestError(f"S3 upload failed: {e.response['Error']['Message']}") from e


def generate_presigned_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for downloading a document."""
    client = get_s3_client()
    try:
        url: str = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": s3_key},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError as e:
        raise NotFoundError(
            f"Could not generate download URL: {e.response['Error']['Message']}"
        ) from e


def delete_file_from_s3(s3_key: str) -> None:
    """Delete a single object from S3."""
    client = get_s3_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)
    except ClientError as e:
        # Log but don't raise — object may already be gone
        print(f"[S3] Warning: could not delete {s3_key}: {e.response['Error']['Message']}")


def delete_project_folder_from_s3(project_id: uuid.UUID) -> None:
    """Delete all S3 objects under a project's prefix."""
    client = get_s3_client()
    prefix = f"projects/{project_id}/"
    paginator = client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=prefix)

    objects_to_delete: list[dict[str, str]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            objects_to_delete.append({"Key": obj["Key"]})

    if objects_to_delete:
        client.delete_objects(
            Bucket=settings.s3_bucket_name,
            Delete={"Objects": objects_to_delete, "Quiet": True},
        )
