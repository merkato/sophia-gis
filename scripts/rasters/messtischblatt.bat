@echo off
rem Uruchamia messtischblatt.py Pythonem z GDAL (OSGeo4W albo instalator QGIS).
rem Systemowy python nie ma modulu osgeo.
rem   messtischblatt.bat E:\skany\5076_*.tif E:\gis\rasters\tk25 --check
setlocal
set "ENVBAT="
if exist "C:\OSGeo4W\bin\o4w_env.bat" set "ENVBAT=C:\OSGeo4W\bin\o4w_env.bat"
if not defined ENVBAT for /d %%D in ("C:\Program Files\QGIS*") do if exist "%%~D\bin\o4w_env.bat" set "ENVBAT=%%~D\bin\o4w_env.bat"
if not defined ENVBAT (
  echo Nie znaleziono OSGeo4W ani QGIS ^(o4w_env.bat^). Uruchom skrypt z "OSGeo4W Shell".
  exit /b 1
)
call "%ENVBAT%" >nul
python "%~dp0messtischblatt.py" %*
