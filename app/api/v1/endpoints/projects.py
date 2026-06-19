import math
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.schemas.schemas import (
    InviteRequest,
    MessageResponse,
    PageMeta,
    ProjectCreate,
    ProjectInfoOut,
    ProjectOut,
    ProjectPage,
    ProjectSearchParams,
    ProjectUpdate,
)
from app.services.notification_service import notify_project_deleted, notify_user_invited
from app.services.project_service import (
    create_project,
    delete_project,
    get_project_with_access,
    invite_user,
    list_project_members,
    list_user_projects,
    update_project,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project_endpoint(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    return await create_project(payload, current_user, db)


@router.get(
    "",
    response_model=ProjectPage,
    summary="List / search projects (paginated). Use ?search=term to filter by name or description.",
)
async def list_projects_endpoint(
    search: str | None = Query(default=None, max_length=128, description="Filter by name or description"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectPage:
    params = ProjectSearchParams(search=search, page=page, size=size)
    items, total = await list_user_projects(current_user, db, params)
    return ProjectPage(
        items=items,
        meta=PageMeta(
            page=page,
            size=size,
            total=total,
            pages=math.ceil(total / size) if total else 0,
        ),
    )


@router.get(
    "/{project_id}/info",
    response_model=ProjectInfoOut,
    summary="Get project details",
)
async def get_project_info_endpoint(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    project, _ = await get_project_with_access(project_id, current_user, db)
    return project


@router.put(
    "/{project_id}/info",
    response_model=ProjectInfoOut,
    summary="Update project name or description",
)
async def update_project_endpoint(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    return await update_project(project_id, payload, current_user, db)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project (owner only)",
)
async def delete_project_endpoint(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project_name, member_logins = await delete_project(project_id, current_user, db)
    if member_logins:
        background_tasks.add_task(
            notify_project_deleted,
            owner_login=current_user.login,
            project_name=project_name,
            member_logins=member_logins,
        )


@router.get(
    "/{project_id}/members",
    response_model=list[dict],
    summary="List all members of a project",
)
async def list_members_endpoint(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await list_project_members(project_id, current_user, db)


@router.post(
    "/{project_id}/invite",
    response_model=MessageResponse,
    summary="Invite a user to the project (owner only)",
)
async def invite_user_endpoint(
    project_id: uuid.UUID,
    payload: InviteRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    _, project_name = await invite_user(project_id, payload.user_login, current_user, db)
    background_tasks.add_task(
        notify_user_invited,
        invitee_login=payload.user_login,
        project_name=project_name,
        inviter_login=current_user.login,
    )
    return MessageResponse(message=f"User '{payload.user_login}' successfully invited")
