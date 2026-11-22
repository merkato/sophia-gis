// Pomiar na mapie: długość (linia) i powierzchnia (poligon) z etykietami przy szkicu.
// W układzie metrycznym projektu (np. EPSG:2180) — wartości płaskie w tym układzie (jak „kartezjańskie” w QGIS);
// w układach kątowych — geodezyjnie na kuli (ol/sphere). Pomiary zostają na mapie do zmiany narzędzia;
// Esc przerywa szkic, Backspace cofa wierzchołek, Delete czyści wszystkie pomiary.
import type OlMap from "ol/Map";
import Overlay from "ol/Overlay";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import { Draw, Modify, Snap } from "ol/interaction";
import { Circle, Fill, Stroke, Style } from "ol/style";
import { unByKey } from "ol/Observable";
import type { EventsKey } from "ol/events";
import { getArea, getLength } from "ol/sphere";
import type Feature from "ol/Feature";
import type { Geometry, LineString, MultiLineString, MultiPolygon, Polygon } from "ol/geom";
import type Projection from "ol/proj/Projection";

export type MeasureKind = "length" | "area";

const nf = (v: number, digits: number) => v.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function formatLength(m: number): string {
  return m < 1000 ? `${nf(m, 2)} m` : `${nf(m / 1000, 3)} km`;
}

export function formatArea(m2: number): string {
  if (m2 < 10000) return `${nf(m2, 1)} m²`;
  if (m2 < 1e8) return `${nf(m2 / 10000, 4)} ha (${nf(m2, 0)} m²)`;
  return `${nf(m2 / 1e6, 3)} km² (${nf(m2 / 10000, 0)} ha)`;
}

/** Długość i powierzchnia w układzie mapy: płasko w układzie metrycznym, geodezyjnie w kątowym. */
function measurer(proj: Projection) {
  const planar = proj.getUnits() === "m";
  const pathLength = (coords: number[][]) =>
    coords.reduce((s, c, i, a) => (i ? s + Math.hypot(c[0] - a[i - 1][0], c[1] - a[i - 1][1]) : 0), 0);
  const lengthOf = (g: Geometry): number => {
    if (!planar) return getLength(g, { projection: proj });
    switch (g.getType()) {
      case "LineString": return (g as LineString).getLength();
      case "MultiLineString": return (g as MultiLineString).getLineStrings().reduce((s, l) => s + l.getLength(), 0);
      case "Polygon": return (g as Polygon).getLinearRings().reduce((s, r) => s + pathLength(r.getCoordinates()), 0);
      case "MultiPolygon": return (g as MultiPolygon).getPolygons().reduce((s, p) => s + lengthOf(p), 0);
      default: return 0;
    }
  };
  const areaOf = (g: Polygon | MultiPolygon) => (planar ? g.getArea() : getArea(g, { projection: proj }));
  /** Poligon — powierzchnia i obwód (z pierścieniami wewnętrznymi), linia — długość, punkt — brak etykiety. */
  const text = (g: Geometry): string | null => {
    const t = g.getType();
    if (t === "Polygon" || t === "MultiPolygon") return `${formatArea(areaOf(g as Polygon))}\nobwód ${formatLength(lengthOf(g))}`;
    if (t === "LineString" || t === "MultiLineString") return formatLength(lengthOf(g));
    return null;
  };
  /** Miejsce etykiety: wnętrze (największej części) poligonu albo koniec linii. */
  const anchor = (g: Geometry): number[] | null => {
    const t = g.getType();
    if (t === "Polygon") return (g as Polygon).getInteriorPoint().getCoordinates().slice(0, 2);
    if (t === "MultiPolygon") {
      const parts = (g as MultiPolygon).getPolygons();
      if (!parts.length) return null;
      return parts.reduce((a, b) => (b.getArea() > a.getArea() ? b : a)).getInteriorPoint().getCoordinates().slice(0, 2);
    }
    if (t === "LineString") return (g as LineString).getLastCoordinate().slice(0, 2);
    if (t === "MultiLineString") return (g as MultiLineString).getLastCoordinate().slice(0, 2);
    return null;
  };
  return { planar, lengthOf, areaOf, text, anchor };
}

/** Etykieta powierzchni i obwodu (długości) przy szkicach edycji: rysowanie i zmiana wierzchołków.
 * Śledzi szkic na żywo, po zakończeniu zostaje z ostatnią wartością do następnego szkicu albo zmiany narzędzia.
 * Zwraca funkcję sprzątającą. */
