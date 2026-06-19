"""
AWS Lambda: Project File Size Calculator
=========================================
Triggered by S3 ObjectCreated / ObjectRemoved events.
Recalculates the total file size for a project and updates
the PostgreSQL `projects.total_size_bytes` column.

Environment variables required:
  DATABASE_URL  — sync psycopg2 URL (Lambda uses sync driver)
  S3_BUCKET_NAME
  PROJECT_STORAGE_LIMIT_MB  (default: 100)
"""

import json
import logging
import os
import urllib.parse
import uuid

import boto3
import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATABASE_URL = os.environ["DATABASE_URL"]  # e.g. postgresql://user:pass@host/db
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
LIMIT_MB = int(os.environ.get("PROJECT_STORAGE_LIMIT_MB", "100"))
LIMIT_BYTES = LIMIT_MB * 1024 * 1024


def _extract_project_id(s3_key: str) -> uuid.UUID | None:
    """
    S3 key format: projects/<project_uuid>/documents/<doc_uuid>/<filename>
    Returns the project UUID or None if the key doesn't match.
    """
    parts = s3_key.split("/")
    if len(parts) >= 2 and parts[0] == "projects":
        try:
            return uuid.UUID(parts[1])
        except ValueError:
            return None
    return None


def _calculate_project_size(project_id: uuid.UUID) -> int:
    """List all S3 objects for a project and sum their sizes."""
    s3 = boto3.client("s3")
    prefix = f"projects/{project_id}/"
    total = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            total += obj.get("Size", 0)
    return total


def _update_project_size(project_id: uuid.UUID, total_bytes: int) -> None:
    """Update total_size_bytes in PostgreSQL."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE projects SET total_size_bytes = %s, updated_at = NOW() WHERE id = %s",
                (total_bytes, str(project_id)),
            )
            if cur.rowcount == 0:
                logger.warning("Project %s not found in DB — skipping update", project_id)
            else:
                logger.info(
                    "Updated project %s → %d bytes (%.2f MB)",
                    project_id,
                    total_bytes,
                    total_bytes / 1024 / 1024,
                )
            if total_bytes > LIMIT_BYTES:
                logger.warning(
                    "Project %s EXCEEDS storage limit: %.2f MB / %d MB",
                    project_id,
                    total_bytes / 1024 / 1024,
                    LIMIT_MB,
                )
        conn.commit()
    finally:
        conn.close()


def handler(event: dict, context: object) -> dict:
    """Lambda entry point. Processes S3 event records."""
    processed: list[str] = []
    errors: list[str] = []

    for record in event.get("Records", []):
        try:
            raw_key = record["s3"]["object"]["key"]
            s3_key = urllib.parse.unquote_plus(raw_key)
            logger.info("Processing S3 event for key: %s", s3_key)

            project_id = _extract_project_id(s3_key)
            if not project_id:
                logger.info("Key %s does not match project pattern — skipping", s3_key)
                continue

            total_bytes = _calculate_project_size(project_id)
            _update_project_size(project_id, total_bytes)
            processed.append(str(project_id))

        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing record: %s", exc, exc_info=True)
            errors.append(str(exc))

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "processed_projects": list(set(processed)),
                "errors": errors,
            }
        ),
    }
