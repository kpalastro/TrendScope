from fastapi import APIRouter

from app.api.v1 import (
    auth,
    categories,
    competition,
    dashboard,
    discovery,
    health,
    products,
    reports,
    scoring,
    sources,
    watchlist,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    dashboard,
    products,
    discovery,
    categories,
    competition,
    watchlist,
    sources,
    scoring,
    reports,
):
    api_router.include_router(module.router)
