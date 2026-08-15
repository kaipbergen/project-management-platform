import os
import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError, StorageLimitError
from app.models.models import Document, User
from app.schemas.schemas import ALLOWED_EXTENSIONS
from app.services.project_service import get_project_with_access
from app.services.s3_service import (
    build_s3_key,
    delete_file_from_s3,
    generate_presigned_download_url,
    upload_file_to_s3,
)

settings = get_settings()

LIMIT_BYTES = settings.project_storage_limit_mb * 1024 * 1024


def _validate_file(file: UploadFile) -> None:
    if not file.filename:
        raise BadRequestError("File must have a filename")
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise BadRequestError(
            f"File type '{ext}' not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}"
        )


async def upload_documents(
    project_id: uuid.UUID,
    files: list[UploadFile],
    user: User,
    db: AsyncSession,
) -> list[Document]:
    project, membership = await get_project_with_access(project_id, user, db)

    uploaded: list[Document] = []
    for file in files:
        _validate_file(file)
        data = await file.read()
        file_size = len(data)

        # Check storage limit
        new_total = project.total_size_bytes + file_size
        if new_total > LIMIT_BYTES:
            raise StorageLimitError(
                f"Upload would exceed {settings.project_storage_limit_mb}MB project limit. "
                f"Current: {project.total_size_bytes / 1024 / 1024:.1f}MB, "
                f"File: {file_size / 1024 / 1024:.2f}MB"
            )

        doc_id = uuid.uuid4()
        s3_key = build_s3_key(project_id, doc_id, file.filename or "unknown")
        content_type = file.content_type or "application/octet-stream"

        upload_file_to_s3(data, s3_key, content_type)

        doc = Document(
            id=doc_id,
            project_id=project_id,
            filename=file.filename or "unknown",
            s3_key=s3_key,
            content_type=content_type,
            size_bytes=file_size,
            uploaded_by_id=user.id,
        )
        db.add(doc)
        project.total_size_bytes = new_total
        uploaded.append(doc)

    await db.flush()
    return uploaded


async def get_document_download_url(
    document_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> tuple[Document, str]:
    result = await db.execute(
        select(Document).options(selectinload(Document.project)).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")

    # Verify project access
    await get_project_with_access(doc.project_id, user, db)

    url = generate_presigned_download_url(doc.s3_key)
    return doc, url


async def update_document(
    document_id: uuid.UUID,
    file: UploadFile,
    user: User,
    db: AsyncSession,
) -> Document:
    result = await db.execute(
        select(Document).options(selectinload(Document.project)).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")

    project, membership = await get_project_with_access(doc.project_id, user, db)

    _validate_file(file)
    data = await file.read()
    new_size = len(data)

    # Check storage limit with size delta
    size_delta = new_size - doc.size_bytes
    new_total = project.total_size_bytes + size_delta
    if new_total > LIMIT_BYTES:
        raise StorageLimitError(
            f"Update would exceed {settings.project_storage_limit_mb}MB project limit"
        )

    # Delete old S3 object and upload new one
    delete_file_from_s3(doc.s3_key)

    new_s3_key = build_s3_key(doc.project_id, document_id, file.filename or doc.filename)
    content_type = file.content_type or "application/octet-stream"
    upload_file_to_s3(data, new_s3_key, content_type)

    doc.filename = file.filename or doc.filename
    doc.s3_key = new_s3_key
    doc.content_type = content_type
    doc.size_bytes = new_size
    project.total_size_bytes = new_total

    await db.flush()
    return doc


async def delete_document(
    document_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> None:
    result = await db.execute(
        select(Document).options(selectinload(Document.project)).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")

    project, membership = await get_project_with_access(doc.project_id, user, db)

    # Only owner can delete documents
    if membership.role != "owner":
        raise ForbiddenError("Only the project owner can delete documents")

    delete_file_from_s3(doc.s3_key)
    project.total_size_bytes = max(0, project.total_size_bytes - doc.size_bytes)
    await db.delete(doc)
    await db.flush()
    # Expire the project so the `documents` relationship is reloaded fresh
    # on any subsequent access within the same session (e.g. in tests)
    await db.refresh(project)


async def patch_document_metadata(
    document_id: uuid.UUID,
    filename: str,
    user: User,
    db: AsyncSession,
) -> Document:
    """Rename a document (metadata only, no S3 key change)."""
    result = await db.execute(
        select(Document).options(selectinload(Document.project)).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")

    # Any member can rename (only owner can delete)
    await get_project_access(doc.project_id, user, db)

    doc.filename = filename
    await db.flush()
    return doc


async def get_project_access(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> None:
    """Lightweight access check without loading full project relationships."""
    from app.services.project_service import get_project_with_access

    await get_project_with_access(project_id, user, db)
