import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.models import User
from app.schemas.schemas import StorageInfoResponse
from app.services.project_service import get_project_with_access

router = APIRouter(tags=["utils"])
settings = get_settings()


@router.get(
    "/projects/{project_id}/storage",
    response_model=StorageInfoResponse,
    summary="Get storage usage for a project",
)
async def project_storage_info(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StorageInfoResponse:
    project, _ = await get_project_with_access(project_id, current_user, db)
    total_mb = project.total_size_bytes / 1024 / 1024
    usage_pct = (total_mb / settings.project_storage_limit_mb) * 100
    return StorageInfoResponse(
        project_id=project.id,
        total_size_bytes=project.total_size_bytes,
        total_size_mb=round(total_mb, 3),
        limit_mb=settings.project_storage_limit_mb,
        usage_percent=round(usage_pct, 1),
    )
