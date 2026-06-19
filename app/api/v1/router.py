from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.projects import router as projects_router
from app.api.v1.endpoints.utils import router as utils_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(documents_router)
api_router.include_router(utils_router)
