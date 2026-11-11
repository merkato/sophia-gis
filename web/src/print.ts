// Wydruk widoku mapy w przeglądarce: osobna mapa poza ekranem w rozdzielczości wydruku (te same
// podkłady z katalogu, rastry i warstwy wektorowe projektu), złożona do jednego obrazu i wstawiona
// na stronę A4/A3 z tytułem, skalą, podziałką, strzałką północy, datą i atrybucjami.
// Kafle są pobierane z crossOrigin=anonymous (wymaga CORS — Geoportal i OSM go mają); mapa
// ekranowa działa bez tego, więc usługa bez CORS psuje co najwyżej wydruk, nie widok.
import OlMap from "ol/Map";
import View from "ol/View";
import ImageLayer from "ol/layer/Image";
import TileLayer from "ol/layer/Tile";
import ImageWMS from "ol/source/ImageWMS";
import TileWMS from "ol/source/TileWMS";
import type { Basemap, ProjectConfig } from "./types";
import { basemapLayer, ensureBasemapProjections, tileGridFor } from "./tiles";
import { tileFormats } from "./components/MapView";

export type Paper = "A4" | "A3";
export type Orientation = "landscape" | "portrait";

export interface PrintOptions {
  title: string;
  note: string;
  paper: Paper;
  orientation: Orientation;
  dpi: number;                     // 96 / 150 / 200
  scale: number | null;            // null = cały widoczny obszar mapy
}

export interface PrintSource {
  config: ProjectConfig;
  basemaps: Basemap[];             // aktywne: podkład + nakładki, w kolejności rysowania
  wmsLayers: string[];             // warstwy projektu od spodu do wierzchu
  extent: number[];                // widok na ekranie
  center: number[];
}

const PAPER_MM: Record<Paper, [number, number]> = { A4: [297, 210], A3: [420, 297] };
const MARGIN = 10, HEADER = 14, FOOTER = 20;   // mm

export function mapAreaMm(o: PrintOptions): [number, number] {
  const [a, b] = PAPER_MM[o.paper];
  const [w, h] = o.orientation === "landscape" ? [a, b] : [b, a];
  return [w - 2 * MARGIN, h - 2 * MARGIN - HEADER - FOOTER - (o.note.trim() ? 8 : 0)];
}

const mmToPx = (mm: number, dpi: number) => Math.round((mm / 25.4) * dpi);

/** Składa canvasy warstw OpenLayers w jeden obraz (przykład „export map” z OpenLayers). */
function composite(map: OlMap, size: number[]): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = size[0];
  out.height = size[1];
  const ctx = out.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);
  map.getViewport()?.querySelectorAll<HTMLCanvasElement>(".ol-layer canvas, canvas.ol-layer").forEach((canvas) => {
    if (!canvas.width) return;
    const parent = canvas.parentElement as HTMLElement | null;
    const opacity = parent?.style.opacity || canvas.style.opacity;
    ctx.globalAlpha = opacity === "" || opacity === undefined ? 1 : Number(opacity);
    const t = canvas.style.transform;
    const m = t ? t.match(/^matrix\(([^(]*)\)$/)?.[1].split(",").map(Number) : null;
    const matrix = m ?? [parseFloat(canvas.style.width) / canvas.width, 0, 0, parseFloat(canvas.style.height) / canvas.height, 0, 0];
    ctx.setTransform(matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5]);
    ctx.drawImage(canvas, 0, 0);
  });
  ctx.globalAlpha = 1;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  return out;
}

