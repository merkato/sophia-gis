"""Mozaiki rastrowe: wiele GeoTIFF jako jedna warstwa.

Dwie strategie (obie wspierane przez portal jako "raster_group"):
  1. Grupa warstw w drzewie — każdy GeoTIFF osobno, portal wysyła do WMS nazwę grupy.
     Prosto, ale przy setkach arkuszy QGIS Server otwiera setki plików.
  2. VRT (wirtualny raster GDAL) + piramidy — jedna warstwa, szybkie renderowanie.
     Zalecane dla ortofotomap i dużych zestawów arkuszy.
"""
from __future__ import annotations

import glob
import os

from qgis.core import QgsLayerTreeGroup, QgsProject, QgsRasterLayer


def find_geotiffs(folder: str, recursive: bool = True) -> list[str]:
    patterns = ("*.tif", "*.tiff", "*.TIF", "*.TIFF")
    files: set[str] = set()
    for p in patterns:
        files.update(glob.glob(os.path.join(folder, "**" if recursive else "", p), recursive=recursive))
    return sorted(files)


def add_as_group(folder: str, group_name: str) -> QgsLayerTreeGroup:
    """Strategia 1: każdy plik jako warstwa w nowej grupie."""
    prj = QgsProject.instance()
    root = prj.layerTreeRoot()
    group = root.findGroup(group_name) or root.insertGroup(0, group_name)
    for path in find_geotiffs(folder):
        lyr = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0], "gdal")
        if lyr.isValid():
            prj.addMapLayer(lyr, False)
            group.addLayer(lyr)
    group.setExpanded(False)
    return group


def overview_settings(ds) -> tuple[str, str]:
    """Kompresja i próbkowanie piramid (.ovr) zależnie od kanałów rastra:
    3 × Byte (RGB) -> JPEG w YCbCr (10–20× mniejsze), RGB + alfa (VRT z addAlpha, przezroczystość poza
    arkuszami) -> WEBP (zachowuje kanał alfa; JPEG YCbCr przyjmuje tylko 3 kanały), raster z paletą ->
    DEFLATE z próbkowaniem NEAREST (nie miesza indeksów kolorów), pozostałe -> DEFLATE."""
    from osgeo import gdal

    n = ds.RasterCount
    bands = [ds.GetRasterBand(i + 1) for i in range(n)]
    byte = all(b.DataType == gdal.GDT_Byte for b in bands)
    interp = [b.GetColorInterpretation() for b in bands]
    if n == 1 and interp[0] == gdal.GCI_PaletteIndex:
        return "DEFLATE", "NEAREST"
    if byte and n == 3:
        return "JPEG", "AVERAGE"
    if byte and n == 4 and interp[3] == gdal.GCI_AlphaBand:
        return "WEBP", "AVERAGE"
    return "DEFLATE", "AVERAGE"


def build_vrt(folder: str, vrt_path: str, group_name: str, build_overviews: bool = True) -> QgsRasterLayer:
    """Strategia 2: VRT z wszystkich GeoTIFF w katalogu, dodany jako warstwa w grupie."""
    from osgeo import gdal  # dostępne w każdej instalacji QGIS

    files = find_geotiffs(folder)
    if not files:
        raise ValueError(f"Brak plików GeoTIFF w {folder}")
    # addAlpha: przezroczystość poza arkuszami (z NoData źródeł); hideNodata: kanały RGB bez NoData —
    # maską jest tylko kanał alfa (inaczej czarne piksele wewnątrz skanu też byłyby przezroczyste)
    vrt = gdal.BuildVRT(vrt_path, files, options=gdal.BuildVRTOptions(resolution="highest", addAlpha=True,
                                                                     hideNodata=True))
    if vrt is None:
        raise RuntimeError("gdal.BuildVRT nie powiodło się — sprawdź, czy pliki mają ten sam układ i liczbę kanałów")
    if build_overviews:
        compress, resampling = overview_settings(vrt)
        options = {"COMPRESS_OVERVIEW": compress, "INTERLEAVE_OVERVIEW": "PIXEL",
                   "PHOTOMETRIC_OVERVIEW": "YCBCR" if compress == "JPEG" else None,
                   "JPEG_QUALITY_OVERVIEW": "85" if compress == "JPEG" else None,
                   "WEBP_LEVEL_OVERVIEW": "85" if compress == "WEBP" else None,
                   "PREDICTOR_OVERVIEW": "2" if compress == "DEFLATE" else None}
        try:
            for k, v in options.items():
                gdal.SetConfigOption(k, v)
            if vrt.BuildOverviews(resampling, [2, 4, 8, 16, 32, 64, 128]) != 0:
                raise RuntimeError(f"Budowa piramid ({compress}) nie powiodła się: {gdal.GetLastErrorMsg()}")
        finally:
            for k in options:
                gdal.SetConfigOption(k, None)   # nie zostawiamy ustawień dla innych operacji QGIS
    vrt = None  # zapis na dysk

    prj = QgsProject.instance()
    lyr = QgsRasterLayer(vrt_path, group_name, "gdal")
    if not lyr.isValid():
        raise RuntimeError("Nie można wczytać utworzonego VRT")
    root = prj.layerTreeRoot()
    group = root.findGroup(group_name) or root.insertGroup(0, group_name)
    prj.addMapLayer(lyr, False)
    group.addLayer(lyr)
    return lyr
