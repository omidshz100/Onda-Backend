from fastapi import APIRouter

from app.api.v1 import auth, calls, chat, health, meetings, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(meetings.router)
api_router.include_router(calls.router)
api_router.include_router(chat.router)
