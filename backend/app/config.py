"""Application configuration, read once from environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")

_DEV_SECRET = "dev-only-secret-change-me-before-deploying-0123456789"


class Settings:
    app_name = "DealFlow360"
    version = "1.0.0"
    environment = os.getenv("ENVIRONMENT", "development")
    secret_key = os.getenv("SECRET_KEY", _DEV_SECRET)
    algorithm = "HS256"
    access_token_expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'dealflow360.db').as_posix()}")
    cors_origins = [o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:4321,http://127.0.0.1:4321").split(",") if o.strip()]
    seed_on_start = os.getenv("SEED_ON_START", "true").lower() in ("1", "true", "yes")
    frontend_dist = Path(os.getenv("FRONTEND_DIST", str(REPO_DIR / "frontend" / "dist")))


settings = Settings()

if settings.environment == "production" and settings.secret_key == _DEV_SECRET:
    raise RuntimeError("SECRET_KEY must be set when ENVIRONMENT=production")
