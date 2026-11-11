from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Połączenie do bazy portalu (schemat "portal") — przez usługę z pg_service.conf
    portal_db_service: str = "sophia"

    jwt_secret: str
    jwt_ttl_minutes: int = 720
    cookie_name: str = "sophia_token"
    cookie_secure: bool = True

    admin_login: str = "admin"
    admin_password: str | None = None

    projects_dir: Path = Path("/projects")
    max_attachment_mb: int = 50                 # dokumenty z WebUI (PDF, GML…)
    # Zdjęcia i pliki wysyłane z WebUI: <uploads_dir>/<slug>/zdjecia/... (data/uploads na hoście)
    uploads_dir: Path = Path("/uploads")
    max_photo_mb: int = 40

    qgis_server_url: str = "http://qgis:80/"



@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
