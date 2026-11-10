import { useEffect, useMemo, useRef, useState } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import { ScaleLine, defaults as defaultControls } from "ol/control";
import { transformExtent } from "ol/proj";
import { adminApi, type BasemapInput } from "../api";
import type { AdminProject, Basemap, WmtsCapabilities } from "../types";
import { PNG8, basemapLayer, ensureBasemapProjections, tileGridFor } from "../tiles";
import { ensureProjection } from "../projections";

const MAP_CRS = "EPSG:2180";        // układ map Sophii (projekty w PUWG 1992)
const POLAND_2180: [number, number, number, number] = [140000, 120000, 880000, 800000];

interface Props {
  basemap: Basemap | null;          // null = nowy
  nextSortOrder: number;
  onSaved: () => void;
  onCancel: () => void;
}

type Draft = BasemapInput;

const emptyDraft = (sort: number): Draft => ({
  name: "", kind: "wmts", is_overlay: false, opacity: 1, visible_default: false, enabled: true,
  sort_order: sort, attribution: "", config: {},
});

function defaultAttribution(url: string | null | undefined, title: string | null): string {
  if (url && /geoportal\.gov\.pl/i.test(url)) return "© GUGiK, geoportal.gov.pl";
  return title ?? "";
}

/** Edytor podkładu: WMTS z GetCapabilities, XYZ albo warstwa projektu Sophii; podgląd na żywo. */
export function BasemapEditor({ basemap, nextSortOrder, onSaved, onCancel }: Props) {
  const [draft, setDraft] = useState<Draft>(() => (basemap ? { ...basemap, attribution: basemap.attribution ?? "" } : emptyDraft(nextSortOrder)));
  const [capsUrl, setCapsUrl] = useState<string>(basemap?.config.capabilities_url ?? "");
  const [capsXml, setCapsXml] = useState("");
  const [pasteXml, setPasteXml] = useState(false);
  const [caps, setCaps] = useState<WmtsCapabilities | null>(null);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setConfig = (patch: Record<string, unknown>) => setDraft((d) => ({ ...d, config: { ...d.config, ...patch } }));

  useEffect(() => { if (draft.kind === "sophia") adminApi.projects().then(setProjects).catch(() => {}); }, [draft.kind]);

  // ---------------------------------------------------------------- WMTS: GetCapabilities
  const loadCaps = async () => {
    setBusy(true); setError(null);
    try {
      const c = await adminApi.capabilities(pasteXml ? { xml: capsXml } : { url: capsUrl });
      setCaps(c);
      // wybór domyślny: obecna warstwa, a jeśli brak — pierwsza
      const layer = c.layers.find((l) => l.identifier === draft.config.layer) ?? c.layers[0];
      chooseLayer(c, layer.identifier, true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const chooseLayer = (c: WmtsCapabilities, layerId: string, keepCurrent = false) => {
    const l = c.layers.find((x) => x.identifier === layerId)!;
    const cur = draft.config;
    // macierz w układzie mapy (bez przeliczania w przeglądarce), a jeśli nie ma — pierwsza
    const ms = (keepCurrent && l.matrix_sets.includes(cur.matrix_set) && cur.matrix_set)
      || l.matrix_sets.find((m) => c.matrix_sets[m].crs === MAP_CRS) || l.matrix_sets[0];
    const format = (keepCurrent && l.formats.includes(cur.format) && cur.format) || l.formats[0];
    const style = (keepCurrent && l.styles.includes(cur.style) && cur.style) || l.default_style || "default";
    applyWmts(c, l.identifier, ms, format, style);
    setDraft((d) => ({
      ...d,
      name: d.name || l.title,
      attribution: d.attribution || defaultAttribution(c.capabilities_url ?? c.kvp_url, c.title),
    }));
  };

  const applyWmts = (c: WmtsCapabilities, layerId: string, ms: string, format: string, style: string) => {
    const l = c.layers.find((x) => x.identifier === layerId)!;
    const rest = l.resource_urls[format];
    setConfig({
      capabilities_url: c.capabilities_url ?? capsUrl ?? null,
      url: rest ?? c.kvp_url,
      request_encoding: rest ? "REST" : "KVP",
      layer: layerId, matrix_set: ms, format, style,
      tile_grid: c.matrix_sets[ms],
      wgs84_bbox: l.wgs84_bbox,
    });
  };

  const capsLayer = caps?.layers.find((l) => l.identifier === draft.config.layer) ?? null;

  // ---------------------------------------------------------------- podgląd
  const previewRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<OlMap | null>(null);
  const [mapReady, setMapReady] = useState(false);
  useEffect(() => {
    let map: OlMap | null = null;
    ensureProjection(MAP_CRS).then(() => {
      const grid = tileGridFor(MAP_CRS);
      map = new OlMap({
        target: previewRef.current!,
        controls: defaultControls({ attributionOptions: { collapsible: false } }).extend([new ScaleLine()]),
        view: new View({ projection: MAP_CRS, resolutions: grid.getResolutions(), constrainResolution: true }),
      });
      map.getView().fit(POLAND_2180);
      mapRef.current = map;
      setMapReady(true);
    });
    return () => { map?.setTarget(undefined); mapRef.current = null; };
  }, []);

  const previewable = useMemo(() => {
    const c = draft.config;
    if (draft.kind === "wmts") return !!(c.url && c.layer && c.tile_grid);
    if (draft.kind === "xyz") return !!c.url;
    return !!(c.project && c.layers);
  }, [draft]);

  // tylko zmiany wpływające na kafle przebudowują podgląd (nie np. wpisywanie nazwy)
  const previewKey = JSON.stringify([draft.kind, draft.config, draft.opacity, draft.attribution]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getLayers().clear();
    if (!previewable) return;
    const b = { ...draft, id: -1, version: Date.now(), attribution: draft.attribution || null } as Basemap;
    ensureBasemapProjections([b]).then(() => map.addLayer(basemapLayer(b, MAP_CRS))).catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey, previewable, mapReady]);

  const zoomToLayer = () => {
    const bb = draft.config.wgs84_bbox as number[] | null;
    if (bb && mapRef.current) mapRef.current.getView().fit(transformExtent(bb, "EPSG:4326", MAP_CRS), { padding: [10, 10, 10, 10] });
  };

  // ---------------------------------------------------------------- zapis
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body = { ...draft, attribution: draft.attribution || null };
      if (basemap) await adminApi.updateBasemap(basemap.id, body); else await adminApi.createBasemap(body);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const grid = draft.config.tile_grid;
  const reprojected = draft.kind === "wmts" && grid && grid.crs !== MAP_CRS;

  return (
    <div className="admin-split">
      <section className="form basemap-form">
        <h3>{basemap ? `Edycja podkładu: ${basemap.name}` : "Nowy podkład"}</h3>
        {error && <div className="error">{error}</div>}

        <label className="field"><span>Rodzaj</span>
          <select value={draft.kind} onChange={(e) => { setCaps(null); set({ kind: e.target.value as Draft["kind"], config: {} }); }}>
            <option value="wmts">WMTS (z GetCapabilities)</option>
            <option value="xyz">XYZ / TMS (szablon {"{z}/{x}/{y}"})</option>
            <option value="sophia">Warstwa projektu Sophii (np. biblioteka rastrów)</option>
          </select>
        </label>

        {draft.kind === "wmts" && (
          <fieldset>
            <legend>1. GetCapabilities</legend>
            <div className="inline">
              <label className="check"><input type="radio" checked={!pasteXml} onChange={() => setPasteXml(false)} /> adres</label>
              <label className="check"><input type="radio" checked={pasteXml} onChange={() => setPasteXml(true)} /> wklej XML</label>
            </div>
            {pasteXml
              ? <textarea rows={6} placeholder="<Capabilities …>" value={capsXml} onChange={(e) => setCapsXml(e.target.value)} />
              : <input placeholder="https://…/WMTS?service=WMTS&request=GetCapabilities" value={capsUrl} onChange={(e) => setCapsUrl(e.target.value)} />}
            <button onClick={loadCaps} disabled={busy || (pasteXml ? !capsXml.trim() : !capsUrl.trim())}>{busy ? "Wczytuję…" : "Wczytaj usługę"}</button>
            {caps?.title && <p className="muted">{caps.title}</p>}
          </fieldset>
        )}

        {draft.kind === "wmts" && caps && capsLayer && (
          <fieldset>
            <legend>2. Warstwa i kafle</legend>
            <label className="field"><span>Warstwa ({caps.layers.length})</span>
              <select value={capsLayer.identifier} onChange={(e) => chooseLayer(caps, e.target.value)}>
                {caps.layers.map((l) => <option key={l.identifier} value={l.identifier}>{l.title}{l.title !== l.identifier ? ` (${l.identifier})` : ""}</option>)}
              </select>
            </label>
            <label className="field"><span>Macierz kafli</span>
              <select value={draft.config.matrix_set} onChange={(e) => applyWmts(caps, capsLayer.identifier, e.target.value, draft.config.format, draft.config.style)}>
                {capsLayer.matrix_sets.map((m) => (
                  <option key={m} value={m}>{m} — {caps.matrix_sets[m].crs}{caps.matrix_sets[m].crs === MAP_CRS ? " (zgodna z mapą)" : " (przeliczana w przeglądarce)"}</option>
                ))}
              </select>
            </label>
            <label className="field"><span>Format</span>
              <select value={draft.config.format} onChange={(e) => applyWmts(caps, capsLayer.identifier, draft.config.matrix_set, e.target.value, draft.config.style)}>
                {capsLayer.formats.map((f) => <option key={f}>{f}</option>)}
              </select>
            </label>
            {capsLayer.styles.length > 1 && (
              <label className="field"><span>Styl</span>
                <select value={draft.config.style} onChange={(e) => applyWmts(caps, capsLayer.identifier, draft.config.matrix_set, draft.config.format, e.target.value)}>
                  {capsLayer.styles.map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
            )}
          </fieldset>
        )}

        {draft.kind === "wmts" && !caps && draft.config.layer && (
          <p className="muted">Zapisana konfiguracja: <code>{draft.config.layer}</code> · {draft.config.matrix_set} · {draft.config.format}. „Wczytaj usługę”, by zmienić warstwę lub macierz.</p>
        )}

        {draft.kind === "xyz" && (
          <fieldset>
            <legend>Kafle XYZ</legend>
            <label className="field"><span>Szablon adresu</span>
              <input placeholder="https://tile.openstreetmap.org/{z}/{x}/{y}.png" value={draft.config.url ?? ""} onChange={(e) => setConfig({ url: e.target.value })} /></label>
            <label className="field"><span>Maksymalny poziom</span>
              <input type="number" className="num" value={draft.config.max_zoom ?? 19} onChange={(e) => setConfig({ max_zoom: Number(e.target.value) })} /></label>
          </fieldset>
        )}

        {draft.kind === "sophia" && (
          <fieldset>
            <legend>Warstwa z projektu Sophii</legend>
            <label className="field"><span>Projekt</span>
              <select value={draft.config.project ?? ""} onChange={(e) => setConfig({ project: e.target.value })}>
                <option value="">— wybierz —</option>
                {projects.map((p) => <option key={p.slug} value={p.slug}>{p.title} ({p.slug})</option>)}
              </select></label>
            <label className="field"><span>Nazwa warstwy WMS (nazwa krótka w QGIS lub nazwa grupy)</span>
              <input value={draft.config.layers ?? ""} onChange={(e) => setConfig({ layers: e.target.value })} /></label>
            <label className="field"><span>Format kafli</span>
              <select value={draft.config.format ?? PNG8} onChange={(e) => setConfig({ format: e.target.value })}>
                <option value={PNG8}>PNG 8-bit (przezroczystość)</option>
                <option value="image/jpeg">JPEG (bez przezroczystości, mniejsze)</option>
              </select></label>
            <p className="muted">Kafle idą przez serwer Sophii i wspólny cache — jeden zestaw kafli dla wszystkich projektów.
              Podkład widzą tylko użytkownicy z dostępem do wybranego projektu (najprościej: projekt publiczny).</p>
          </fieldset>
        )}

        <fieldset>
          <legend>{draft.kind === "wmts" ? "3. Wyświetlanie" : "Wyświetlanie"}</legend>
          <label className="field"><span>Nazwa w przełączniku</span>
            <input value={draft.name} onChange={(e) => set({ name: e.target.value })} /></label>
          <label className="field"><span>Atrybucja (źródło danych)</span>
            <input value={draft.attribution ?? ""} onChange={(e) => set({ attribution: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={draft.is_overlay} onChange={(e) => set({ is_overlay: e.target.checked })} /> Nakładka (rysowana nad podkładem, np. cieniowanie)</label>
          <label className="field"><span>Krycie: {Math.round(draft.opacity * 100)}%</span>
            <input type="range" min={0.1} max={1} step={0.05} value={draft.opacity} onChange={(e) => set({ opacity: Number(e.target.value) })} /></label>
          <label className="check"><input type="checkbox" checked={draft.visible_default} onChange={(e) => set({ visible_default: e.target.checked })} />
            {draft.is_overlay ? " Nakładka włączona na start" : " Podkład startowy"}</label>
          <label className="check"><input type="checkbox" checked={draft.enabled ?? true} onChange={(e) => set({ enabled: e.target.checked })} /> Włączony (widoczny w WebUI)</label>
        </fieldset>

        <div className="actions">
          <button className="primary" onClick={save} disabled={busy || !draft.name || !previewable}>Zapisz</button>
          <button onClick={onCancel}>Anuluj</button>
        </div>
      </section>

      <section className="preview">
        <div className="preview-head">
          <strong>Podgląd</strong>
          {reprojected && <span className="muted">kafle w {grid.crs} — przeliczane w przeglądarce (wolniej, mniej ostro)</span>}
          {draft.config.wgs84_bbox && <button onClick={zoomToLayer}>Przybliż do zasięgu</button>}
        </div>
        <div ref={previewRef} className="preview-map" />
      </section>
    </div>
  );
}
