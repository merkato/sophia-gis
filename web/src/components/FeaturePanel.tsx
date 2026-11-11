import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "../api";
import type { Attachment, GeoJSONFeature, ProjectConfig, RelatedGroup } from "../types";
import { FieldInput } from "./FieldInput";
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

interface Pos { x: number; y: number }

const POS_KEY = "sophia.featureWindow";
const MOBILE = "(max-width: 800px)";
const KEEP_VISIBLE = 80;   // ile px okna musi zostać nad mapą przy przesuwaniu

function loadPos(): Pos | null {
  try {
    const v = JSON.parse(localStorage.getItem(POS_KEY) ?? "null");
    return v && typeof v.x === "number" && typeof v.y === "number" ? v : null;
  } catch { return null; }
}

function savePos(p: Pos | null) {
  try { if (p) localStorage.setItem(POS_KEY, JSON.stringify(p)); else localStorage.removeItem(POS_KEY); } catch { /* brak storage */ }
}

/** Trzyma okno w obrębie mapy: nagłówek zawsze widoczny, z boku może wystawać. */
function clamp(p: Pos, el: HTMLElement): Pos {
  const parent = el.offsetParent as HTMLElement | null;
  if (!parent) return p;
  const maxX = parent.clientWidth - KEEP_VISIBLE;
  const minX = KEEP_VISIBLE - el.offsetWidth;
  const maxY = Math.max(0, parent.clientHeight - 44);
  return { x: Math.round(Math.min(Math.max(p.x, minX), maxX)), y: Math.round(Math.min(Math.max(p.y, 0), maxY)) };
}

/**
 * Pływające okno nad mapą: na starcie wyśrodkowane, przesuwane za nagłówek (pozycja
 * zapamiętana w przeglądarce, dwuklik w nagłówek wraca na środek), rozmiar zmieniany
 * w prawym dolnym rogu. Mapa pod spodem zostaje klikalna. Na telefonie — pełny ekran.
 */
function useFloatingWindow() {
  const ref = useRef<HTMLElement | null>(null);
  const [pos, setPos] = useState<Pos | null>(loadPos);
  const drag = useRef<{ dx: number; dy: number } | null>(null);

  // zapamiętana pozycja mogła zostać z większego okna przeglądarki
  useLayoutEffect(() => {
    const fit = () => setPos((p) => (p && ref.current ? clamp(p, ref.current) : p));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    const el = ref.current;
    if (!el || e.button !== 0 || (e.target as HTMLElement).closest("button") || matchMedia(MOBILE).matches) return;
    // z prostokątów, nie offsetLeft — ten pomija transform wyśrodkowania
    const r = el.getBoundingClientRect();
    const pr = (el.offsetParent ?? document.body).getBoundingClientRect();
    drag.current = { dx: e.clientX - (r.left - pr.left), dy: e.clientY - (r.top - pr.top) };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }, []);

  const onPointerMove = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    const el = ref.current;
    if (!el || !drag.current) return;
    setPos(clamp({ x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }, el));
  }, []);

  const onPointerUp = useCallback(() => {
    if (!drag.current) return;
    drag.current = null;
    setPos((p) => { savePos(p); return p; });
  }, []);

  const center = useCallback(() => { setPos(null); savePos(null); }, []);

  return {
    ref,
    style: pos ? { left: pos.x, top: pos.y, transform: "none" } : undefined,
    handle: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, onDoubleClick: center },
  };
}

export const FeaturePanel = forwardRef<FeaturePanelHandle, Props>(function FeaturePanel(
  { config, layerId, feature, isNew, onSaved, onDeleted, onClose, onOpenRelated }, ref) {
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
  const win = useFloatingWindow();
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
    if (!pk) { setRelated([]); setAttachments([]); return; }
    loadRelated();
    if (layer.attachments) {
      api.attachments(config.slug, layerId, pk).then(setAttachments).catch(() => setAttachments([]));
    }
  }, [pk, layerId, config, layer.attachments, loadRelated]);

  // Wariant B zdjęć: tabela dzieci z polem „Załącznik” (obraz) -> galeria zamiast listy powiązanych
  const photoGroups = related.filter((g) => g.direction === "child" && photoFieldOf(config.layers[g.layer_id]));
  const otherGroups = related.filter((g) => !photoGroups.includes(g));
  const photoCount = photoGroups.reduce((n, g) => n + g.features.length, 0);
  useEffect(() => {
    if ((tab === "related" && !otherGroups.length && related.length) || (tab === "photos" && !photoGroups.length && related.length)) setTab("attrs");
  }, [tab, related.length, otherGroups.length, photoGroups.length]);

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

  const upload = async (file: File) => {
    try {
      await api.uploadAttachment(config.slug, layerId, pk!, file);
      setAttachments(await api.attachments(config.slug, layerId, pk!));
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
                source={{ slug: config.slug, layerId, version: config.version, pk: pk === null ? null : String(pk), crs: config.crs }}
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
      </div>
    </aside>
  );
});
