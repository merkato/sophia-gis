import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from "react";
import { api } from "../api";
import type { FieldDef, GeoJSONFeature, ProjectConfig, RelatedGroup } from "../types";
import { FieldInput } from "./FieldInput";
import { useFloatingWindow } from "./FloatingWindow";
import { DocumentList, fileFieldOf } from "./Files";
import { PhotoGallery, photoFieldOf } from "./Photos";
import { featureActions, usePluginsVersion } from "../plugins";

interface Props {
  config: ProjectConfig;
  layerId: string;
  feature: GeoJSONFeature | null;          // null id => nowy obiekt (po narysowaniu)
  isNew: boolean;
  cutFrom?: string | null;                 // pierścień wypełniony: zapis wycina dziurę w tym obiekcie
  onSaved: (f: GeoJSONFeature) => void;
  onDeleted: () => void;
  onClose: () => void;
  onOpenRelated: (layerId: string, pk: string) => void;
  onNewRelated?: (layerId: string, props: Record<string, unknown>) => void;   // nowy rekord podrzędny (klucz rodzica wypełniony)
}

type Tab = "attrs" | "photos" | "docs" | "reports";

/** Dla App: czy formularz ma niezapisane zmiany i zapis „z zewnątrz” (okno zapisz/odrzuć/anuluj). */
export interface FeaturePanelHandle {
  isDirty: () => boolean;
  save: () => Promise<boolean>;
}

