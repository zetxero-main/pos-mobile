"""FastAPI application entry point."""

import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, close_db
from app.api import api_router
from app.api import websocket as ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    await init_db()
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} started")
    print(f"📊 Database: {settings.DATABASE_URL}")
    print(f"🌐 Server: http://{settings.HOST}:{settings.PORT}")
    yield
    # Shutdown
    await close_db()
    print("👋 Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="POS-MOBILE Backend API - Local-first Point of Sale for Mobile",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Private Network Access: หน้าเว็บ https (GitHub Pages) เรียก backend บน 127.0.0.1 ได้
# ต่อเมื่อ preflight ตอบ Access-Control-Allow-Private-Network — ให้เฉพาะ origin ที่อยู่ใน
# CORS_ORIGINS (ลงทะเบียนหลัง CORSMiddleware จึงครอบอยู่ชั้นนอกและเห็นคำตอบ preflight)
@app.middleware("http")
async def allow_private_network_access(request: Request, call_next):
    response = await call_next(request)
    if (
        request.method == "OPTIONS"
        and request.headers.get("access-control-request-private-network") == "true"
        and request.headers.get("origin") in settings.CORS_ORIGINS
    ):
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

# Include API routes
app.include_router(api_router)

# Include WebSocket router directly on app
app.include_router(ws.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "POS-MOBILE Backend API",
        "docs": "/docs",
        "health": "/api/v1/sync/health",
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "service": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )