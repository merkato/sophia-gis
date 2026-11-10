import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { GeoJSONFeature, LayerInfo, ProjectConfig } from "../types";

interface Props {
  config: ProjectConfig;
  layer: LayerInfo;
  reloadToken: number;
  selectedId: string | null;
  onOpen: (pk: string) => void;
  onNew: () => void;
}

/**
 * Pole etykiety rekordu — ta sama reguła co w API (fields.label_field): nazwa pola z wyrażenia
 * wyświetlanego QGIS (np. COALESCE("nazwa", '<NULL>') -> nazwa), inaczej pierwsze pole tekstowe,
 * a gdy typy nieznane (QGIS ich nie zapisuje w projekcie) — pierwsze pole poza kluczem.
 */
function labelFor(layer: LayerInfo): (f: GeoJSONFeature) => string {
  const names = layer.fields.map((f) => f.name);
  const expr = layer.display_expression?.trim() ?? "";
  const quoted = [...expr.matchAll(/"((?:[^"]|"")+)"/g)].map((m) => m[1].replace(/""/g, '"'));
  const byExpr = names.includes(expr) ? expr : quoted.find((n) => names.includes(n));
  const others = layer.fields.filter((f) => f.name !== layer.primary_key);
  const field = byExpr ?? others.find((f) => /char|text|string/i.test(f.type ?? ""))?.name ?? others[0]?.name;
  return (f) => {
    const v = field ? f.properties[field] : null;
    return v !== null && v !== undefined && String(v).trim() ? String(v) : `#${f.id}`;
  };
}

/**
 * Edycja tabeli bez geometrii (np. słownik, tabela nadrzędna relacji): lista rekordów zamiast
 * zaznaczania na mapie. Kliknięcie otwiera ten sam formularz co obiekt z mapy.
 */
export function RecordList({ config, layer, reloadToken, selectedId, onOpen, onNew }: Props) {
  const [rows, setRows] = useState<GeoJSONFeature[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const label = useMemo(() => labelFor(layer), [layer]);

  useEffect(() => {
    let cancelled = false;
    api.features(config.slug, layer.id, null, config.crs)
      .then((fc) => { if (!cancelled) { setRows(fc.features); setTruncated(fc.truncated); setError(null); } })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => { cancelled = true; };
  }, [config.slug, config.crs, layer.id, reloadToken]);

  const q = filter.trim().toLowerCase();
  const shown = rows
    .map((f) => ({ f, text: label(f) }))
    .filter(({ f, text }) => !q || text.toLowerCase().includes(q)
      || Object.values(f.properties).some((v) => v !== null && String(v).toLowerCase().includes(q)))
    .sort((a, b) => a.text.localeCompare(b.text, "pl", { numeric: true }));

  return (
    <div className="records">
      <div className="toolgroup">
        {layer.perms.insert && <button className="primary" onClick={onNew}>+ Nowy rekord</button>}
        <span className="muted">{rows.length}{truncated ? "+" : ""} rekordów · tabela bez geometrii</span>
      </div>
      {rows.length > 8 && <input placeholder="Szukaj…" value={filter} onChange={(e) => setFilter(e.target.value)} />}
      {error && <div className="error">{error}</div>}
      <ul>
        {shown.map(({ f, text }) => (
          <li key={f.id}>
            <button className={`link-row${selectedId === String(f.id) ? " active" : ""}`} onClick={() => onOpen(String(f.id))}>{text}</button>
          </li>
        ))}
        {!rows.length && !error && <li className="muted">Brak rekordów.</li>}
      </ul>
    </div>
  );
}
