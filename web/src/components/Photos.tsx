import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { FieldDef, GeoJSONFeature, LayerInfo, ProjectConfig, RelatedGroup } from "../types";

// Zdjęcia w polach z widżetem QGIS „Załącznik” (ExternalResource):
//   wariant A — pole w tabeli obiektu (PhotoField w formularzu),
//   wariant B — osobna tabela zdjęć powiązana relacją (PhotoGallery w zakładce „Zdjęcia”).
// Konfiguracja w QGIS: docs/user/zdjecia.md.

const IMAGE_EXT = /\.(jpe?g|png|gif|webp|heic|heif|tiff?|bmp)\b/i;

/** Ta sama reguła co w API (photos.is_photo_field): podgląd „Obraz” albo filtr plików graficznych. */
export function isPhotoField(f: FieldDef): boolean {
  if (f.widget !== "ExternalResource") return false;
  const cfg = f.widget_config ?? {};
  return String(cfg.DocumentViewer) === "1" || IMAGE_EXT.test(String(cfg.FileWidgetFilter ?? ""));
}

export function photoFieldOf(layer: LayerInfo | undefined): FieldDef | undefined {
  return layer?.fields.find(isPhotoField);
}

/** Telefon/tablet: osobny przycisk „Aparat” (capture) — na komputerze otwierałby i tak wybór pliku. */
const touch = typeof matchMedia !== "undefined" && matchMedia("(pointer: coarse)").matches;

// Podglądy zdjęć wysłanych w tej sesji, zanim obiekt zostanie zapisany (ścieżka -> blob URL)
const localPreviews = new Map<string, string>();

function PickButtons({ onFiles, multiple, busy }: { onFiles: (files: File[]) => void; multiple?: boolean; busy: boolean }) {
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    if (files.length) onFiles(files);
  };
  return (
    <>
      {touch && (
        <label className={`upload${busy ? " disabled" : ""}`} title="Zrób zdjęcie aparatem">
          📷 Aparat
          <input type="file" accept="image/*" capture="environment" hidden disabled={busy} onChange={pick} />
        </label>
      )}
      <label className={`upload${busy ? " disabled" : ""}`} title={multiple ? "Wybierz zdjęcia z galerii lub dysku" : "Wybierz zdjęcie z galerii lub dysku"}>
        🖼 {multiple ? "Dodaj zdjęcia" : touch ? "Galeria" : "Wybierz zdjęcie"}
        <input type="file" accept="image/*" multiple={multiple} hidden disabled={busy} onChange={pick} />
      </label>
    </>
  );
}

