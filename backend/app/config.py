"""Application configuration."""

from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # App
    APP_NAME: str = "POS-MOBILE API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./pos_mobile.db"
    DATABASE_ECHO: bool = False

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "file://",
        "null",
        # หน้าเว็บบน GitHub Pages เรียก backend บนมือถือเพื่อสำรองข้อมูล
        "https://zetxero-main.github.io",
    ]

    # Server — ค่าเริ่มต้นรับเฉพาะเครื่องนี้ (AUTH ปิดเป็นค่าเริ่มต้น ถ้าเปิด 0.0.0.0
    # ใครก็ได้ใน Wi-Fi เดียวกันจะอ่าน/แก้ข้อมูลร้านได้)
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Backup snapshots (POST /api/v1/sync/snapshots)
    SNAPSHOT_KEEP: int = 30  # เก็บย้อนหลังกี่ชุดต่อร้าน/label
    SNAPSHOT_MAX_BYTES: int = 10_000_000  # ขนาดสูงสุดต่อชุด (10 MB)

    # Auth (ปิดไว้เป็นค่า default — เปิดใน .env เมื่อต้องการ)
    AUTH_ENABLED: bool = False
    API_KEY: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Data directory (default: ~/pos-mobile-data; on Termux = /data/data/com.termux/files/home/pos-mobile-data)
    DATA_DIR: Path = Path.home() / "pos-mobile-data"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
