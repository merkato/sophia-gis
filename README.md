# Sophia

Geoportal i edytor GIS na QGIS Server. Wtyczka QGIS do konfiguracji i publikacji: **Fia**.

Alternatywa dla Lizmap Web Client z naciskiem na prostą konfigurację: **projekt QGIS jest jedynym źródłem prawdy**, a edycja idzie bezpośrednio do PostGIS
z kontrolą uprawnień i zasięgów przestrzennych.

| Katalog | Zawartość |
|---|---|
| `docker-compose.yml` | PostGIS, QGIS Server, API, WebUI, Caddy (SSL) |
| `api/` | FastAPI: projekty, edycja obiektów, załączniki PDF, raporty, użytkownicy/grupy/zasięgi |
| `web/` | React + OpenLayers: mapa, drzewo warstw, edycja, formularze, dokumenty, wydruki |
| `fia/` | Wtyczka QGIS **Fia**: konfiguracja, diagnostyka, mozaiki GeoTIFF/VRT, publikacja |
| `db/init/` | Schemat `portal` (tworzony przy pierwszym starcie bazy) |
| `docs/ARCHITECTURE.md` | Architektura, model uprawnień, roadmapa |
| `docs/SERVER.md` | Wdrożenie na VPS: klucz SSH na Windows, konfiguracja Ubuntu, rastry, kopie zapasowe |
| `docs/TODO.md` | Bieżąca lista zadań (WebUI, Fia) w kolejności realizacji |
| `scripts/` | `windows/setup-ssh.ps1`, `server/setup-ubuntu.sh`, `server/backup.sh` |

## Szybki start

```bash
cp .env.example .env              # ustaw hasła, JWT_SECRET, SITE_ADDRESS
# hasło w config/pg_service.conf musi być takie samo jak POSTGRES_PASSWORD
docker compose up -d --build
```

Portal: `https://<SITE_ADDRESS>/`, dokumentacja API: `https://<SITE_ADDRESS>/api/docs`.
Konto administratora tworzy się przy pierwszym starcie z `ADMIN_LOGIN` / `ADMIN_PASSWORD`.

## Przygotowanie projektu QGIS

1. Połączenie z bazą **wyłącznie przez usługę** `service=sophia` (plik `pg_service.conf` na desktopie —
   patrz komentarz w `config/pg_service.conf`). Nie zapisuj haseł w projekcie.
2. Tabele edytowalne muszą mieć klucz główny i określony typ geometrii/SRID.
3. Formularze, aliasy, słowniki (ValueMap), relacje i wydruki ustawiasz normalnie w QGIS — portal je odczyta.
4. Zainstaluj wtyczkę: skopiuj katalog `fia` do katalogu wtyczek profilu QGIS
   (Windows: `%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\`, w QGIS 3.x — `QGIS3`), włącz ją, a następnie
   *Web → Fia → Konfiguracja i publikacja w Sophii*: zaznacz warstwy edytowalne/załączniki, mozaiki rastrowe,
   sprawdź diagnostykę i kliknij **Publikuj**.
5. W API (`/api/docs`, sekcja *admin*) utwórz grupy, użytkowników, nadaj grupom rolę w projekcie
   (`PUT /api/admin/projects/{id}/access`) i ewentualnie zasięgi.

Rastry (GeoTIFF/VRT) kopiuj do `data/rasters/` — w projekcie używaj ścieżek względnych.

## Rozwój

```bash
cd api && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && .venv/Scripts/pytest
cd web && npm install && npm run dev       # proxy /api i /ows do https://localhost (SOPHIA_URL)
```
