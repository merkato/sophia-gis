import { useEffect, useState } from "react";
import { api } from "../api";
import type { Attachment, GeoJSONFeature, ProjectConfig, RelatedGroup } from "../types";
import { FieldInput } from "./FieldInput";

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

type Tab = "attrs" | "related" | "docs" | "reports";

export function FeaturePanel({ config, layerId, feature, isNew, onSaved, onDeleted, onClose, onOpenRelated }: Props) {
  const layer = config.layers[layerId];
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [tab, setTab] = useState<Tab>("attrs");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [related, setRelated] = useState<RelatedGroup[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const pk = isNew ? null : feature?.id ?? null;
  const canEdit = isNew ? layer.perms.insert : layer.perms.update;
  const reports = config.reports.filter((r) => r.layer_id === layerId);

  useEffect(() => {
    setValues({ ...(feature?.properties ?? {}) });
    setError(null);
    if (isNew) setTab("attrs");
  }, [feature, isNew]);

  useEffect(() => {
    if (!pk) { setRelated([]); setAttachments([]); return; }
    if (config.relations.some((r) => r.parent_layer === layerId || r.child_layer === layerId)) {
      api.related(config.slug, layerId, pk, config.crs).then(setRelated).catch(() => setRelated([]));
    }
    if (layer.attachments) {
      api.attachments(config.slug, layerId, pk).then(setAttachments).catch(() => setAttachments([]));
    }
  }, [pk, layerId, config, layer.attachments]);

  const visibleFields = layer.fields.filter((f) => f.widget !== "Hidden" && f.name !== layer.primary_key);

  const save = async () => {
    const missing = visibleFields.filter((f) => f.not_null && f.editable && (values[f.name] ?? "") === "");
    if (missing.length) {
      setError(`Wymagane pola: ${missing.map((f) => f.alias ?? f.name).join(", ")}`);
      return;
    }
    const props = Object.fromEntries(
      visibleFields.filter((f) => f.editable).map((f) => [f.name, values[f.name] ?? null]));
    setBusy(true);
    setError(null);
    try {
      const saved = isNew
        ? await api.createFeature(config.slug, layerId, { type: "Feature", geometry: feature?.geometry ?? null, properties: props }, config.crs)
        : await api.updateFeature(config.slug, layerId, pk!, { properties: props }, config.crs);
      onSaved(saved);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!pk || !confirm("Usunąć obiekt? Tej operacji nie można cofnąć.")) return;
    try {
      await api.deleteFeature(config.slug, layerId, pk);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const upload = async (file: File) => {
    try {
      await api.uploadAttachment(config.slug, layerId, pk!, file);
      setAttachments(await api.attachments(config.slug, layerId, pk!));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <aside className="feature-panel">
      <header>
        <div>
          <div className="muted">{layer.name}</div>
          <strong>{isNew ? "Nowy obiekt" : `#${pk}`}</strong>
        </div>
        <button className="icon" onClick={onClose} aria-label="Zamknij">✕</button>
      </header>

      {!isNew && (
        <nav className="tabs">
          <button className={tab === "attrs" ? "active" : ""} onClick={() => setTab("attrs")}>Atrybuty</button>
          {related.length > 0 && <button className={tab === "related" ? "active" : ""} onClick={() => setTab("related")}>Powiązane</button>}
          {layer.attachments && <button className={tab === "docs" ? "active" : ""} onClick={() => setTab("docs")}>Dokumenty ({attachments.length})</button>}
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
                source={{ slug: config.slug, layerId, version: config.version }}
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

      {tab === "related" && related.map((g) => (
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

      {tab === "docs" && pk && (
        <section className="docs">
          <ul>
            {attachments.map((a) => (
              <li key={a.id}>
                <a href={api.attachmentUrl(config.slug, layerId, pk, a.id)} target="_blank" rel="noreferrer">📄 {a.file_name}</a>
                <span className="muted"> {(a.size_bytes / 1024 / 1024).toFixed(1)} MB · {a.uploaded_by ?? "?"}</span>
                {layer.perms.update && (
                  <button className="icon" title="Usuń dokument" onClick={async () => {
                    if (!confirm(`Usunąć ${a.file_name}?`)) return;
                    await api.deleteAttachment(config.slug, layerId, pk, a.id);
                    setAttachments(await api.attachments(config.slug, layerId, pk));
                  }}>✕</button>
                )}
              </li>
            ))}
          </ul>
          {layer.perms.update && (
            <label className="upload">
              Dodaj PDF
              <input type="file" accept="application/pdf" hidden
                onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
            </label>
          )}
        </section>
      )}

      {tab === "reports" && pk && (
        <section className="reports">
          {reports.map((r) => (
            <a key={r.layout} className="button" target="_blank" rel="noreferrer"
              href={api.reportUrl(config.slug, r.layout, { pk })}>🖨 {r.title}</a>
          ))}
        </section>
      )}
    </aside>
  );
}
