#!/bin/sh
# Raport czasów żądań mapy (/ows) z dziennika Caddy: mediana, 95. percentyl, rozmiar, błędy — na projekt i rodzaj żądania.
#   scripts/server/ows-report.sh [godziny] [--warstwy]      (domyślnie ostatnie 24 h)
# Dziennik: wolumen caddy_data, /data/logs/ows.log* (rotacja co 50 MB, 10 plików) — proxy/Caddyfile.
set -eu
cd "$(dirname "$0")/../.."
docker compose exec -T proxy sh -c 'cat /data/logs/ows.log* 2>/dev/null || true' | python3 scripts/server/ows_report.py "$@"
