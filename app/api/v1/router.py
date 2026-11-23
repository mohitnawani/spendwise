from fastapi import APIRouter

from app.api.v1.endpoints import exchange_rates
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.categories import router as categories_router
from app.api.v1.endpoints.expenses import router as expenses_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(categories_router)
api_router.include_router(expenses_router)
api_router.include_router(admin_router)
api_router.include_router(exchange_rates.router)