/** Porównanie wartości pola niezależnie od typu z inputa (liczba vs tekst, null vs ""). */
const norm = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export const FeaturePanel = forwardRef<FeaturePanelHandle, Props>(function FeaturePanel(
  { config, layerId, feature, isNew, cutFrom, onSaved, onDeleted, onClose, onOpenRelated, onNewRelated }, ref) {
  const layer = config.layers[layerId];
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [tab, setTab] = useState<Tab>("attrs");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [related, setRelated] = useState<RelatedGroup[]>([]);
  const pk = isNew ? null : feature?.id ?? null;
  const canEdit = isNew ? layer.perms.insert : layer.perms.update;
  const reports = config.reports.filter((r) => r.layer_id === layerId);
  const win = useFloatingWindow("sophia.featureWindow");
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setValues({ ...(feature?.properties ?? {}) });
    setError(null);
    if (isNew) setTab("attrs");
  }, [feature, isNew]);

  const loadRelated = useCallback(() => {
    if (!pk || !config.relations.some((r) => r.parent_layer === layerId || r.child_layer === layerId)) return;
    api.related(config.slug, layerId, pk, config.crs).then(setRelated).catch(() => setRelated([]));
  }, [pk, layerId, config]);

  useEffect(() => {
    if (!pk) { setRelated([]); return; }
    loadRelated();
  }, [pk, loadRelated]);

  // Wariant B zdjęć: tabela dzieci z polem „Załącznik” (obraz) -> galeria zamiast listy powiązanych
  // Wariant B dokumentów: tabela dzieci z polem „Załącznik” na pliki -> lista w zakładce „Dokumenty”
  // — tylko tabela załączników (poza kluczami i załącznikiem najwyżej 3 widoczne pola, np. opis, data, autor).
  // Rekord z wieloma polami i jednym zdjęciem (np. lustracja z fotografią) zostaje zwykłym rekordem powiązanym.
  const photoGroups = related.filter((g) => attachmentTable(config, g) && photoFieldOf(config.layers[g.layer_id]));
  const docGroups = related.filter((g) => attachmentTable(config, g) && fileFieldOf(config.layers[g.layer_id]));
  const otherGroups = related.filter((g) => !photoGroups.includes(g) && !docGroups.includes(g));
  const photoCount = photoGroups.reduce((n, g) => n + g.features.length, 0);
  const docCount = docGroups.reduce((n, g) => n + g.features.length, 0);
  useEffect(() => {
    if (!related.length) return;
    if ((tab === "photos" && !photoGroups.length) || (tab === "docs" && !docGroups.length)) setTab("attrs");
  }, [tab, related.length, otherGroups.length, photoGroups.length, docGroups.length]);

  // akcje wtyczek dla obiektu (np. dokument decyzji przy konturze) — po załadowaniu wtyczek
  usePluginsVersion();
  const pluginActions = !isNew && layer.source_table && pk !== null
    ? featureActions({ table: layer.source_table, pk: String(pk), layerId, project: config.slug, properties: feature?.properties ?? {} })
    : [];
  const visibleFields = layer.fields.filter((f) => f.widget !== "Hidden" && f.name !== layer.primary_key);

  const editableFields = visibleFields.filter((f) => f.editable);

  // nowy obiekt z narysowaną geometrią to też praca do stracenia
  const isDirty = () => canEdit && (
    (isNew && !!feature?.geometry)
    || editableFields.some((f) => norm(values[f.name]) !== norm(feature?.properties[f.name])));

  const save = async (): Promise<boolean> => {
    const missing = visibleFields.filter((f) => f.not_null && f.editable && (values[f.name] ?? "") === "");
    if (missing.length) {
      setTab("attrs");
      setError(`Wymagane pola: ${missing.map((f) => f.alias ?? f.name).join(", ")}`);
      return false;
    }
    // nowy obiekt: pola wypełnione z góry, których nie ma w formularzu (ukryte, klucz naturalny — np. identyfikator
    // działki ustawiony przez wtyczkę, klucz obcy rekordu powiązanego), idą do zapisu razem z polami formularza
    const preset = isNew ? Object.fromEntries(Object.entries(feature?.properties ?? {}).filter(([k, v]) =>
      v != null && v !== "" && (k === layer.primary_key || layer.fields.some((f) => f.name === k && f.editable)))) : {};
    const props = {
      ...preset,
      ...Object.fromEntries(editableFields.map((f) => [f.name, values[f.name] ?? null])),
    };
    setBusy(true);
    setError(null);
    try {
      const saved = isNew
        ? await api.createFeature(config.slug, layerId, { type: "Feature", geometry: feature?.geometry ?? null, properties: props }, config.crs, cutFrom)
        : await api.updateFeature(config.slug, layerId, pk!, { properties: props }, config.crs);
      onSaved(saved);
      return true;
    } catch (e) {
      setTab("attrs");
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  // isDirty/save zależą od bieżących wartości — uchwyt odświeżany przy każdym renderze
  useImperativeHandle(ref, () => ({ isDirty, save }));

  const remove = async () => {
    if (!pk || !confirm("Usunąć obiekt? Tej operacji nie można cofnąć.")) return;
    try {
      await api.deleteFeature(config.slug, layerId, pk);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <aside ref={win.ref} style={win.style} className={`feature-window${collapsed ? " collapsed" : ""}`}
      role="dialog" aria-label={`${layer.name}: ${isNew ? "nowy obiekt" : `#${pk}`}`}>
      <header className="fw-head" {...win.handle} title="Przeciągnij, aby przesunąć · dwuklik: na środek">
        <div className="fw-title">
          <div className="muted">{layer.name}</div>
          <strong>{isNew ? "Nowy obiekt" : `#${pk}`}</strong>
        </div>
        <button className="icon fw-collapse" onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Rozwiń" : "Zwiń"} aria-label={collapsed ? "Rozwiń" : "Zwiń"}>{collapsed ? "▢" : "▁"}</button>
        <button className="icon" onClick={onClose} title="Zamknij" aria-label="Zamknij">✕</button>
      </header>

      <div className="fw-body">
      {!isNew && pluginActions.length > 0 && (
        <div className="feature-actions">
          {pluginActions.map((a, i) => (
            <button key={i} className="link" title={a.title} onClick={a.run}>{a.label}</button>
          ))}
        </div>
      )}

      {!isNew && (
        <nav className="tabs">
          <button className={tab === "attrs" ? "active" : ""} onClick={() => setTab("attrs")}>Atrybuty</button>
          {photoGroups.length > 0 && <button className={tab === "photos" ? "active" : ""} onClick={() => setTab("photos")}>Zdjęcia ({photoCount})</button>}
          {docGroups.length > 0 && <button className={tab === "docs" ? "active" : ""} onClick={() => setTab("docs")}>Dokumenty ({docCount})</button>}
          {reports.length > 0 && <button className={tab === "reports" ? "active" : ""} onClick={() => setTab("reports")}>Raporty</button>}
        </nav>
      )}

      {error && <div className="error">{error}</div>}

      {tab === "attrs" && (
        <div className="form">
          {formRows(visibleFields).map((row) => (
            <div key={row[0][0].name} className="field-row">
            {row.map(([f, span]) => (
            <label key={f.name} className="field" style={{ flex: `${span} 1 0` }}>
              <span>{f.alias ?? f.name}{f.not_null && f.editable ? " *" : ""}</span>
              <FieldInput field={f} value={values[f.name]} readOnly={!canEdit}
                source={{ slug: config.slug, layerId, version: config.version, pk: pk === null ? null : String(pk), crs: config.crs,
                  canPhotos: config.rights?.photos ?? false, canFiles: config.rights?.files ?? false }}
                saved={isNew ? undefined : feature?.properties[f.name]}
                onChange={(v) => setValues((s) => ({ ...s, [f.name]: v }))} />
            </label>
            ))}
            </div>
          ))}
          {canEdit && (
            <div className="actions">
              <button className="primary" disabled={busy} onClick={save}>{busy ? "Zapisywanie…" : "Zapisz"}</button>
              {!isNew && layer.perms.delete && <button className="danger" onClick={remove}>Usuń</button>}
            </div>
          )}
          {!isNew && otherGroups.map((g) => (
            <RelatedTable key={g.relation} config={config} group={g} parentValues={values}
              onOpen={(id) => onOpenRelated(g.layer_id, id)}
              onNew={g.direction === "child" && onNewRelated && config.layers[g.layer_id]?.perms.insert
                ? () => onNewRelated(g.layer_id, Object.fromEntries(g.pairs.map(([pf, cf]) => [cf, values[pf]])))
                : undefined} />
          ))}
        </div>
      )}

      {tab === "photos" && pk && photoGroups.map((g) => (
        <PhotoGallery key={g.relation} config={config} group={g} parentLayerId={layerId} parentPk={String(pk)}
          onChanged={loadRelated} onOpenRecord={onOpenRelated} />
      ))}

      {tab === "docs" && pk && docGroups.map((g) => (
        <DocumentList key={g.relation} config={config} group={g} parentLayerId={layerId} parentPk={String(pk)}
          onChanged={loadRelated} onOpenRecord={onOpenRelated} />
      ))}

      {tab === "reports" && pk && (
        <section className="reports">
          {reports.map((r) => (
            <a key={r.layout} className="button" target="_blank" rel="noreferrer"
              href={api.reportUrl(config.slug, r.layout, { pk })}>🖨 {r.title}</a>
          ))}
        </section>
      )}
      </div>
    </aside>
  );
});

/** Wartość pola do tabelki rekordów powiązanych: etykieta z mapy wartości, data bez godziny. */
function shown(field: { widget: string; widget_config: Record<string, unknown> | null }, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const cfg = (field.widget_config ?? {}) as Record<string, unknown>;
  if (field.widget === "ValueMap") {
    const raw = cfg.map;
    const entries: [string, string][] = Array.isArray(raw)
      ? raw.flatMap((o) => Object.entries(o as Record<string, string>))
      : Object.entries((raw ?? {}) as Record<string, string>);
    const hit = entries.find(([, val]) => String(val) === String(v));
    if (hit) return hit[0];
  }
  if (field.widget === "CheckBox") return v === true || v === "true" || v === 1 ? "tak" : "nie";
  if (field.widget === "DateTime" && typeof v === "string") return v.slice(0, 10).split("-").reverse().join(".");
  return String(v);
}

/** Rekordy powiązane w formularzu (okno w oknie): kilka kolumn, kliknięcie otwiera rekord, „+ Dodaj” — nowy podrzędny. */
function RelatedTable({ config, group, parentValues, onOpen, onNew }: {
  config: ProjectConfig; group: RelatedGroup; parentValues: Record<string, unknown>;
  onOpen: (id: string) => void; onNew?: () => void;
}) {
  const lyr = config.layers[group.layer_id];
  if (!lyr) return null;
  void parentValues;
  const keys = new Set([lyr.primary_key, ...group.pairs.map(([p, c]) => (group.direction === "child" ? c : p))]);
  const cols = lyr.fields.filter((f) => f.widget !== "Hidden" && f.widget !== "ExternalResource" && !keys.has(f.name)).slice(0, 5);
  return (
    <section className="related related-inline">
      <h4>{group.name || lyr.name} <span className="muted">({group.features.length})</span>
        {onNew && <button className="link" style={{ marginLeft: 8 }} onClick={onNew}>+ Dodaj</button>}</h4>
      {group.features.length > 0 && (
        <div className="related-table">
          <table className="grid">
            <thead><tr>{cols.map((c) => <th key={c.name}>{c.alias ?? c.name}</th>)}</tr></thead>
            <tbody>
              {group.features.map((f) => (
                <tr key={f.id} onClick={() => onOpen(String(f.id))} style={{ cursor: "pointer" }} title="Otwórz rekord">
                  {cols.map((c) => <td key={c.name}>{shown(c, f.properties[c.name])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Szerokość pola w formularzu (z 6 kolumn): krótkie pola (liczby, daty, kody) obok siebie, długie teksty na całą szerokość.
 *  Typ i typowa długość wartości pochodzą z bazy (varchar(n) albo średnia z pg_stats dla text). */
export function fieldSpan(f: FieldDef): number {
  const t = (f.type ?? "").toLowerCase();
  const cfg = (f.widget_config ?? {}) as Record<string, unknown>;
  if (f.widget === "ExternalResource" || (f.widget === "TextEdit" && cfg.IsMultiline) || cfg.AllowMulti
      || /json|\[\]|geometry|geography/.test(t)) return 6;
  let span = 6;
  if (f.widget === "CheckBox" || /^(smallint|integer|bigint|boolean|date|timestamp)/.test(t)) span = 2;
  else if (["DateTime", "ValueMap", "ValueRelation", "RelationReference", "Range"].includes(f.widget)
      || /^(numeric|decimal|real|double|time|uuid)/.test(t)) span = 3;
  else if (/char|text/.test(t)) {
    const declared = /char[^(]*\((\d+)\)/.exec(t);
    const len = declared ? Number(declared[1]) : f.avg_width ?? null;
    if (len !== null) span = len <= 10 ? 2 : len <= 32 ? 3 : 6;
  }
  // długa etykieta nie mieści się w wąskiej kolumnie
  if (span === 2 && (f.alias ?? f.name).length > 22) span = 3;
  return span;
}

/** Czy tabela dzieci relacji jest tabelą załączników (zdjęcia/dokumenty) — galeria zamiast tabelki rekordów. */
function attachmentTable(config: ProjectConfig, g: RelatedGroup): boolean {
  const lyr = config.layers[g.layer_id];
  if (g.direction !== "child" || !lyr) return false;
  const keys = new Set([lyr.primary_key, ...g.pairs.map(([, c]) => c)]);
  const rest = lyr.fields.filter((f) => f.widget !== "Hidden" && f.widget !== "ExternalResource" && !keys.has(f.name));
  return rest.length <= 3;
}

/** Kolejne pola łączone w wiersze do 6 kolumn (kolejność z projektu zostaje); wiersz rozciąga się na całą szerokość. */
export function formRows(fields: FieldDef[]): [FieldDef, number][][] {
  const rows: [FieldDef, number][][] = [];
  let cur: [FieldDef, number][] = [];
  let sum = 0;
  for (const f of fields) {
    const s = fieldSpan(f);
    if (cur.length && sum + s > 6) { rows.push(cur); cur = []; sum = 0; }
    cur.push([f, s]);
    sum += s;
  }
  if (cur.length) rows.push(cur);
  return rows;
}
