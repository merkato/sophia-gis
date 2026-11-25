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
    # Biblioteka rastrów wspólna dla projektów (data/rasters; w QGIS ../../rasters) — wysyłka z Fii (routers/rasters.py)
    rasters_dir: Path = Path("/rasters")
    max_attachment_mb: int = 50                 # dokumenty z WebUI (PDF, GML…)
    # Zdjęcia i pliki wysyłane z WebUI: <uploads_dir>/<slug>/zdjecia/... (data/uploads na hoście)
    uploads_dir: Path = Path("/uploads")
    max_photo_mb: int = 40

    qgis_server_url: str = "http://qgis:80/"

    # Powiadomienia e-mail (app/mail.py): lekki Postfix z docker-compose (SMTP_HOST=mail, port 587, bez logowania)
    # albo dowolny serwer SMTP. Puste SMTP_HOST — wysyłka wyłączona.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    smtp_from: str | None = None                # np. powiadomienia@webgis.example.pl
    smtp_from_name: str | None = None           # nazwa nadawcy (domyślnie „Sophia WebGIS”)
    # Adres aplikacji w linkach w wiadomościach (np. https://webgis.example.pl); puste — z SITE_ADDRESS
    public_url: str | None = None
    site_address: str | None = None

    @property
    def base_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        site = (self.site_address or "localhost").strip()
        return site if site.startswith("http") else f"https://{site}"

    # Wtyczki: <plugins_dir>/<id>/sophia-plugin.json (data/… na hoście: plugins/, scripts/server/plugin.sh)
    plugins_dir: Path = Path("/plugins")



@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
