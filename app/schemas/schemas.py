import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    repeat_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "UserRegister":
        if self.password != self.repeat_password:
            raise ValueError("Passwords do not match")
        return self


class UserLogin(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    id: uuid.UUID
    login: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Project ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ProjectUpdate":
        if self.name is None and self.description is None:
            raise ValueError("At least one field (name or description) must be provided")
        return self


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    total_size_bytes: int
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentOut] = []

    model_config = {"from_attributes": True}


class ProjectInfoOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    total_size_bytes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Document ──────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


class DocumentDownloadResponse(BaseModel):
    download_url: str
    filename: str
    expires_in: int = 3600  # seconds


# ── Member / Invite ───────────────────────────────────────────────────────────

class MemberOut(BaseModel):
    user_id: uuid.UUID
    login: str
    role: Literal["owner", "participant"]
    joined_at: datetime

    model_config = {"from_attributes": True}


class InviteRequest(BaseModel):
    user_login: str = Field(min_length=1, max_length=64)


class ShareLinkResponse(BaseModel):
    join_url: str
    expires_at: datetime


class JoinResponse(BaseModel):
    project_id: uuid.UUID
    role: str
    message: str


# ── Generic responses ─────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class StorageInfoResponse(BaseModel):
    project_id: uuid.UUID
    total_size_bytes: int
    total_size_mb: float
    limit_mb: int
    usage_percent: float


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    size: int = Field(default=20, ge=1, le=100, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    pages: int


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    meta: PageMeta


# ── Document metadata patch ───────────────────────────────────────────────────

class DocumentMetadataPatch(BaseModel):
    filename: str = Field(min_length=1, max_length=256)

    @field_validator("filename")
    @classmethod
    def must_have_valid_extension(cls, v: str) -> str:
        import os
        _, ext = os.path.splitext(v.lower())
        if ext not in {".pdf", ".docx", ".doc"}:
            raise ValueError(f"Extension '{ext}' not allowed. Use .pdf or .docx")
        return v


# ── Refresh token ─────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int   # seconds
    refresh_expires_in: int  # seconds


# ── Search ────────────────────────────────────────────────────────────────────

class ProjectSearchParams(BaseModel):
    search: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
