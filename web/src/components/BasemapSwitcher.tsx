import type { Basemap } from "../types";

interface Props {
  basemaps: Basemap[];
  baseId: number | null;
  overlayIds: Set<number>;
  onBase: (id: number | null) => void;
  onToggleOverlay: (id: number) => void;
}

/** Podkłady z katalogu Sophii: jeden podkład (radio) + dowolne nakładki (np. cieniowanie). */
export function BasemapSwitcher({ basemaps, baseId, overlayIds, onBase, onToggleOverlay }: Props) {
  const bases = basemaps.filter((b) => !b.is_overlay);
  const overlays = basemaps.filter((b) => b.is_overlay);
  if (!basemaps.length) return null;
  return (
    <section className="basemaps">
      <h3>Podkład</h3>
      <ul className="tree">
        {bases.map((b) => (
          <li key={b.id} className="tree-row">
            <label>
              <input type="radio" name="basemap" checked={baseId === b.id} onChange={() => onBase(b.id)} />
              {b.name}
            </label>
          </li>
        ))}
        <li className="tree-row">
          <label className="muted">
            <input type="radio" name="basemap" checked={baseId === null} onChange={() => onBase(null)} />
            bez podkładu
          </label>
        </li>
      </ul>
      {overlays.length > 0 && (
        <>
          <h3>Nakładki</h3>
          <ul className="tree">
            {overlays.map((b) => (
              <li key={b.id} className="tree-row">
                <label>
                  <input type="checkbox" checked={overlayIds.has(b.id)} onChange={() => onToggleOverlay(b.id)} />
                  {b.name}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// --- wybór zapamiętany w przeglądarce (wygoda; bez niego działają ustawienia domyślne katalogu)
const KEY = "sophia.basemaps";

export function initialBasemapChoice(basemaps: Basemap[]): { baseId: number | null; overlayIds: Set<number> } {
  const ids = new Set(basemaps.map((b) => b.id));
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (saved && (saved.baseId === null || ids.has(saved.baseId))) {
      return { baseId: saved.baseId, overlayIds: new Set((saved.overlayIds ?? []).filter((i: number) => ids.has(i))) };
    }
  } catch { /* brak dostępu do localStorage */ }
  const bases = basemaps.filter((b) => !b.is_overlay);
  const base = bases.find((b) => b.visible_default) ?? bases[0];
  return {
    baseId: base?.id ?? null,
    overlayIds: new Set(basemaps.filter((b) => b.is_overlay && b.visible_default).map((b) => b.id)),
  };
}

export function saveBasemapChoice(baseId: number | null, overlayIds: Set<number>) {
  try { localStorage.setItem(KEY, JSON.stringify({ baseId, overlayIds: [...overlayIds] })); } catch { /* jw. */ }
}
