import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.limiter import limiter
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.models import User
from app.schemas.schemas import (
    MessageResponse,
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserOut,
    UserRegister,
)
from app.services.token_service import issue_token_pair, revoke_token, rotate_token_pair

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.login == payload.login))
    if result.scalar_one_or_none():
        raise ConflictError(f"Login '{payload.login}' is already taken")

    user = User(
        login=payload.login,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    return user


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Login — returns access + refresh token pair (rate limited: 10/min per IP)",
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    result = await db.execute(select(User).where(User.login == payload.login))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("Invalid login or password")

    logger.info("User logged in", extra={"user": user.login})
    return await issue_token_pair(user, db)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new token pair (rotation)",
)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    return await rotate_token_pair(payload.refresh_token, db)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke the current refresh token (logout)",
)
async def logout(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await revoke_token(payload.refresh_token, db)
    return MessageResponse(message="Logged out successfully")
