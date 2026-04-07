"""
Thesis IoT Server — FastAPI Application Entry Point
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import router as api_router
from app.api.scheduler_routes import router as scheduler_router
from app.api.firmware_routes import router as firmware_router
from app.api.wifi_routes import router as wifi_router
from app.api.agent_routes import router as agent_router
from app.mqtt.client import mqtt_client, mqtt_config
from app.db.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Ensure upload and firmware directories exist
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.firmware_dir, exist_ok=True)

    # Create DB tables
    await create_tables()
    print("[OK] Database tables ready")

    # Connect MQTT
    await mqtt_client.connection()
    print(f"[OK] MQTT connected to {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    yield

    # Disconnect MQTT
    await mqtt_client.client.disconnect()
    print("[WARN] MQTT disconnected")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Cloud server for Autonomous IoT Visual Monitoring. "
        "Handles AI planning, MQTT command dispatch, image upload, and visual analysis."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# ── CORS (allow dashboard) ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────
app.include_router(api_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")
app.include_router(firmware_router, prefix="/api")
app.include_router(wifi_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "mqtt_broker": f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
    }
