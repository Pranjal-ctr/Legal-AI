from fastapi import APIRouter

from app.api.v1.endpoints import chat, health, sessions, speech

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(sessions.router)
api_router.include_router(sessions.feedback_router)
api_router.include_router(speech.router)
