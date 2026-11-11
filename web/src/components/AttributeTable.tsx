import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { FieldDef, GeoJSONFeature, ProjectConfig } from "../types";
import { fileName, isUrl } from "./Files";
import { useFloatingWindow } from "./FloatingWindow";

const PAGE = 100;

type Labels = Record<string, Map<string, string>>;   // pole relacyjne -> wartość -> etykieta

function loadHidden(key: string): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(key) ?? "[]")); } catch { return new Set(); }
}
function saveHidden(key: string, s: Set<string>) {
  try { localStorage.setItem(key, JSON.stringify([...s])); } catch { /* brak storage */ }
}

/** Wartość komórki tak, jak w formularzu: etykiety list wartości i słowników, nazwy plików, ✓. */
function cellText(f: FieldDef, v: unknown, labels: Labels): string {
  if (v === null || v === undefined || v === "") return "";
  const s = String(v);
  const cfg = f.widget_config ?? {};
  switch (f.widget) {
    case "ValueMap": {
      const raw = cfg.map;
      const entries: [string, string][] = Array.isArray(raw)
        ? raw.flatMap((o) => Object.entries(o as Record<string, string>))
        : Object.entries((raw ?? {}) as Record<string, string>);
      return entries.find(([, val]) => String(val) === s)?.[0] ?? s;
    }
    case "CheckBox":
      return v === true || s === String(cfg.CheckedState ?? "true") ? "✓" : "—";
    case "RelationReference":
    case "ValueRelation":
      return labels[f.name]?.get(s) ?? s;
    case "ExternalResource":
      return isUrl(s) ? `↗ ${s.replace(/^https?:\/\//i, "")}` : `📎 ${fileName(s)}`;
    case "DateTime":
      return s.replace("T", " ").slice(0, String(cfg.field_format ?? "").includes("HH") ? 16 : 10);
    default:
      return s;
  }
}

/**
 * Tabela atrybutów warstwy (jak w QGIS): okno nad mapą, sortowanie po kolumnie (na serwerze),
 * wyszukiwanie, stronicowanie, tymczasowe ukrywanie kolumn (zapamiętane w tej przeglądarce).
 * Kliknięcie wiersza otwiera obiekt w formularzu, a dla warstw z geometrią przybliża mapę.
 */
