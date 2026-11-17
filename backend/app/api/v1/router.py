from fastapi import APIRouter

from app.api.v1.routers import agents, auth, notifications, posts

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(posts.router)
api_router.include_router(notifications.router)
