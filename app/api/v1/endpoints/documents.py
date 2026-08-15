import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.models import Document, User
from app.schemas.schemas import (
    DocumentDownloadResponse,
    DocumentMetadataPatch,
    DocumentOut,
)
from app.services.document_service import (
    delete_document,
    get_document_download_url,
    patch_document_metadata,
    update_document,
    upload_documents,
)
from app.services.project_service import get_project_with_access

router = APIRouter(tags=["documents"])


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[DocumentOut],
    summary="List all documents in a project",
)
async def list_documents_endpoint(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    project, _ = await get_project_with_access(project_id, current_user, db)
    return project.documents


@router.post(
    "/projects/{project_id}/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more documents to a project",
)
async def upload_documents_endpoint(
    project_id: uuid.UUID,
    files: list[UploadFile] = File(..., description="PDF or DOCX files"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    return await upload_documents(project_id, files, current_user, db)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDownloadResponse,
    summary="Get presigned download URL for a document",
)
async def download_document_endpoint(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownloadResponse:
    doc, url = await get_document_download_url(document_id, current_user, db)
    return DocumentDownloadResponse(
        download_url=url,
        filename=doc.filename,
        expires_in=3600,
    )


@router.put(
    "/documents/{document_id}",
    response_model=DocumentOut,
    summary="Replace a document file",
)
async def update_document_endpoint(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    return await update_document(document_id, file, current_user, db)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document (owner only)",
)
async def delete_document_endpoint(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await delete_document(document_id, current_user, db)


@router.patch(
    "/documents/{document_id}/metadata",
    response_model=DocumentOut,
    summary="Rename a document (metadata only, no file replacement)",
)
async def patch_document_metadata_endpoint(
    document_id: uuid.UUID,
    payload: DocumentMetadataPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    return await patch_document_metadata(document_id, payload.filename, current_user, db)
