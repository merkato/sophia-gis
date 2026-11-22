#!/usr/bin/env python3
"""Raport czasów żądań mapy (/ows) z dziennika Caddy (proxy/Caddyfile, log „ows”): JSON z wejścia standardowego.

    scripts/server/ows-report.sh [godziny] [--warstwy]

Grupy: projekt × rodzaj żądania (GetMap, GetFeatureInfo, kafle TILED=true…); z --warstwy także zestaw warstw.
Kolumny: liczba żądań, mediana i 95. percentyl czasu, maksimum, średni rozmiar odpowiedzi, odsetek błędów (≥ 400).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from urllib.parse import parse_qsl, urlsplit


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hours", nargs="?", type=float, default=24, help="okres wstecz w godzinach (domyślnie 24)")
    ap.add_argument("--warstwy", action="store_true", help="grupuj także po zestawie warstw")
    a = ap.parse_args()
    since = time.time() - a.hours * 3600
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for line in sys.stdin:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("ts", 0) < since or "request" not in e:
            continue
        q = {k.upper(): v for k, v in parse_qsl(urlsplit(e["request"].get("uri", "")).query)}
        kind = q.get("REQUEST", "?")
        if q.get("TILED", "").lower() == "true":
            kind += " (kafel)"
        key = (q.get("PROJECT", "?"), kind) + ((q.get("LAYERS", ""),) if a.warstwy else ())
        groups[key].append({"d": float(e.get("duration", 0)), "s": int(e.get("size", 0)), "st": int(e.get("status", 0)),
                            "px": int(q.get("WIDTH", 0) or 0) * int(q.get("HEIGHT", 0) or 0)})
    if not groups:
        print(f"Brak żądań /ows z ostatnich {a.hours:g} h.")
        return
    head = f"{'projekt':28} {'żądanie':22} {'liczba':>7} {'mediana':>8} {'p95':>7} {'max':>7} {'KB':>6} {'Mpx':>5} {'błędy':>6}"
    print(f"Żądania /ows z ostatnich {a.hours:g} h (czasy w sekundach)\n{head}")
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        r = groups[key]
        d = [x["d"] for x in r]
        px = [x["px"] for x in r if x["px"]]
        print(f"{key[0][:28]:28} {key[1][:22]:22} {len(r):7} {statistics.median(d):8.2f} {pct(d, 95):7.2f} {max(d):7.2f}"
              f" {statistics.mean(x['s'] for x in r) / 1024:6.0f} {statistics.mean(px) / 1e6 if px else 0:5.1f}"
              f" {sum(x['st'] >= 400 for x in r) / len(r):6.0%}")
        if a.warstwy:
            print(f"    warstwy: {key[2] or '—'}")


if __name__ == "__main__":
    main()
