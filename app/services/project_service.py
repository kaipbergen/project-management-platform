import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.models import Project, ProjectMember, User
from app.schemas.schemas import ProjectCreate, ProjectSearchParams, ProjectUpdate


async def get_project_with_access(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    *,
    require_owner: bool = False,
) -> tuple[Project, ProjectMember]:
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.documents), selectinload(Project.members))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    membership = member_result.scalar_one_or_none()
    if not membership:
        raise ForbiddenError("You do not have access to this project")

    if require_owner and membership.role != "owner":
        raise ForbiddenError("Only the project owner can perform this action")

    return project, membership


async def create_project(payload: ProjectCreate, owner: User, db: AsyncSession) -> Project:
    project = Project(
        name=payload.name,
        description=payload.description,
        owner_id=owner.id,
    )
    db.add(project)
    await db.flush()

    membership = ProjectMember(
        project_id=project.id,
        user_id=owner.id,
        role="owner",
    )
    db.add(membership)
    await db.flush()

    result = await db.execute(
        select(Project)
        .options(selectinload(Project.documents), selectinload(Project.members))
        .where(Project.id == project.id)
    )
    return result.scalar_one()


async def list_user_projects(
    user: User,
    db: AsyncSession,
    params: ProjectSearchParams,
) -> tuple[list[Project], int]:
    """
    Returns (items, total) — supports optional full-text search on name + description.
    Search is case-insensitive substring match (ilike). Works on both PostgreSQL and SQLite.
    """
    base_query = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
    )

    if params.search:
        term = f"%{params.search}%"
        base_query = base_query.where(
            or_(
                Project.name.ilike(term),
                Project.description.ilike(term),
            )
        )

    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.options(selectinload(Project.documents))
        .order_by(Project.created_at.desc())
        .offset(params.offset)
        .limit(params.size)
    )
    return list(result.scalars().all()), total


async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: User,
    db: AsyncSession,
) -> Project:
    project, _ = await get_project_with_access(project_id, user, db)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description

    await db.flush()
    return project


async def delete_project(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> tuple[str, list[str]]:
    project, _ = await get_project_with_access(project_id, user, db, require_owner=True)

    members_result = await db.execute(
        select(User.login)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id != user.id,
        )
    )
    member_logins = list(members_result.scalars().all())
    project_name = project.name

    await db.delete(project)
    await db.flush()
    return project_name, member_logins


async def invite_user(
    project_id: uuid.UUID,
    invitee_login: str,
    requester: User,
    db: AsyncSession,
) -> tuple[ProjectMember, str]:
    project, _ = await get_project_with_access(project_id, requester, db, require_owner=True)

    result = await db.execute(select(User).where(User.login == invitee_login))
    invitee = result.scalar_one_or_none()
    if not invitee:
        raise NotFoundError(f"User '{invitee_login}' not found")

    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == invitee.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"User '{invitee_login}' is already a member of this project")

    membership = ProjectMember(
        project_id=project_id,
        user_id=invitee.id,
        role="participant",
    )
    db.add(membership)
    await db.flush()
    return membership, project.name


async def list_project_members(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    await get_project_with_access(project_id, user, db)

    result = await db.execute(
        select(User.login, ProjectMember.role, ProjectMember.joined_at)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.joined_at)
    )
    return [
        {"login": row.login, "role": row.role, "joined_at": row.joined_at} for row in result.all()
    ]
