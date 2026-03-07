"""
Thesis IoT Server — FastAPI Application Entry Point
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import router as api_router
from app.mqtt.client import mqtt_client, mqtt_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Ensure upload directory exists
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Connect MQTT
    await mqtt_client.connection()
    print(f"✓ MQTT connected to {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    yield

    # Disconnect MQTT
    await mqtt_client.client.disconnect()
    print("✗ MQTT disconnected")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Cloud server for Autonomous IoT Visual Monitoring. "
        "Handles AI planning, MQTT command dispatch, image upload, and visual analysis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS (allow dashboard) ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────
app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "mqtt_broker": f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
    }