export function AttributeTable({ config, layerId, reloadToken, selectedId, onOpen, onNew, onClose }: {
  config: ProjectConfig;
  layerId: string;
  reloadToken: number;
  selectedId: string | null;
  onOpen: (pk: string) => void;
  onNew: (() => void) | null;          // „Dodaj rekord” — tylko tabele bez geometrii z prawem dodawania
  onClose: () => void;
}) {
  const layer = config.layers[layerId];
  const win = useFloatingWindow("sophia.tableWindow");
  const hiddenKey = `sophia.table.${config.slug}.${layerId}`;
  const fields = useMemo(() => layer.fields.filter((f) => f.widget !== "Hidden" && f.name !== layer.primary_key), [layer]);
  const [hidden, setHidden] = useState<Set<string>>(() => loadHidden(hiddenKey));
  const [rows, setRows] = useState<GeoJSONFeature[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ field: string; desc: boolean } | null>(null);
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");                 // po odczekaniu (wyszukiwanie przy pisaniu)
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [colMenu, setColMenu] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [labels, setLabels] = useState<Labels>({});
  const seq = useRef(0);

  useEffect(() => { setHidden(loadHidden(hiddenKey)); setOffset(0); setSort(null); setQuery(""); setQ(""); }, [hiddenKey]);
  useEffect(() => { const t = setTimeout(() => { setQ(query); setOffset(0); }, 350); return () => clearTimeout(t); }, [query]);

  useEffect(() => {
    const my = ++seq.current;
    setLoading(true);
    api.tablePage(config.slug, layerId, config.crs, { offset, limit: PAGE, sort: sort?.field, desc: sort?.desc, q })
      .then((r) => { if (my === seq.current) { setRows(r.features); setTotal(r.total); setError(null); } })
      .catch((e) => my === seq.current && setError((e as Error).message))
      .finally(() => my === seq.current && setLoading(false));
  }, [config.slug, config.crs, layerId, offset, sort, q, reloadToken]);

  // Etykiety słowników (RelationReference / ValueRelation) — raz na pole
  useEffect(() => {
    let cancelled = false;
    for (const f of fields.filter((x) => x.widget === "RelationReference" || x.widget === "ValueRelation")) {
      api.fieldOptions(config.slug, layerId, f.name)
        .then((r) => !cancelled && setLabels((l) => ({ ...l, [f.name]: new Map(r.options.map((o) => [o.value, o.label])) })))
        .catch(() => { /* zostają surowe wartości */ });
    }
    return () => { cancelled = true; };
  }, [config.slug, layerId, fields]);

  const shown = fields.filter((f) => !hidden.has(f.name));
  const toggleCol = (name: string) => {
    const next = new Set(hidden);
    if (next.has(name)) next.delete(name); else next.add(name);
    setHidden(next);
    saveHidden(hiddenKey, next);
  };
  const clickHeader = (name: string) => {
    setOffset(0);
    setSort((s) => (s?.field !== name ? { field: name, desc: false } : !s.desc ? { field: name, desc: true } : null));
  };
  const arrow = (name: string) => (sort?.field === name ? (sort.desc ? " ▼" : " ▲") : "");
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const page = Math.floor(offset / PAGE) + 1;

  return (
    <aside ref={win.ref} style={win.style} className={`feature-window table-window${collapsed ? " collapsed" : ""}`}
      role="dialog" aria-label={`Tabela atrybutów: ${layer.name}`}>
      <header className="fw-head" {...win.handle} title="Przeciągnij, aby przesunąć · dwuklik: na środek">
        <div className="fw-title">
          <div className="muted">Tabela atrybutów</div>
          <strong>{layer.name} <span className="muted">({total}{loading ? "…" : ""})</span></strong>
        </div>
        <button className="icon fw-collapse" onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Rozwiń" : "Zwiń"} aria-label={collapsed ? "Rozwiń" : "Zwiń"}>{collapsed ? "▢" : "▁"}</button>
        <button className="icon" onClick={onClose} title="Zamknij" aria-label="Zamknij">✕</button>
      </header>

      <div className="table-tools">
        <input type="search" placeholder="Szukaj we wszystkich kolumnach…" value={query}
          onChange={(e) => setQuery(e.target.value)} aria-label="Szukaj" />
        <div className="col-menu-wrap">
          <button onClick={() => setColMenu((o) => !o)} aria-expanded={colMenu} title="Pokaż / ukryj kolumny">
            Kolumny{hidden.size ? ` (${fields.length - hidden.size}/${fields.length})` : ""} ▾
          </button>
          {colMenu && (
            <div className="col-menu" role="menu">
              {fields.map((f) => (
                <label key={f.name} className="check">
                  <input type="checkbox" checked={!hidden.has(f.name)} onChange={() => toggleCol(f.name)} /> {f.alias ?? f.name}
                </label>
              ))}
              {hidden.size > 0 && <button className="link" onClick={() => { setHidden(new Set()); saveHidden(hiddenKey, new Set()); }}>pokaż wszystkie</button>}
            </div>
          )}
        </div>
        {onNew && <button className="primary" onClick={onNew}>+ Dodaj rekord</button>}
      </div>
      {error && <div className="error">{error}</div>}

      <div className="table-scroll" onClick={() => colMenu && setColMenu(false)}>
        <table className="attr-table">
          <thead>
            <tr>
              <th className="pk" onClick={() => layer.primary_key && clickHeader(layer.primary_key)} title="Klucz — sortuj">
                #{layer.primary_key ? arrow(layer.primary_key) : ""}
              </th>
              {shown.map((f) => (
                <th key={f.name} onClick={() => clickHeader(f.name)} title={`${f.name} — kliknij, aby sortować`}>
                  {f.alias ?? f.name}{arrow(f.name)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={selectedId === String(r.id) ? "active" : ""} onClick={() => onOpen(String(r.id))}
                title={layer.geometry_type ? "Otwórz i pokaż na mapie" : "Otwórz rekord"}>
                <td className="pk">{r.id}</td>
                {shown.map((f) => {
                  const text = cellText(f, r.properties[f.name], labels);
                  return <td key={f.name} title={text.length > 40 ? text : undefined}>{text}</td>;
                })}
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr><td colSpan={shown.length + 1} className="muted">{q ? "Brak rekordów pasujących do wyszukiwania." : "Brak rekordów."}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <footer className="table-pager">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} aria-label="Poprzednia strona">‹</button>
        <span className="muted">
          {total ? `${offset + 1}–${Math.min(offset + PAGE, total)} z ${total}` : "0"} · strona {page}/{pages}
        </span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} aria-label="Następna strona">›</button>
      </footer>
    </aside>
  );
}
