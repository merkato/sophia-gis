#!/bin/bash
# Start QGIS Server (camptocamp/qgis-server) ze strojeniem pod sprzęt, na którym kontener właśnie wstaje.
#
# Liczba procesów QGIS Server (Apache mod_fcgid) i wątków renderu wynika z rdzeni CPU i pamięci dostępnych
# DLA KONTENERA (limity z docker-compose / cgroup, inaczej cała maszyna) — ten sam obraz i konfiguracja działają
# na małym VPS i na większym serwerze produkcyjnym. Każdą wartość można nadpisać w .env:
#   SOPHIA_QGIS_PROCESSES      maks. liczba procesów (FCGID_MAX_PROCESSES)
#   SOPHIA_QGIS_MIN_PROCESSES  procesy utrzymywane stale (FCGID_MIN_PROCESSES)
#   SOPHIA_QGIS_THREADS        wątki renderu na żądanie (QGIS_SERVER_MAX_THREADS, przy PARALLEL_RENDERING)
#   SOPHIA_QGIS_PROCESS_MB     szacowana pamięć jednego procesu do wyliczeń (domyślnie 500 MB)
# Wyliczone wartości trafiają do logu: docker compose logs qgis | grep Sophia
set -e

cpus=$(nproc)
if [ -r /sys/fs/cgroup/cpu.max ]; then                       # limit CPU kontenera (deploy.resources.limits.cpus)
    read -r quota period < /sys/fs/cgroup/cpu.max
    if [ "$quota" != "max" ] && [ "${period:-0}" -gt 0 ]; then
        q=$(( (quota + period - 1) / period ))
        [ "$q" -lt "$cpus" ] && cpus=$q
    fi
fi
[ "$cpus" -lt 1 ] && cpus=1

mem_mb=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ -r /sys/fs/cgroup/memory.max ]; then                    # limit pamięci kontenera (deploy.resources.limits.memory)
    lim=$(cat /sys/fs/cgroup/memory.max)
    if [ "$lim" != "max" ]; then
        lim_mb=$(( lim / 1024 / 1024 ))
        [ "$lim_mb" -lt "$mem_mb" ] && mem_mb=$lim_mb
    fi
fi

per_proc=${SOPHIA_QGIS_PROCESS_MB:-500}
by_mem=$(( mem_mb * 3 / 4 / per_proc ))                      # 3/4 pamięci na procesy QGIS, reszta: cache GDAL, system
procs=$cpus
[ "$by_mem" -lt "$procs" ] && procs=$by_mem
[ "$procs" -lt 2 ] && procs=2
procs=${SOPHIA_QGIS_PROCESSES:-$procs}

min_procs=$(( procs / 2 ))
[ "$min_procs" -lt 1 ] && min_procs=1
min_procs=${SOPHIA_QGIS_MIN_PROCESSES:-$min_procs}

threads=$(( cpus / procs ))
[ "$threads" -lt 2 ] && threads=2
[ "$threads" -gt "$cpus" ] && threads=$cpus
threads=${SOPHIA_QGIS_THREADS:-$threads}

export FCGID_MAX_PROCESSES=$procs FCGID_MIN_PROCESSES=$min_procs QGIS_SERVER_MAX_THREADS=$threads
echo "Sophia: QGIS Server — CPU: $cpus, pamięć: ${mem_mb} MB → procesy: $min_procs–$procs, wątki renderu: $threads" \
     "(nadpisanie: SOPHIA_QGIS_PROCESSES / SOPHIA_QGIS_MIN_PROCESSES / SOPHIA_QGIS_THREADS w .env)" >&2

exec /usr/local/bin/start-server "$@"
