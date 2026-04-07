"""
Thesis IoT Server — Configuration
Environment-based settings using pydantic-settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── App ─────────────────────────────────────────────
    app_name: str = "Thesis IoT Visual Monitoring"
    debug: bool = True

    # ── MQTT ────────────────────────────────────────────
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_topic_commands: str = "device/stm32/commands"
    mqtt_topic_status: str = "device/stm32/status"
    mqtt_topic_dashboard_images: str = "dashboard/images/new"
    mqtt_topic_dashboard_analysis: str = "dashboard/analysis/new"

    # ── Database ────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/thesis.db"

    # ── AI Backends ─────────────────────────────────────
    vllm_base_url: str = "http://localhost:8001/v1"
    vllm_model: str = "Qwen/Qwen3-VL-30B-A3B"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash"

    # ── Storage ─────────────────────────────────────────
    upload_dir: str = "./data/uploads"
    firmware_dir: str = "./data/firmware"

    # ── Firmware OTA ───────────────────────────────────
    firmware_upload_token: str = ""  # API key for CI firmware uploads (empty = no auth)

    # ── WiFi Config Encryption ────────────────────────
    # Fernet key for encrypting WiFi passwords at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    wifi_config_encryption_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
