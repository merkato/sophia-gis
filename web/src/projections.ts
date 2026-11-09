import proj4 from "proj4";
import { register } from "ol/proj/proj4";
import { get as getProjection } from "ol/proj";

// Polskie układy odniesienia — rejestrowane zawsze, inne pobierane na żądanie z epsg.io.
// Uwaga: WMS wołamy w wersji 1.1.1 (BBOX zawsze x,y), co omija problem kolejności osi
// w EPSG:2176–2180 obecny w WMS 1.3.0.
proj4.defs([
  ["EPSG:2180", "+proj=tmerc +lat_0=0 +lon_0=19 +k=0.9993 +x_0=500000 +y_0=-5300000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"],
  ["EPSG:2176", "+proj=tmerc +lat_0=0 +lon_0=15 +k=0.999923 +x_0=5500000 +y_0=0 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"],
  ["EPSG:2177", "+proj=tmerc +lat_0=0 +lon_0=18 +k=0.999923 +x_0=6500000 +y_0=0 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"],
  ["EPSG:2178", "+proj=tmerc +lat_0=0 +lon_0=21 +k=0.999923 +x_0=7500000 +y_0=0 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"],
  ["EPSG:2179", "+proj=tmerc +lat_0=0 +lon_0=24 +k=0.999923 +x_0=8500000 +y_0=0 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"],
]);
register(proj4);

export async function ensureProjection(code: string): Promise<void> {
  if (getProjection(code)) return;
  const num = code.split(":")[1];
  const res = await fetch(`https://epsg.io/${num}.proj4`);
  if (!res.ok) throw new Error(`Nieznany układ ${code}`);
  proj4.defs(code, await res.text());
  register(proj4);
}
