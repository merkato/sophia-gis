import TileLayer from "ol/layer/Tile";
import TileGrid from "ol/tilegrid/TileGrid";
import WMTSTileGrid from "ol/tilegrid/WMTS";
import TileWMS from "ol/source/TileWMS";
import WMTS from "ol/source/WMTS";
import XYZ from "ol/source/XYZ";
import { get as getProjection } from "ol/proj";
import type { Basemap } from "./types";
import { ensureProjection } from "./projections";

export const TILE_SIZE = 512;
export const PNG8 = "image/png; mode=8bit";

// Krajowa macierz kafli GUGiK dla EPSG:2180 (ta sama w ortofotomapie, BDOT10k, NMT, TOPO
// na geoportal.gov.pl): narożnik (100000, 850000), kafle 512 px, skale z GetCapabilities.
// Mapa i nasze kafle używają tych samych poziomów, więc podkłady z geoportalu wyświetlają się
// 1:1 (ostro), a nie przeskalowane.
const GUGIK_2180_SCALES = [
  30238155.714285716, 15119077.857142858, 7559538.928571429, 3779769.4642857146, 1889884.7321428573,
  944942.3660714286, 472471.1830357143, 236235.59151785716, 94494.23660714286, 47247.11830357143,
  23623.559151785714, 9449.423660714287, 4724.711830357143, 1889.8847321428573, 944.9423660714286,
  472.4711830357143, 236.23559151785716,
];
export const GUGIK_2180 = {
  origin: [100000, 850000] as [number, number],
  resolutions: GUGIK_2180_SCALES.map((s) => s * 0.00028),
};

/** Siatka kafli i poziomy powiększenia mapy dla układu projektu. */
export function tileGridFor(crs: string): TileGrid {
  if (crs === "EPSG:2180") {
    // + dwa poziomy dokładniejsze niż geoportal (do pracy na własnych danych)
    const r = GUGIK_2180.resolutions;
    return new TileGrid({ origin: GUGIK_2180.origin, resolutions: [...r, r[r.length - 1] / 2, r[r.length - 1] / 4], tileSize: TILE_SIZE });
  }
  // Inne układy: siatka od (0,0), rozdzielczości co 2x
  const top = getProjection(crs)?.getUnits() === "degrees" ? 360 / TILE_SIZE : 4096;
  return new TileGrid({ origin: [0, 0], resolutions: Array.from({ length: 18 }, (_, z) => top / 2 ** z), tileSize: TILE_SIZE });
}

/** Układy, w których podawane są kafle podkładów — trzeba je zarejestrować przed utworzeniem warstw. */
export async function ensureBasemapProjections(basemaps: Basemap[]): Promise<void> {
  const codes = new Set(basemaps.filter((b) => b.kind === "wmts").map((b) => wmtsProjection(b.config.tile_grid.crs)));
  for (const c of codes) await ensureProjection(c);
}

const wmtsProjection = (crs: string) => (crs === "OGC:CRS84" ? "EPSG:4326" : crs);

/**
 * Warstwa OpenLayers dla podkładu z katalogu.
 * wmts/xyz: kafle prosto z serwisu (inny układ niż mapa = przeliczenie w przeglądarce).
 * sophia: kafle WMS z projektu Sophii przez /ows (autoryzacja + wspólny cache nginx).
 */
/** crossOrigin: wydruk w przeglądarce składa obraz z kafli — wymaga CORS (ekranowa mapa go nie wymaga). */
export function basemapLayer(b: Basemap, mapCrs: string, crossOrigin = false): TileLayer {
  const co = crossOrigin ? "anonymous" : undefined;
  const c = b.config;
  const attributions = b.attribution ?? undefined;
  let source;
  if (b.kind === "wmts") {
    const g = c.tile_grid;
    const tileGrid = new WMTSTileGrid({
      ...(g.origins ? { origins: g.origins } : { origin: g.origin }),
      resolutions: g.resolutions,
      matrixIds: g.matrix_ids,
      tileSize: g.tile_size,
    });
    source = new WMTS({
      url: c.url, layer: c.layer, matrixSet: c.matrix_set, format: c.format, style: c.style ?? "default",
      requestEncoding: c.request_encoding === "REST" ? "REST" : "KVP",
      projection: wmtsProjection(g.crs), tileGrid, wrapX: false, attributions, transition: 0, crossOrigin: co,
    });
  } else if (b.kind === "xyz") {
    source = new XYZ({ url: c.url, maxZoom: c.max_zoom ?? 19, attributions, transition: 0, crossOrigin: co });
  } else {
    const format: string = c.format ?? PNG8;
    source = new TileWMS({
      url: "/ows",
      params: {
        PROJECT: c.project, VERSION: "1.1.1", LAYERS: c.layers, STYLES: "", FORMAT: format,
        TRANSPARENT: format === "image/jpeg" ? "false" : "true", TILED: "true", V: b.version,
      },
      tileGrid: tileGridFor(mapCrs), projection: mapCrs, serverType: "qgis", hidpi: false, transition: 0,
      attributions, crossOrigin: co,
    });
  }
  return new TileLayer({ source, opacity: b.opacity, preload: 1, properties: { basemapId: b.id } });
}
