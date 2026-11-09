#!/usr/bin/env bash
# Kopia zapasowa Sophii: baza (pg_dump), projekty QGIS, załączniki PDF, konfiguracja.
# Rastrów NIE kopiuje (duże i odtwarzalne z oryginałów) — trzymaj oryginały u siebie.
#
#   crontab -e
#   15 3 * * * /opt/sophia/scripts/server/backup.sh >> /opt/sophia-backups/backup.log 2>&1
#
# Kopia poza serwerem (zalecane): skonfiguruj rclone (np. OVH Object Storage, S3) i ustaw
#   RCLONE_REMOTE=ovh:sophia-backup   w /opt/sophia/.env
#
# Odtworzenie bazy:
#   docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < db.dump
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-${APP_DIR}-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
cd "$APP_DIR"
set -a; . ./.env; set +a

STAMP="$(date +%Y-%m-%d_%H%M)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
echo "[$(date -Is)] Kopia -> $DEST"

# 1. Baza — format custom (skompresowany, pozwala odtworzyć pojedyncze tabele)
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DEST/db.dump"

# 2. Projekty QGIS + .portal.json. Rastry leżące obok projektu (np. projects/<slug>/rastry/)
#    pomijamy tak samo jak data/rasters: oryginały są u autora projektu.
tar -czf "$DEST/projects.tar.gz" -C "$APP_DIR/data" \
  --exclude='*.tif' --exclude='*.tiff' --exclude='*.TIF' --exclude='*.ovr' \
  --exclude='*.jp2' --exclude='*.ecw' --exclude='*.vrt' --exclude='*.aux.xml' \
  projects

# 3. Załączniki PDF (wolumen Dockera) — czytane przez kontener api, bez znajomości ścieżek wolumenu
docker compose exec -T api tar -czf - -C / attachments > "$DEST/attachments.tar.gz"

# 4. Konfiguracja (zawiera hasła — katalog kopii ma prawa 700)
tar -czf "$DEST/config.tar.gz" -C "$APP_DIR" .env config proxy
chmod -R go-rwx "$BACKUP_ROOT"

du -sh "$DEST" | awk '{print "    rozmiar: "$1}'

# Rotacja lokalna
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

# Kopia poza serwerem
if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  if command -v rclone &>/dev/null; then
    rclone copy "$DEST" "$RCLONE_REMOTE/$STAMP" --quiet
    echo "    wysłano do $RCLONE_REMOTE/$STAMP"
  else
    echo "    !! RCLONE_REMOTE ustawione, ale brak rclone (sudo apt install rclone)" >&2
  fi
fi
echo "[$(date -Is)] OK"