/** Wariant A: jedno zdjęcie w polu obiektu. Wartość pola = ścieżka względna zwrócona przez serwer. */
export function PhotoField({ field, value, saved, onChange, disabled, slug, layerId, pk, crs }: {
  field: FieldDef; value: unknown; saved: unknown; onChange: (v: unknown) => void; disabled: boolean;
  slug: string; layerId: string; pk: string | null; crs: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  const str = value === null || value === undefined ? "" : String(value);
  const isSaved = !!str && !!pk && str === String(saved ?? "");
  const thumb = localPreviews.get(str) ?? (isSaved ? api.fileUrl(slug, layerId, pk!, field.name, str, true) : null);
  const full = localPreviews.get(str) ?? (isSaved ? api.fileUrl(slug, layerId, pk!, field.name, str) : null);
  useEffect(() => setBroken(false), [str]);

  const upload = async ([file]: File[]) => {
    setBusy(true);
    setError(null);
    try {
      const meta = await api.uploadPhoto(slug, layerId, field.name, file, crs);
      localPreviews.set(meta.path, URL.createObjectURL(file));
      onChange(meta.path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="photo-field">
      {str && thumb && !broken ? (
        <a href={full!} target="_blank" rel="noreferrer" title="Otwórz w pełnym rozmiarze">
          <img src={thumb} alt={field.alias ?? field.name} onError={() => setBroken(true)} />
        </a>
      ) : str ? (
        <div className="muted photo-missing" title={str}>{broken ? "Brak pliku na serwerze: " : "Zdjęcie: "}{str.split("/").pop()}</div>
      ) : (
        <div className="muted">Brak zdjęcia</div>
      )}
      {!disabled && (
        <div className="toolgroup">
          <PickButtons onFiles={upload} busy={busy} />
          {str && <button type="button" className="danger" disabled={busy} onClick={() => onChange(null)}>Usuń zdjęcie</button>}
          {busy && <span className="muted">Wysyłanie…</span>}
        </div>
      )}
      {!disabled && str && !isSaved && !busy && <div className="muted">Zdjęcie zostanie przypisane po zapisaniu formularza.</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

const DATE_NAMES = ["data_wizytacji", "wizytacja", "data_zdjecia", "data", "dodano", "created_at", "date"];

/** Pole daty w tabeli zdjęć do grupowania galerii: pierwsze z widżetem Data/czas, inaczej po nazwie. */
export function dateFieldOf(layer: LayerInfo): FieldDef | undefined {
  return layer.fields.find((f) => f.widget === "DateTime")
    ?? DATE_NAMES.map((n) => layer.fields.find((f) => f.name.toLowerCase() === n && f.widget !== "Hidden")).find(Boolean);
}

/** Dzień (YYYY-MM-DD, czas lokalny) z wartości daty/znacznika czasu z bazy. */
export function dayOf(v: unknown): string | null {
  const s = v === null || v === undefined ? "" : String(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const d = new Date(s);
  if (!s || Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 1 zdjęcie, 2–4 zdjęcia, 5+ zdjęć (12–14 zdjęć). */
function photosLabel(n: number): string {
  const word = n === 1 ? "zdjęcie"
    : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "zdjęcia" : "zdjęć";
  return `${n} ${word}`;
}

/** Wariant B: wiele zdjęć w tabeli powiązanej relacją (rodzic = otwarty obiekt). */
export function PhotoGallery({ config, group, parentLayerId, parentPk, onChanged, onOpenRecord }: {
  config: ProjectConfig; group: RelatedGroup; parentLayerId: string; parentPk: string;
  onChanged: () => void; onOpenRecord: (layerId: string, pk: string) => void;
}) {
  const layer = config.layers[group.layer_id];
  const field = photoFieldOf(layer)!;
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const dateField = dateFieldOf(layer);
  // Grupy wg dnia (wizytacje), najnowsze na górze; kolejność items = kolejność w podglądzie
  const groups = useMemo(() => {
    const withPhoto = group.features.filter((f) => f.properties[field.name]);
    if (!dateField) return [{ day: null as string | null, items: withPhoto }];
    const key = (f: GeoJSONFeature) => String(f.properties[dateField.name] ?? "");
    const byDay = new Map<string | null, GeoJSONFeature[]>();
    for (const f of [...withPhoto].sort((a, b) => key(b).localeCompare(key(a)))) {
      const d = dayOf(f.properties[dateField.name]);
      byDay.set(d, [...(byDay.get(d) ?? []), f]);
    }
    return [...byDay.entries()]
      .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : b.localeCompare(a)))
      .map(([day, items]) => ({ day, items }));
  }, [group.features, field.name, dateField]);
  const items = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const withoutPhoto = group.features.length - items.length;
  const url = (f: GeoJSONFeature, thumb: boolean) =>
    api.fileUrl(config.slug, layer.id, String(f.id), field.name, f.properties[field.name], thumb);

  const upload = async (files: File[]) => {
    setError(null);
    const failed: string[] = [];
    for (const [i, file] of files.entries()) {
      setProgress(files.length > 1 ? `Wysyłanie ${i + 1}/${files.length}…` : "Wysyłanie…");
      try {
        await api.uploadPhoto(config.slug, layer.id, field.name, file, config.crs, { layerId: parentLayerId, pk: parentPk });
      } catch (e) {
        failed.push(`${file.name}: ${(e as Error).message}`);
      }
    }
    setProgress(null);
    if (failed.length) setError(failed.join("\n"));
    onChanged();
  };

  const remove = async (f: GeoJSONFeature) => {
    if (!confirm("Usunąć zdjęcie (rekord w tabeli zdjęć)?")) return;
    try {
      await api.deleteFeature(config.slug, layer.id, String(f.id));
      setOpen(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="gallery">
      <h4>{group.name} <span className="muted">({items.length})</span></h4>
      {layer.perms.insert && (
        <div className="toolgroup">
          <PickButtons onFiles={upload} multiple busy={!!progress} />
          {progress && <span className="muted">{progress}</span>}
        </div>
      )}
      {error && <div className="error" style={{ whiteSpace: "pre-line" }}>{error}</div>}
      {groups.map((g) => (
        <div key={g.day ?? "-"} className="visit">
          {dateField && (
            <h5>{g.day ? `Wizytacja ${g.day.split("-").reverse().join(".")}` : "Bez daty"}
              <span className="muted"> ({photosLabel(g.items.length)})</span></h5>
          )}
          <div className="thumbs">
            {g.items.map((f) => (
              <button key={f.id} type="button" className="thumb" onClick={() => setOpen(items.indexOf(f))} title={`#${f.id}`}>
                <img src={url(f, true)} alt={`Zdjęcie #${f.id}`} loading="lazy" />
              </button>
            ))}
          </div>
        </div>
      ))}
      {!items.length && <p className="muted">Brak zdjęć.</p>}
      {withoutPhoto > 0 && <p className="muted">{withoutPhoto} rekord(y) bez pliku zdjęcia.</p>}
      {open !== null && items[open] && (
        <Lightbox src={url(items[open], false)} index={open} count={items.length}
          onNav={(d) => setOpen((open + d + items.length) % items.length)} onClose={() => setOpen(null)}
          onOpenRecord={() => { const f = items[open]; setOpen(null); onOpenRecord(layer.id, String(f.id)); }}
          onDelete={layer.perms.delete ? () => remove(items[open]) : undefined} />
      )}
    </section>
  );
}

function Lightbox({ src, index, count, onNav, onClose, onOpenRecord, onDelete }: {
  src: string; index: number; count: number; onNav: (d: number) => void; onClose: () => void;
  onOpenRecord: () => void; onDelete?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const touchX = useRef<number | null>(null);
  return (
    <div className="lightbox" ref={ref} tabIndex={-1} role="dialog" aria-label="Podgląd zdjęcia"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
        else if (e.key === "ArrowRight") onNav(1);
        else if (e.key === "ArrowLeft") onNav(-1);
      }}
      onTouchStart={(e) => { touchX.current = e.touches[0].clientX; }}
      onTouchEnd={(e) => {
        if (touchX.current === null) return;
        const dx = e.changedTouches[0].clientX - touchX.current;
        touchX.current = null;
        if (Math.abs(dx) > 50 && count > 1) onNav(dx < 0 ? 1 : -1);
      }}>
      <img src={src} alt={`Zdjęcie ${index + 1} z ${count}`} />
      <div className="lightbox-bar">
        {count > 1 && <button onClick={() => onNav(-1)} title="Poprzednie">‹</button>}
        <span>{index + 1} / {count}</span>
        {count > 1 && <button onClick={() => onNav(1)} title="Następne">›</button>}
        <a className="button" href={src} target="_blank" rel="noreferrer">Pełny rozmiar</a>
        <button onClick={onOpenRecord}>Rekord</button>
        {onDelete && <button className="danger" onClick={onDelete}>Usuń</button>}
        <button onClick={onClose} title="Zamknij">✕</button>
      </div>
    </div>
  );
}
