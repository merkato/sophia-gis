#!/bin/sh
# Wtyczki Sophii na serwerze (docs/WTYCZKI.md). Uruchamiaj z katalogu Sophii (/opt/sophia).
#
#   scripts/server/plugin.sh install <repozytorium git> <id> [<tag albo gałąź>]
#       np. scripts/server/plugin.sh install https://github.com/merkato/sophia-plugins egib egib-v1.0.0
#       Instaluje albo aktualizuje katalog <id> z repozytorium do plugins/<id> i restartuje API.
#       Włączenie i uprawnienia: panel administratora → Wtyczki.
#   scripts/server/plugin.sh list
#   scripts/server/plugin.sh remove <id>
#       Usuwa kod wtyczki (najpierw wyłącz ją w panelu). Dane w bazie (schemat wtyczki) zostają.
#
# Kod wtyczki wykonuje się w API z pełnym dostępem do bazy — instaluj tylko z zaufanych repozytoriów
# i z konkretnego tagu wersji.
set -eu
cd "$(dirname "$0")/../.."
PLUGINS=plugins
mkdir -p "$PLUGINS"

restart_api() {
    docker compose restart api >/dev/null
    echo "API zrestartowane. Stan wtyczki: panel administratora → Wtyczki (albo: docker compose logs api | grep wtyczka)."
}

case "${1:-}" in
install)
    repo=${2:?podaj adres repozytorium}; id=${3:?podaj identyfikator wtyczki}; ref=${4:-}
    echo "$id" | grep -Eq '^[a-z][a-z0-9_]{1,40}$' || { echo "Błędny identyfikator: $id"; exit 1; }
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    if [ -n "$ref" ]; then git clone -q --depth 1 --branch "$ref" "$repo" "$tmp/repo"
    else git clone -q --depth 1 "$repo" "$tmp/repo"; fi
    src="$tmp/repo/$id"
    [ -f "$src/sophia-plugin.json" ] || { echo "W repozytorium nie ma katalogu $id z sophia-plugin.json"; exit 1; }
    grep -q "\"id\": *\"$id\"" "$src/sophia-plugin.json" || { echo "Identyfikator w manifeście różni się od $id"; exit 1; }
    rm -rf "$src/tests"
    commit=$(git -C "$tmp/repo" rev-parse --short HEAD)
    printf '{"repo": "%s", "ref": "%s", "commit": "%s", "installed": "%s"}\n' "$repo" "$ref" "$commit" "$(date -Is)" \
        > "$src/.installed.json"
    rm -rf "$PLUGINS/.$id.new"
    cp -a "$src" "$PLUGINS/.$id.new"
    rm -rf "$PLUGINS/.$id.old"
    [ -d "$PLUGINS/$id" ] && mv "$PLUGINS/$id" "$PLUGINS/.$id.old"
    mv "$PLUGINS/.$id.new" "$PLUGINS/$id"
    rm -rf "$PLUGINS/.$id.old"
    version=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$PLUGINS/$id/sophia-plugin.json" | head -1)
    echo "Zainstalowano $id $version ($repo ${ref:-HEAD}, $commit)."
    restart_api
    ;;
list)
    for m in "$PLUGINS"/*/sophia-plugin.json; do
        [ -f "$m" ] || { echo "Brak zainstalowanych wtyczek."; break; }
        d=$(dirname "$m")
        v=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$m" | head -1)
        src=$(cat "$d/.installed.json" 2>/dev/null || echo "(skopiowana ręcznie)")
        echo "$(basename "$d") $v  $src"
    done
    ;;
remove)
    id=${2:?podaj identyfikator wtyczki}
    [ -d "$PLUGINS/$id" ] || { echo "Nie ma wtyczki $id"; exit 1; }
    rm -rf "${PLUGINS:?}/$id"
    echo "Usunięto kod wtyczki $id (dane w bazie zostały)."
    restart_api
    ;;
*)
    sed -n '2,15p' "$0"; exit 1 ;;
esac