/** Renderuje mapę poza ekranem i zwraca obraz (data URL JPEG) oraz rzeczywistą skalę. */
export async function renderPrintMap(src: PrintSource, o: PrintOptions): Promise<{ image: string; scale: number; widthMm: number; heightMm: number }> {
  const [wMm, hMm] = mapAreaMm(o);
  const size = [mmToPx(wMm, o.dpi), mmToPx(hMm, o.dpi)];
  const crs = src.config.crs;

  const host = document.createElement("div");
  host.style.cssText = `position:fixed;left:-20000px;top:0;width:${size[0]}px;height:${size[1]}px;`;
  document.body.appendChild(host);

  await ensureBasemapProjections(src.basemaps);
  const layers: (TileLayer | ImageLayer<ImageWMS>)[] = src.basemaps.map((b) => basemapLayer(b, crs, true));
  const formats = tileFormats(src.config);
  const vectors: string[] = [];
  for (const name of src.wmsLayers) {
    const fmt = formats.get(name);
    if (!fmt) { vectors.push(name); continue; }
    layers.push(new TileLayer({
      source: new TileWMS({
        url: "/ows", crossOrigin: "anonymous", tileGrid: tileGridFor(crs), serverType: "qgis", hidpi: false, transition: 0,
        params: { PROJECT: src.config.slug, VERSION: "1.1.1", LAYERS: name, STYLES: "", FORMAT: fmt,
          TRANSPARENT: fmt === "image/jpeg" ? "false" : "true", TILED: "true", V: src.config.version },
      }),
    }));
  }
  if (vectors.length && src.config.slug) {
    layers.push(new ImageLayer({
      // DPI: QGIS Server skaluje grubości linii i symbole do rozdzielczości wydruku
      source: new ImageWMS({
        url: "/ows", crossOrigin: "anonymous", ratio: 1, serverType: "qgis", hidpi: false,
        params: { PROJECT: src.config.slug, VERSION: "1.1.1", FORMAT: "image/png", TRANSPARENT: "true",
          LAYERS: vectors.join(","), DPI: o.dpi },
      }),
    }));
  }

  // Skala: zadana albo taka, by zmieścić cały widoczny obszar; bez przyciągania do poziomów kafli
  const view = new View({ projection: crs, center: src.center, constrainResolution: false });
  let resolution: number;
  if (o.scale) {
    resolution = (o.scale * 0.0254) / o.dpi;
  } else {
    const [minx, miny, maxx, maxy] = src.extent;
    resolution = Math.max((maxx - minx) / size[0], (maxy - miny) / size[1]);
  }
  view.setResolution(resolution);
  const map = new OlMap({ target: host, layers, view, controls: [], interactions: [], pixelRatio: 1 });

  try {
    const image = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Przekroczono czas wczytywania mapy do wydruku (60 s)")), 60000);
      map.once("rendercomplete", () => {
        clearTimeout(timer);
        try {
          resolve(composite(map, size).toDataURL("image/jpeg", 0.92));
        } catch {
          reject(new Error("Przeglądarka zablokowała złożenie obrazu — któraś usługa podkładu nie pozwala na wydruk (brak CORS)."));
        }
      });
      map.renderSync();
    });
    const scale = Math.round((resolution * o.dpi) / 0.0254);
    return { image, scale, widthMm: wMm, heightMm: hMm };
  } finally {
    map.setTarget(undefined);
    host.remove();
  }
}

