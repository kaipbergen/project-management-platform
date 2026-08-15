"""
Project share-link service (optional spec feature):
GET /projects/{id}/share?with=<email> -> hashed join token + link
GET /join?token=<raw token>           -> redeem, grants participant access

Mirrors the refresh-token pattern in token_service.py: the raw token is
returned to the caller once and only its SHA-256 hash is stored, so a leaked
DB dump can't be used to forge join links.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.models.models import Project, ProjectMember, ProjectShareToken, User
from app.services.project_service import get_project_with_access

SHARE_TOKEN_BYTES = 32
SHARE_TOKEN_EXPIRE_HOURS = 72


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_share_token(
    project_id: uuid.UUID,
    invited_email: str,
    requester: User,
    db: AsyncSession,
) -> tuple[str, datetime, Project]:
    """Owner-only. Returns (raw_token, expires_at, project)."""
    project, _ = await get_project_with_access(project_id, requester, db, require_owner=True)

    raw_token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SHARE_TOKEN_EXPIRE_HOURS)

    share = ProjectShareToken(
        project_id=project.id,
        invited_email=invited_email,
        token_hash=_hash_token(raw_token),
        expires_at=expires_at,
    )
    db.add(share)
    await db.flush()

    return raw_token, expires_at, project


async def redeem_share_token(raw_token: str, user: User, db: AsyncSession) -> ProjectMember:
    """Authenticated user opens the join link — grants participant access."""
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(ProjectShareToken).where(ProjectShareToken.token_hash == token_hash)
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise NotFoundError("Invalid or unknown join link")
    if share.expires_at.replace(tzinfo=timezone.utc) < now:
        raise UnauthorizedError("Join link has expired")

    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == share.project_id,
            ProjectMember.user_id == user.id,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership is None:
        membership = ProjectMember(
            project_id=share.project_id,
            user_id=user.id,
            role="participant",
        )
        db.add(membership)

    share.used = True
    await db.flush()
    return membership