export function attachEditLabels(map: OlMap, interactions: (Draw | Modify)[]): () => void {
  const m = measurer(map.getView().getProjection());
  const el = document.createElement("div");
  el.className = "measure-label live";
  const overlay = new Overlay({ element: el, offset: [0, -12], positioning: "bottom-center", stopEvent: false });
  map.addOverlay(overlay);
  let watch: EventsKey | null = null;
  const stop = () => { if (watch) unByKey(watch); watch = null; };
  const update = (g: Geometry) => {
    const t = m.text(g);
    const pos = t ? m.anchor(g) : null;
    if (!t || !pos) { overlay.setPosition(undefined); return; }
    el.textContent = t;
    overlay.setPosition(pos);
  };
  const follow = (g: Geometry | null | undefined) => {
    stop();
    if (!g) return;
    el.classList.replace("done", "live");
    update(g);
    watch = g.on("change", () => update(g));
  };
  const finish = () => { stop(); el.classList.replace("live", "done"); };
  const keys: EventsKey[] = [];
  for (const i of interactions) {
    if (i instanceof Draw) {
      keys.push(i.on("drawstart", (e) => follow(e.feature.getGeometry())));
      keys.push(i.on("drawend", (e) => { const g = e.feature.getGeometry(); if (g) update(g); finish(); }));
      keys.push(i.on("drawabort", () => { stop(); overlay.setPosition(undefined); }));
    } else {
      keys.push(i.on("modifystart", (e) => follow((e.features.item(0) as Feature<Geometry> | undefined)?.getGeometry())));
      keys.push(i.on("modifyend", finish));
    }
  }
  return () => { stop(); keys.forEach((k) => unByKey(k)); map.removeOverlay(overlay); };
}

const style = [
  new Style({ fill: new Fill({ color: "rgba(255, 196, 0, 0.18)" }), stroke: new Stroke({ color: "#fff", width: 5 }) }),
  new Style({
    stroke: new Stroke({ color: "#e8590c", width: 2.5, lineDash: [8, 6] }),
    image: new Circle({ radius: 5, fill: new Fill({ color: "#e8590c" }), stroke: new Stroke({ color: "#fff", width: 2 }) }),
  }),
];

/** Włącza pomiar na mapie; zwraca funkcję sprzątającą (usuwa szkice, etykiety i interakcje). */
export function startMeasure(map: OlMap, kind: MeasureKind, snapSource?: VectorSource<Feature<Geometry>> | null): () => void {
  const source = new VectorSource<Feature<Geometry>>();
  const layer = new VectorLayer({ source, style, zIndex: 1000 });
  map.addLayer(layer);
  const proj = map.getView().getProjection();
  const { planar, lengthOf, areaOf } = measurer(proj);
  const unit = planar ? ` (płasko, ${proj.getCode()})` : " (geodezyjnie)";
  const text = (g: LineString | Polygon) => kind === "area"
    ? `${formatArea(areaOf(g as Polygon))}\nobwód ${formatLength(lengthOf(g))}`
    : formatLength(lengthOf(g));

  const overlays: Overlay[] = [];
  const label = (cls: string) => {
    const el = document.createElement("div");
    el.className = `measure-label ${cls}`;
    const o = new Overlay({ element: el, offset: [0, -12], positioning: "bottom-center", stopEvent: false });
    map.addOverlay(o);
    overlays.push(o);
    return o;
  };

  const draw = new Draw({ source, type: kind === "area" ? "Polygon" : "LineString", style });
  const snap = snapSource ? new Snap({ source: snapSource }) : null;
  let live: Overlay | null = null;
  let changeKey: EventsKey | null = null;
  const hint = label("hint");
  (hint.getElement() as HTMLElement).textContent =
    kind === "area" ? "Klikaj wierzchołki, dwuklik kończy poligon" : "Klikaj punkty linii, dwuklik kończy";
  const moveKey = map.on("pointermove", (e) => { if (!live) hint.setPosition(e.coordinate); });
  const leave = () => hint.setPosition(undefined);
  const viewport = map.getViewport() as HTMLElement | undefined;
  viewport?.addEventListener("mouseout", leave);

  draw.on("drawstart", (e) => {
    hint.setPosition(undefined);
    live = label("live");
    const g = e.feature.getGeometry() as LineString | Polygon;
    changeKey = g.on("change", () => {
      const pos = g.getType() === "Polygon" ? (g as Polygon).getInteriorPoint().getCoordinates() : (g as LineString).getLastCoordinate();
      (live!.getElement() as HTMLElement).textContent = text(g);
      live!.setPosition(pos.slice(0, 2));
    });
  });
  draw.on("drawend", (e) => {
    const g = e.feature.getGeometry() as LineString | Polygon;
    const el = live!.getElement() as HTMLElement;
    el.textContent = text(g);
    el.title = `Pomiar${unit}`;
    el.classList.replace("live", "done");
    if (changeKey) unByKey(changeKey);
    live = null;
  });
  draw.on("drawabort", () => {
    if (changeKey) unByKey(changeKey);
    if (live) { map.removeOverlay(live); overlays.splice(overlays.indexOf(live), 1); live = null; }
  });

  const clearAll = () => {
    draw.abortDrawing();
    source.clear();
    for (const o of overlays.filter((x) => x !== hint)) map.removeOverlay(o);
    overlays.splice(0, overlays.length, hint);
  };
  const onKey = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
    if (e.key === "Escape") draw.abortDrawing();
    else if (e.key === "Backspace") { draw.removeLastPoint(); e.preventDefault(); }
    else if (e.key === "Delete") clearAll();
  };
  document.addEventListener("keydown", onKey);
  map.addInteraction(draw);
  if (snap) map.addInteraction(snap);

  return () => {
    document.removeEventListener("keydown", onKey);
    viewport?.removeEventListener("mouseout", leave);
    unByKey(moveKey);
    if (changeKey) unByKey(changeKey);
    map.removeInteraction(draw);
    if (snap) map.removeInteraction(snap);
    for (const o of overlays) map.removeOverlay(o);
    map.removeLayer(layer);
  };
}
