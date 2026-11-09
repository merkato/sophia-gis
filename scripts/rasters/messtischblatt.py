"""Przycina skany Messtischblatt (TK25) do ramki mapy, opcjonalnie poprawiając georeferencję.

Arkusz TK25 (Messtischblatt) obejmuje dokładnie 10' długości x 6' szerokości geograficznej
na elipsoidzie Bessela (datum Potsdam/Rauenberg ~ DHDN). Numer arkusza "RRCC":
    północna krawędź  = 56° - RR * 6'
    zachodnia krawędź = 5°50' + (CC-1) * 10'     (= pełne 10' od Ferro, Ferro = 17°40' W)
np. 5264 Charlottenbrunn: 50°42'-50°48' N, 16°20'-16°30' E (na mapie: 34°0'-34°10' ö. L. v. Ferro).
Numer to pierwsze 4 cyfry nazwy pliku. Opisy w narożnikach skanu pozwalają go sprawdzić.

Tryb 1 — georeferencja jest dobra: ramka liczona z numeru wycina arkusz.
    python messtischblatt.py oryginaly\\5264_*.tif rastry\\

Tryb 2 — georeferencja jest zła (ramka wyliczona nie pokrywa się z ramką na skanie):
podaj piksele 4 narożników ramki mapy (wewnętrznej, cienkiej linii) w rastrze wejściowym,
w kolejności NW NE SW SE. Arkusz zostanie zgeoreferowany na nowo z dokładnych współrzędnych
narożników (thin plate spline: narożniki trafiają dokładnie) i przycięty.
    python messtischblatt.py oryginaly\\5364_*.tif rastry\\ --corners 400,472 3171,461 406,3089 3180,3072

--check: zapisuje tylko ramkę (GeoJSON) obok wyniku — do kontroli w QGIS na tle skanu.
--margin M: zapas M metrów na zewnątrz ramki.

Wynik: COG RGBA (WEBP, kanał alfa = przezroczystość poza ramką), piramidy.
W projekcie QGIS ustaw pasmo 4 jako pasmo przezroczystości warstwy.
Wymaga GDAL z Pythonem (np. OSGeo4W Shell).
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
osr.UseExceptions()

# Bessel 1841 + 7 parametrów DHDN -> WGS84 (EPSG:1777, dokładność ~3 m w Niemczech).
# Samo EPSG:4314 bywa przeliczane przez PROJ "na skróty" bez przesunięcia datum — wtedy ramka
# wychodzi ~150-200 m obok (sprawdzone na arkuszu 5264).
BESSEL_DHDN = "+proj=longlat +ellps=bessel +towgs84=598.1,73.7,418.2,0.202,0.045,-2.455,6.7 +no_defs"
STEP_LAT = 6 / 60       # 6'
STEP_LON = 10 / 60      # 10'
DENSIFY = 60            # punktów na krawędź ramki
CORNERS = ("NW", "NE", "SW", "SE")


def sheet_bounds(number: str) -> tuple[float, float, float, float]:
    """(zachód, południe, wschód, północ) w stopniach Bessela dla numeru TK25 'RRCC'."""
    row, col = int(number[:2]), int(number[2:4])
    north = 56 - row * STEP_LAT
    west = 5 + 50 / 60 + (col - 1) * STEP_LON
    return west, north - STEP_LAT, west + STEP_LON, north


def bessel_to(target: osr.SpatialReference) -> osr.CoordinateTransformation:
    src = osr.SpatialReference()
    src.ImportFromProj4(BESSEL_DHDN)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(src, target)


def corner_coords(number: str, target: osr.SpatialReference) -> dict[str, tuple[float, float]]:
    w, s, e, n = sheet_bounds(number)
    tr = bessel_to(target)
    geo = {"NW": (w, n), "NE": (e, n), "SW": (w, s), "SE": (e, s)}
    return {k: tuple(tr.TransformPoint(lon, lat)[:2]) for k, (lon, lat) in geo.items()}


def neatline(number: str, target: osr.SpatialReference, margin: float) -> ogr.Geometry:
    w, s, e, n = sheet_bounds(number)
    pts = []
    for i in range(DENSIFY):                       # południe: zachód -> wschód
        pts.append((w + (e - w) * i / DENSIFY, s))
    for i in range(DENSIFY):                       # wschód: południe -> północ
        pts.append((e, s + (n - s) * i / DENSIFY))
    for i in range(DENSIFY):                       # północ: wschód -> zachód
        pts.append((e - (e - w) * i / DENSIFY, n))
    for i in range(DENSIFY):                       # zachód: północ -> południe
        pts.append((w, n - (n - s) * i / DENSIFY))
    pts.append(pts[0])
    tr = bessel_to(target)
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for lon, lat in pts:
        x, y, _ = tr.TransformPoint(lon, lat)
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly.Buffer(margin) if margin else poly


def write_cutline(geom: ogr.Geometry, srs: osr.SpatialReference, path: Path) -> None:
    drv = ogr.GetDriverByName("GeoJSON")
    if path.exists():
        drv.DeleteDataSource(str(path))
    ds = drv.CreateDataSource(str(path))
    lyr = ds.CreateLayer("ramka", srs, ogr.wkbPolygon)
    feat = ogr.Feature(lyr.GetLayerDefn())
    feat.SetGeometry(geom)
    lyr.CreateFeature(feat)
    ds = None


def process(src: Path, out_dir: Path, margin: float, check: bool,
            corners: list[tuple[float, float]] | None) -> None:
    m = re.match(r"(\d{4})", src.name)
    if not m:
        print(f"!! {src.name}: nazwa nie zaczyna się od numeru arkusza (RRCC) — pomijam")
        return
    number = m.group(1)
    ds = gdal.Open(str(src))
    srs = ds.GetSpatialRef()
    if srs is None:
        print(f"!! {src.name}: brak układu współrzędnych — pomijam")
        return
    gt = ds.GetGeoTransform()
    res = (abs(gt[1]) + abs(gt[5])) / 2
    w, s, e, n = sheet_bounds(number)
    print(f"{src.name}: arkusz {number}  {s:.4f}-{n:.4f} N, {w:.4f}-{e:.4f} E (Bessel)")

    out_dir.mkdir(parents=True, exist_ok=True)
    cut = out_dir / f"{src.stem}.ramka.geojson"
    write_cutline(neatline(number, srs.Clone(), margin), srs, cut)
    if check:
        print(f"    ramka: {cut}")
        return

    warp_src: gdal.Dataset | str = ds
    warp_opts: dict = {}
    if corners:
        # Nowa georeferencja: piksele narożników -> dokładne współrzędne narożników ramki
        xy = corner_coords(number, srs.Clone())
        gcps = [gdal.GCP(xy[k][0], xy[k][1], 0, px + 0.5, py + 0.5) for k, (px, py) in zip(CORNERS, corners)]
        warp_src = f"/vsimem/{number}_gcp.vrt"
        gdal.Translate(warp_src, ds, format="VRT", GCPs=gcps, outputSRS=srs.ExportToWkt())
        warp_opts = {"tps": True, "dstSRS": srs.ExportToWkt()}
        print("    nowa georeferencja z 4 narożników ramki")

    tmp = out_dir / f"{src.stem}.tmp.tif"
    gdal.Warp(
        str(tmp), warp_src, format="GTiff", cutlineDSName=str(cut), cropToCutline=True,
        dstAlpha=True, xRes=res, yRes=res, targetAlignedPixels=True,
        resampleAlg="bilinear", multithread=True,
        creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"], **warp_opts,
    )
    ds = None
    if corners:
        gdal.Unlink(warp_src)
    out = out_dir / src.name
    # COG + WEBP z kanałem alfa (RGBA). NIE JPEG: JPEG zamienia alfę na maskę GDAL, a QGIS
    # maski nie respektuje — poza obróconą ramką rysuje czarne kliny. W QGIS ustaw pasmo 4
    # jako "pasmo przezroczystości" (Właściwości warstwy -> Przezroczystość).
    gdal.Translate(
        str(out), str(tmp), format="COG",
        creationOptions=["COMPRESS=WEBP", "QUALITY=85", "OVERVIEWS=AUTO",
                         "OVERVIEW_RESAMPLING=AVERAGE", "BLOCKSIZE=512"],
    )
    tmp.unlink()
    cut.unlink()
    print(f"    -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="pliki GeoTIFF (można używać *)")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--margin", type=float, default=0.0, help="zapas na zewnątrz ramki [m]")
    ap.add_argument("--check", action="store_true", help="tylko zapisz ramkę jako GeoJSON")
    ap.add_argument("--corners", nargs=4, metavar="X,Y",
                    help="piksele narożników ramki NW NE SW SE w rastrze wejściowym (jeden plik)")
    a = ap.parse_args()
    files = [Path(p) for pattern in a.inputs for p in (glob.glob(pattern) or [pattern])]
    corners = [tuple(float(v) for v in c.split(",")) for c in a.corners] if a.corners else None
    if corners and len(files) != 1:
        ap.error("--corners działa dla jednego pliku")
    for f in files:
        if f.resolve().parent == a.out_dir.resolve():
            print(f"!! {f.name}: plik wejściowy w katalogu wyjściowym — pomijam")
            continue
        process(f, a.out_dir, a.margin, a.check, corners)
    return 0


if __name__ == "__main__":
    sys.exit(main())
