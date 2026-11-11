import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from "react";
import { api } from "../api";
import type { GeoJSONFeature, ProjectConfig, RelatedGroup } from "../types";
import { FieldInput } from "./FieldInput";
import { useFloatingWindow } from "./FloatingWindow";
import { DocumentList, fileFieldOf } from "./Files";
import { PhotoGallery, photoFieldOf } from "./Photos";

interface Props {
  config: ProjectConfig;
  layerId: string;
  feature: GeoJSONFeature | null;          // null id => nowy obiekt (po narysowaniu)
  isNew: boolean;
  onSaved: (f: GeoJSONFeature) => void;
  onDeleted: () => void;
  onClose: () => void;
  onOpenRelated: (layerId: string, pk: string) => void;
}

type Tab = "attrs" | "photos" | "related" | "docs" | "reports";

/** Dla App: czy formularz ma niezapisane zmiany i zapis „z zewnątrz” (okno zapisz/odrzuć/anuluj). */
export interface FeaturePanelHandle {
  isDirty: () => boolean;
  save: () => Promise<boolean>;
}

/** Porównanie wartości pola niezależnie od typu z inputa (liczba vs tekst, null vs ""). */
const norm = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export const FeaturePanel = forwardRef<FeaturePanelHandle, Props>(function FeaturePanel(
  { config, layerId, feature, isNew, onSaved, onDeleted, onClose, onOpenRelated }, ref) {
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
  const photoGroups = related.filter((g) => g.direction === "child" && photoFieldOf(config.layers[g.layer_id]));
  const docGroups = related.filter((g) => g.direction === "child" && fileFieldOf(config.layers[g.layer_id]));
  const otherGroups = related.filter((g) => !photoGroups.includes(g) && !docGroups.includes(g));
  const photoCount = photoGroups.reduce((n, g) => n + g.features.length, 0);
  const docCount = docGroups.reduce((n, g) => n + g.features.length, 0);
  useEffect(() => {
    if (!related.length) return;
    if ((tab === "related" && !otherGroups.length) || (tab === "photos" && !photoGroups.length)
      || (tab === "docs" && !docGroups.length)) setTab("attrs");
  }, [tab, related.length, otherGroups.length, photoGroups.length, docGroups.length]);

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
    const props = Object.fromEntries(
      editableFields.map((f) => [f.name, values[f.name] ?? null]));
    setBusy(true);
    setError(null);
    try {
      const saved = isNew
        ? await api.createFeature(config.slug, layerId, { type: "Feature", geometry: feature?.geometry ?? null, properties: props }, config.crs)
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

      {!isNew && (
        <nav className="tabs">
          <button className={tab === "attrs" ? "active" : ""} onClick={() => setTab("attrs")}>Atrybuty</button>
          {photoGroups.length > 0 && <button className={tab === "photos" ? "active" : ""} onClick={() => setTab("photos")}>Zdjęcia ({photoCount})</button>}
          {otherGroups.length > 0 && <button className={tab === "related" ? "active" : ""} onClick={() => setTab("related")}>Powiązane</button>}
          {docGroups.length > 0 && <button className={tab === "docs" ? "active" : ""} onClick={() => setTab("docs")}>Dokumenty ({docCount})</button>}
          {reports.length > 0 && <button className={tab === "reports" ? "active" : ""} onClick={() => setTab("reports")}>Raporty</button>}
        </nav>
      )}

      {error && <div className="error">{error}</div>}

      {tab === "attrs" && (
        <div className="form">
          {visibleFields.map((f) => (
            <label key={f.name} className="field">
              <span>{f.alias ?? f.name}{f.not_null && f.editable ? " *" : ""}</span>
              <FieldInput field={f} value={values[f.name]} readOnly={!canEdit}
                source={{ slug: config.slug, layerId, version: config.version, pk: pk === null ? null : String(pk), crs: config.crs,
                  canPhotos: config.rights?.photos ?? false, canFiles: config.rights?.files ?? false }}
                saved={isNew ? undefined : feature?.properties[f.name]}
                onChange={(v) => setValues((s) => ({ ...s, [f.name]: v }))} />
            </label>
          ))}
          {canEdit && (
            <div className="actions">
              <button className="primary" disabled={busy} onClick={save}>{busy ? "Zapisywanie…" : "Zapisz"}</button>
              {!isNew && layer.perms.delete && <button className="danger" onClick={remove}>Usuń</button>}
            </div>
          )}
        </div>
      )}

      {tab === "photos" && pk && photoGroups.map((g) => (
        <PhotoGallery key={g.relation} config={config} group={g} parentLayerId={layerId} parentPk={String(pk)}
          onChanged={loadRelated} onOpenRecord={onOpenRelated} />
      ))}

      {tab === "related" && otherGroups.map((g) => (
        <section key={g.relation} className="related">
          <h4>{g.name} <span className="muted">({g.features.length})</span></h4>
          <ul>
            {g.features.map((f) => (
              <li key={f.id}>
                <button className="link" onClick={() => onOpenRelated(g.layer_id, f.id)}>
                  {config.layers[g.layer_id]?.name} #{f.id}
                </button>
              </li>
            ))}
          </ul>
        </section>
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
