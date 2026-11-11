import { useEffect, useMemo, useState } from "react";
import { api, type ReportInfo } from "../api";
import type { Basemap, ProjectConfig } from "../types";
import { projectAttributions } from "../attribution";
import { mapAreaMm, printPageHtml, renderPrintMap, type Orientation, type Paper, type PrintOptions } from "../print";

export const SCALES = [500, 1000, 2000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000];
const STORE = "sophia.print";
const SOPHIA = "";                                  // wartość listy: układ Sophii (bez szablonu QGIS)

interface Saved { template?: string; paper?: Paper; orientation?: Orientation; dpi?: number; scale?: number | null }
function loadSaved(): Saved {
  try { return JSON.parse(localStorage.getItem(STORE) ?? "{}"); } catch { return {}; }
}

/**
 * Panel wydruku widoku mapy (obok mapy — mapę można przesuwać, ramka pokazuje obszar wydruku).
 * Dwa rodzaje: układ Sophii (A4/A3, w przeglądarce, z podkładem z katalogu) albo szablon wydruku
 * z projektu QGIS (GetPrint: skala, warstwy, podkład z warstwy projektu, tytuł/opis do etykiet).
 * docs/user/wydruki.md
 */
export function PrintPanel({ config, basemaps, wmsLayers, layerNames, opacity, getView, onFrame, onClose }: {
  config: ProjectConfig;
  opacity: Record<string, number>;     // krycie rastrów i podkładów jak na ekranie
  basemaps: Basemap[];                 // aktywne: podkład + nakładki
  wmsLayers: string[];                 // od spodu
  layerNames: string[];
  getView: () => { extent: number[]; center: number[] } | null;
  onFrame: (sizeMeters: [number, number] | null) => void;   // ramka obszaru wydruku na mapie
  onClose: () => void;
}) {
  const layouts = useMemo(() => config.reports.filter((r) => !r.layer_id), [config.reports]);
  const saved = useMemo(loadSaved, []);
  const [template, setTemplate] = useState<string>(() =>
    saved.template && layouts.some((l) => l.layout === saved.template) ? saved.template : layouts[0]?.layout ?? SOPHIA);
  const [title, setTitle] = useState(config.slug ? config.title : "Mapa");
  const [note, setNote] = useState("");
  const [paper, setPaper] = useState<Paper>(saved.paper ?? "A4");
  const [orientation, setOrientation] = useState<Orientation>(saved.orientation ?? "landscape");
  const [dpi, setDpi] = useState(saved.dpi ?? 150);
  const [scale, setScale] = useState<number | null>(saved.scale ?? null);
  const [info, setInfo] = useState<ReportInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isLayout = template !== SOPHIA;
  const opts: PrintOptions = { title, note, paper, orientation, dpi, scale };
  const layoutMapMm = isLayout ? info?.map_mm ?? null : null;
  const mapMm: [number, number] | null = isLayout ? (layoutMapMm ? [layoutMapMm[0], layoutMapMm[1]] : null) : mapAreaMm(opts);

  // szablon QGIS: rozmiar mapy, etykiety, czy podkład da się wydrukować
  useEffect(() => {
    if (!isLayout || !config.slug) { setInfo(null); return; }
    let cancelled = false;
    api.reportInfo(config.slug, template, basemaps.map((b) => b.id))
      .then((i) => !cancelled && setInfo(i)).catch((e) => !cancelled && setError((e as Error).message));
    return () => { cancelled = true; };
  }, [isLayout, config.slug, template, basemaps]);

  // ramka na mapie: rozmiar pola mapy wydruku w terenie (tylko przy stałej skali)
  useEffect(() => {
    onFrame(scale && mapMm ? [(mapMm[0] * scale) / 1000, (mapMm[1] * scale) / 1000] : null);
  }, [scale, mapMm?.[0], mapMm?.[1]]);    // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onFrame(null), []);   // eslint-disable-line react-hooks/exhaustive-deps

  const remember = () => {
    try { localStorage.setItem(STORE, JSON.stringify({ template, paper, orientation, dpi, scale })); } catch { /* */ }
  };

  const run = async () => {
    const v = getView();
    if (!v) return;
    remember();
    setError(null);
    if (isLayout) {
      // szablon QGIS: środek widoku + skala (albo cały widok); PDF z QGIS Server w nowej karcie
      const p: Record<string, string> = {
        extent: v.extent.join(","), layers: wmsLayers.join(","), dpi: String(dpi),
        basemaps: basemaps.map((b) => b.id).join(","),
      };
      if (scale) p.scale = String(scale);
      if (info?.title_label) p.title = title;
      if (info?.note_label) p.note = note;
      window.open(api.reportUrl(config.slug, template, p), "_blank");
      return;
    }
    const win = window.open("", "_blank");
    if (win) win.document.write("<p style='font-family:sans-serif;padding:20px'>Przygotowywanie wydruku…</p>");
    setBusy(true);
    try {
      const r = await renderPrintMap({ config, basemaps, wmsLayers, extent: v.extent, center: v.center, opacity }, opts);
      const html = printPageHtml(r, opts, {
        project: config.slug ? config.title : null, layers: layerNames,
        attributions: [
          ...basemaps.map((b) => b.attribution ?? b.name),
          ...(config.slug ? projectAttributions(config, wmsLayers).map((a) => a.text) : []),
        ],
      });
      if (win) { win.document.open(); win.document.write(html); win.document.close(); }
      else if (!window.open(URL.createObjectURL(new Blob([html], { type: "text/html" })), "_blank")) {
        setError("Przeglądarka zablokowała nowe okno — zezwól na wyskakujące okna dla tej strony.");
      }
    } catch (e) {
      win?.close();
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const missingBase = isLayout && info ? info.basemaps.filter((b) => !b.layer) : [];

  return (
    <aside className="print-panel form" role="dialog" aria-labelledby="print-title">
      <header>
        <h3 id="print-title">Wydruk</h3>
        <button className="icon" onClick={onClose} title="Zamknij" aria-label="Zamknij">✕</button>
      </header>
      <label className="field"><span>Szablon</span>
        <select value={template} onChange={(e) => { setTemplate(e.target.value); setError(null); }}>
          {layouts.map((l) => <option key={l.layout} value={l.layout}>{l.title} (szablon QGIS)</option>)}
          <option value={SOPHIA}>Układ Sophii — A4/A3</option>
        </select></label>
      <label className="field"><span>Tytuł</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)}
          disabled={isLayout && !!info && !info.title_label}
          title={isLayout && info && !info.title_label ? "Szablon nie ma etykiety o identyfikatorze „tytul”" : undefined} /></label>
      <label className="field"><span>Opis</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="np. stan na dzień, sygnatura sprawy"
          disabled={isLayout && !!info && !info.note_label}
          title={isLayout && info && !info.note_label ? "Szablon nie ma etykiety o identyfikatorze „opis”" : undefined} /></label>
      {!isLayout && (
        <div className="inline">
          <label className="field"><span>Papier</span>
            <select value={paper} onChange={(e) => setPaper(e.target.value as Paper)}>
              <option value="A4">A4</option><option value="A3">A3</option>
            </select></label>
          <label className="field"><span>Orientacja</span>
            <select value={orientation} onChange={(e) => setOrientation(e.target.value as Orientation)}>
              <option value="landscape">pozioma</option><option value="portrait">pionowa</option>
            </select></label>
        </div>
      )}
      <div className="inline">
        <label className="field"><span>Skala</span>
          <select value={scale ?? ""} onChange={(e) => setScale(e.target.value ? Number(e.target.value) : null)}>
            <option value="">cały widok mapy</option>
            {SCALES.map((s) => <option key={s} value={s}>1:{s.toLocaleString("pl-PL")}</option>)}
          </select></label>
        <label className="field"><span>Jakość</span>
          <select value={dpi} onChange={(e) => setDpi(Number(e.target.value))}>
            <option value={96}>szkic (96 dpi)</option><option value={150}>standard (150)</option>
            <option value={200}>wysoka (200)</option>{isLayout && <option value={300}>do druku (300)</option>}
          </select></label>
      </div>
      <p className="muted">
        {scale ? "Niebieska ramka na mapie pokazuje obszar wydruku — przesuń mapę, aby go ustawić."
          : "Wydruk obejmie cały widok mapy (skala dopasuje się do pola mapy)."}
        {mapMm && <> Pole mapy: {Math.round(mapMm[0])} × {Math.round(mapMm[1])} mm.</>}
        {isLayout && info && !info.map_mm && " Szablon nie ma mapy — wydrukuje się bez mapy."}
      </p>
      {missingBase.length > 0 && (
        <div className="notice">
          Podkład „{missingBase.map((b) => b.name).join(", ")}” nie zostanie wydrukowany z szablonem QGIS — projekt nie
          ma warstwy z tej usługi. Dodaj ją w QGIS (może być „Tylko w QGIS”) albo wybierz „Układ Sophii”.
        </div>
      )}
      {error && <div className="error">{error}</div>}
      <div className="actions">
        <button className="primary" disabled={busy || (isLayout && !info)} onClick={run}>
          {busy ? "Przygotowywanie…" : isLayout ? "Utwórz PDF" : "Utwórz wydruk"}</button>
        <button onClick={onClose}>Zamknij</button>
      </div>
      <p className="muted">Wydruk otworzy się w nowej karcie.{isLayout ? "" : " Tam „Drukuj” albo „Zapisz jako PDF”."}</p>
    </aside>
  );
}
