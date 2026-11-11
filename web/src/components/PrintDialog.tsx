import { useState } from "react";
import type { Basemap, ProjectConfig } from "../types";
import { mapAreaMm, printPageHtml, renderPrintMap, type Orientation, type Paper, type PrintOptions } from "../print";

const SCALES = [500, 1000, 2000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000];
const STORE = "sophia.print";

function loadOpts(title: string): PrintOptions {
  try {
    const s = JSON.parse(localStorage.getItem(STORE) ?? "{}");
    return { title, note: "", paper: s.paper ?? "A4", orientation: s.orientation ?? "landscape", dpi: s.dpi ?? 150, scale: null };
  } catch {
    return { title, note: "", paper: "A4", orientation: "landscape", dpi: 150, scale: null };
  }
}

/**
 * Wydruk widoku mapy (bez szablonu QGIS): bieżący widok z podkładami i warstwami na stronie
 * A4/A3 — tytuł, skala, podziałka, data, źródła. Strona otwiera się w nowej karcie; „Drukuj”
 * pozwala też zapisać PDF.
 */
export function PrintDialog({ config, basemaps, wmsLayers, layerNames, extent, center, onClose }: {
  config: ProjectConfig; basemaps: Basemap[]; wmsLayers: string[]; layerNames: string[];
  extent: number[]; center: number[]; onClose: () => void;
}) {
  const [o, setO] = useState<PrintOptions>(() => loadOpts(config.slug ? config.title : "Mapa"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (p: Partial<PrintOptions>) => setO((x) => ({ ...x, ...p }));
  const [wMm, hMm] = mapAreaMm(o);

  const run = async () => {
    try { localStorage.setItem(STORE, JSON.stringify({ paper: o.paper, orientation: o.orientation, dpi: o.dpi })); } catch { /* */ }
    // okno otwieramy od razu (w odpowiedzi na kliknięcie), żeby nie zablokowała go przeglądarka
    const win = window.open("", "_blank");
    if (win) win.document.write("<p style='font-family:sans-serif;padding:20px'>Przygotowywanie wydruku…</p>");
    setBusy(true);
    setError(null);
    try {
      const r = await renderPrintMap({ config, basemaps, wmsLayers, extent, center }, o);
      const html = printPageHtml(r, o, {
        project: config.slug ? config.title : null, layers: layerNames,
        attributions: basemaps.map((b) => b.attribution ?? b.name),
      });
      if (win) {
        win.document.open();
        win.document.write(html);
        win.document.close();
      } else {
        const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
        window.open(url, "_blank") ?? setError("Przeglądarka zablokowała nowe okno — zezwól na wyskakujące okna dla tej strony.");
      }
      onClose();
    } catch (e) {
      win?.close();
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="dialog print-dialog form" role="dialog" aria-labelledby="print-title">
        <h3 id="print-title">Wydruk widoku mapy</h3>
        <label className="field"><span>Tytuł</span>
          <input value={o.title} onChange={(e) => set({ title: e.target.value })} autoFocus /></label>
        <label className="field"><span>Opis (opcjonalnie)</span>
          <input value={o.note} onChange={(e) => set({ note: e.target.value })} placeholder="np. stan na dzień, sygnatura sprawy" /></label>
        <div className="inline">
          <label className="field"><span>Papier</span>
            <select value={o.paper} onChange={(e) => set({ paper: e.target.value as Paper })}>
              <option value="A4">A4</option><option value="A3">A3</option>
            </select></label>
          <label className="field"><span>Orientacja</span>
            <select value={o.orientation} onChange={(e) => set({ orientation: e.target.value as Orientation })}>
              <option value="landscape">pozioma</option><option value="portrait">pionowa</option>
            </select></label>
          <label className="field"><span>Jakość</span>
            <select value={o.dpi} onChange={(e) => set({ dpi: Number(e.target.value) })}>
              <option value={96}>szkic (96 dpi)</option><option value={150}>standard (150 dpi)</option><option value={200}>wysoka (200 dpi)</option>
            </select></label>
        </div>
        <label className="field"><span>Skala</span>
          <select value={o.scale ?? ""} onChange={(e) => set({ scale: e.target.value ? Number(e.target.value) : null })}>
            <option value="">cały widoczny obszar mapy</option>
            {SCALES.map((s) => <option key={s} value={s}>1:{s.toLocaleString("pl-PL")}</option>)}
          </select></label>
        <p className="muted">Pole mapy: {Math.round(wMm)} × {Math.round(hMm)} mm. Środek wydruku = środek widoku na ekranie.
          Wydruk otworzy się w nowej karcie — tam „Drukuj” albo „Zapisz jako PDF”.</p>
        {error && <div className="error">{error}</div>}
        <div className="actions">
          <button className="primary" disabled={busy} onClick={run}>{busy ? "Przygotowywanie…" : "Utwórz wydruk"}</button>
          <button disabled={busy} onClick={onClose}>Anuluj</button>
        </div>
      </div>
    </div>
  );
}
