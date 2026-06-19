"""
Refresh token service.

Flow:
  1. Login  → issue (access_token, refresh_token)
  2. Client stores refresh_token in httpOnly cookie or secure storage
  3. Access token expires (15 min) → POST /auth/refresh with refresh_token
  4. Server validates, revokes old refresh token, issues new pair (rotation)
  5. Logout → revoke current refresh token

Security properties:
  - Refresh tokens stored as SHA-256 hashes (never plaintext in DB)
  - Rotation on every use (old token immediately revoked)
  - Expiry enforced at DB level (expires_at column)
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token
from app.models.models import RefreshToken, User
from app.schemas.schemas import TokenPair

settings = get_settings()

REFRESH_TOKEN_BYTES = 64  # 512-bit entropy


def _generate_raw_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _refresh_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)


async def issue_token_pair(user: User, db: AsyncSession) -> TokenPair:
    """Create a fresh (access, refresh) pair for the user."""
    access = create_access_token(subject=str(user.id))
    raw_refresh = _generate_raw_token()

    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw_refresh),
        expires_at=_refresh_expires_at(),
    )
    db.add(rt)
    await db.flush()

    return TokenPair(
        access_token=access,
        refresh_token=raw_refresh,
        access_expires_in=settings.access_token_expire_minutes * 60,
        refresh_expires_in=settings.refresh_token_expire_days * 86400,
    )


async def rotate_token_pair(raw_refresh: str, db: AsyncSession) -> TokenPair:
    """
    Validate the incoming refresh token, revoke it, and issue a new pair.
    Raises UnauthorizedError if token is invalid, expired, or already revoked.
    """
    token_hash = _hash_token(raw_refresh)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()

    if rt is None:
        raise UnauthorizedError("Invalid refresh token")
    if rt.revoked:
        # Possible token reuse — revoke all tokens for this user (security measure)
        await _revoke_all_for_user(rt.user_id, db)
        raise UnauthorizedError("Refresh token already used — all sessions revoked")
    if rt.expires_at.replace(tzinfo=timezone.utc) < now:
        raise UnauthorizedError("Refresh token expired")

    # Revoke the old token (rotation)
    rt.revoked = True
    await db.flush()

    # Load the user
    user_result = await db.execute(select(User).where(User.id == rt.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")

    return await issue_token_pair(user, db)


async def revoke_token(raw_refresh: str, db: AsyncSession) -> None:
    """Revoke a specific refresh token (logout)."""
    token_hash = _hash_token(raw_refresh)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt and not rt.revoked:
        rt.revoked = True
        await db.flush()


async def _revoke_all_for_user(user_id: uuid.UUID, db: AsyncSession) -> None:
    """Revoke all active refresh tokens for a user (reuse detection response)."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
    )
    for rt in result.scalars().all():
        rt.revoked = True
    await db.flush()
