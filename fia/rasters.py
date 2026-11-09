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


def build_vrt(folder: str, vrt_path: str, group_name: str, build_overviews: bool = True) -> QgsRasterLayer:
    """Strategia 2: VRT z wszystkich GeoTIFF w katalogu, dodany jako warstwa w grupie."""
    from osgeo import gdal  # dostępne w każdej instalacji QGIS

    files = find_geotiffs(folder)
    if not files:
        raise ValueError(f"Brak plików GeoTIFF w {folder}")
    vrt = gdal.BuildVRT(vrt_path, files, options=gdal.BuildVRTOptions(resolution="highest", addAlpha=True))
    if vrt is None:
        raise RuntimeError("gdal.BuildVRT nie powiodło się — sprawdź, czy pliki mają ten sam układ i liczbę kanałów")
    if build_overviews:
        gdal.SetConfigOption("COMPRESS_OVERVIEW", "JPEG")
        gdal.SetConfigOption("PHOTOMETRIC_OVERVIEW", "YCBCR")
        gdal.SetConfigOption("INTERLEAVE_OVERVIEW", "PIXEL")
        vrt.BuildOverviews("AVERAGE", [2, 4, 8, 16, 32, 64, 128])
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