/** Podziałka: „ładna” długość (1/2/5 × 10^n m) zajmująca ok. 1/5 szerokości mapy. */
function scaleBar(scale: number, widthMm: number): { mm: number; label: string } {
  const target = (widthMm / 5) * scale / 1000;          // metry w terenie
  const pow = 10 ** Math.floor(Math.log10(target));
  const nice = [1, 2, 5, 10].map((k) => k * pow).filter((v) => v <= target).pop() ?? pow;
  return { mm: (nice * 1000) / scale, label: nice >= 1000 ? `${nice / 1000} km` : `${nice} m` };
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** Strona do druku (nowe okno): mapa, tytuł, skala, podziałka, północ, data, źródła. */
export function printPageHtml(r: { image: string; scale: number; widthMm: number; heightMm: number }, o: PrintOptions,
  info: { project: string | null; layers: string[]; attributions: string[] }): string {
  const [pw, ph] = o.orientation === "landscape" ? PAPER_MM[o.paper] : [PAPER_MM[o.paper][1], PAPER_MM[o.paper][0]];
  const bar = scaleBar(r.scale, r.widthMm);
  const date = new Date().toLocaleDateString("pl-PL", { year: "numeric", month: "long", day: "numeric" });
  const sources = [...new Set(info.attributions.filter(Boolean))].join(" · ");
  return `<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>${esc(o.title || "Mapa")}</title>
<style>
@page { size: ${pw}mm ${ph}mm; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #eee; font-family: "Segoe UI", system-ui, sans-serif; color: #1d2430; }
.page { width: ${pw}mm; height: ${ph}mm; padding: ${MARGIN}mm; background: #fff; margin: 0 auto; display: flex; flex-direction: column; }
header { height: ${HEADER}mm; display: flex; align-items: flex-end; justify-content: space-between; border-bottom: 0.4mm solid #1d2430; padding-bottom: 1.5mm; }
header h1 { font-size: 6mm; margin: 0; font-weight: 600; }
header .proj { font-size: 3mm; color: #555; }
.note { font-size: 3.2mm; margin: 2mm 0 0; height: 6mm; overflow: hidden; }
.map { position: relative; margin-top: 2mm; width: ${r.widthMm}mm; height: ${r.heightMm}mm; border: 0.3mm solid #1d2430; }
.map img { width: 100%; height: 100%; display: block; }
.north { position: absolute; top: 3mm; right: 3mm; width: 10mm; background: rgba(255,255,255,.85); border-radius: 1mm; padding: 1mm; }
footer { height: ${FOOTER}mm; display: flex; justify-content: space-between; align-items: flex-start; padding-top: 2mm; font-size: 2.8mm; gap: 6mm; }
.scale b { font-size: 3.4mm; }
.bar { display: flex; margin-top: 1mm; }
.bar span { height: 2mm; border: 0.25mm solid #1d2430; }
.bar span:nth-child(odd) { background: #1d2430; }
.bar-label { display: flex; justify-content: space-between; width: ${bar.mm}mm; font-size: 2.5mm; }
.meta { text-align: right; color: #444; max-width: 60%; }
.toolbar { text-align: center; padding: 8px; font-size: 14px; }
.toolbar button { font-size: 14px; padding: 6px 14px; margin: 0 4px; cursor: pointer; }
@media print { body { background: #fff; } .toolbar { display: none; } .page { margin: 0; } }
</style></head><body>
<div class="toolbar"><button onclick="window.print()">Drukuj / zapisz jako PDF</button><button onclick="window.close()">Zamknij</button></div>
<div class="page">
  <header><h1>${esc(o.title || "Mapa")}</h1><span class="proj">${esc(info.project ?? "")}</span></header>
  ${o.note.trim() ? `<p class="note">${esc(o.note.trim())}</p>` : ""}
  <div class="map"><img src="${r.image}" alt="Mapa">
    <svg class="north" viewBox="0 0 20 30" aria-label="Północ"><path d="M10 2 L16 22 L10 18 L4 22 Z" fill="#1d2430"/><text x="10" y="29" font-size="7" text-anchor="middle" font-family="sans-serif" font-weight="700">N</text></svg>
  </div>
  <footer>
    <div class="scale"><b>Skala 1:${r.scale.toLocaleString("pl-PL")}</b>
      <div class="bar">${[0, 1, 2, 3].map(() => `<span style="width:${bar.mm / 4}mm"></span>`).join("")}</div>
      <div class="bar-label"><span>0</span><span>${bar.label}</span></div>
    </div>
    <div class="meta">${date}${info.layers.length ? ` · Warstwy: ${esc(info.layers.join(", "))}` : ""}${sources ? `<br>Źródła: ${esc(sources)}` : ""}<br>Wydruk z Sophii</div>
  </footer>
</div>
<script>document.querySelector(".map img").addEventListener("load", () => setTimeout(() => window.print(), 300));</script>
</body></html>`;
}
