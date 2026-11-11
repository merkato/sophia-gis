import { useState } from "react";
import { api } from "../api";
import type { FieldDef, GeoJSONFeature, LayerInfo, ProjectConfig, RelatedGroup } from "../types";
import { dateFieldOf, dayOf, isPhotoField } from "./Photos";

// Dokumenty (PDF, GML z podpisem, DOCX…) w polach z widżetem QGIS „Załącznik” bez podglądu obrazu:
//   wariant A — pole w tabeli obiektu (FileField w formularzu),
//   wariant B — tabela dokumentów powiązana relacją (DocumentList w zakładce „Dokumenty”).
// Pliki są zapisywane bez zmian; dozwolone typy z filtra plików widżetu. docs/user/zalaczniki.md

export function isFileField(f: FieldDef): boolean {
  return f.widget === "ExternalResource" && !isPhotoField(f);
}

/** Tabela dokumentów: pole „Załącznik” na pliki i żadnego pola na zdjęcia (te mają galerię). */
export function fileFieldOf(layer: LayerInfo | undefined): FieldDef | undefined {
  if (!layer || layer.fields.some(isPhotoField)) return undefined;
  return layer.fields.find(isFileField);
}

/** Filtr QGIS „PDF (*.pdf);;GML (*.gml *.xml)” -> accept=".pdf,.gml,.xml" (pusty = dowolne). */
function acceptOf(f: FieldDef): string | undefined {
  const flt = String(f.widget_config?.FileWidgetFilter ?? "");
  if (!flt.trim() || flt.includes("*.*")) return undefined;
  const exts = [...flt.matchAll(/\*\.([0-9A-Za-z_+-]+)/g)].map((m) => `.${m[1].toLowerCase()}`);
  return exts.length ? [...new Set(exts)].join(",") : undefined;
}

export function fileName(path: unknown): string {
  return String(path ?? "").replace(/\\/g, "/").split("/").pop() ?? "";
}

const EXT_ICON: Record<string, string> = {
  pdf: "📕", gml: "🗺️", xml: "🧾", xades: "🔏", sig: "🔏", docx: "📝", doc: "📝", odt: "📝", xlsx: "📊",
  xls: "📊", ods: "📊", csv: "📊", zip: "🗜️", "7z": "🗜️", dwg: "📐", dxf: "📐", txt: "📄",
};
const iconFor = (name: string) => EXT_ICON[name.split(".").pop()?.toLowerCase() ?? ""] ?? "📄";

function PickFiles({ field, multiple, busy, onFiles, label }: {
  field: FieldDef; multiple?: boolean; busy: boolean; onFiles: (files: File[]) => void; label: string;
}) {
  return (
    <label className={`upload${busy ? " disabled" : ""}`} title={acceptOf(field) ? `Dozwolone: ${acceptOf(field)}` : undefined}>
      📎 {label}
      <input type="file" accept={acceptOf(field)} multiple={multiple} hidden disabled={busy}
        onChange={(e) => { const files = [...(e.target.files ?? [])]; e.target.value = ""; if (files.length) onFiles(files); }} />
    </label>
  );
}

/** Wariant A: jeden plik w polu obiektu. Wartość pola = ścieżka względna zwrócona przez serwer. */
export function FileField({ field, value, saved, onChange, disabled, slug, layerId, pk, crs }: {
  field: FieldDef; value: unknown; saved: unknown; onChange: (v: unknown) => void; disabled: boolean;
  slug: string; layerId: string; pk: string | null; crs: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const str = value === null || value === undefined ? "" : String(value);
  const isSaved = !!str && !!pk && str === String(saved ?? "");
  const name = fileName(str);

  const upload = async ([file]: File[]) => {
    setBusy(true);
    setError(null);
    try {
      const meta = await api.uploadFile(slug, layerId, field.name, file, crs);
      onChange(meta.path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="file-field">
      {str ? (
        isSaved ? (
          <a className="file-link" href={api.fileUrl(slug, layerId, pk!, field.name, str)} target="_blank" rel="noreferrer">
            {iconFor(name)} {name}
          </a>
        ) : <span className="file-link" title={str}>{iconFor(name)} {name}</span>
      ) : <span className="muted">Brak pliku</span>}
      {!disabled && (
        <div className="toolgroup">
          <PickFiles field={field} busy={busy} onFiles={upload} label={str ? "Zmień plik" : "Wybierz plik"} />
          {str && <button type="button" className="danger" disabled={busy} onClick={() => onChange(null)}>Usuń plik</button>}
          {busy && <span className="muted">Wysyłanie…</span>}
        </div>
      )}
      {!disabled && str && !isSaved && !busy && <div className="muted">Plik zostanie przypisany po zapisaniu formularza.</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

/** Wariant B: lista dokumentów z tabeli powiązanej relacją (rodzic = otwarty obiekt). */
export function DocumentList({ config, group, parentLayerId, parentPk, onChanged, onOpenRecord }: {
  config: ProjectConfig; group: RelatedGroup; parentLayerId: string; parentPk: string;
  onChanged: () => void; onOpenRecord: (layerId: string, pk: string) => void;
}) {
  const layer = config.layers[group.layer_id];
  const field = fileFieldOf(layer)!;
  const dateField = dateFieldOf(layer);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rows = group.features
    .filter((f) => f.properties[field.name])
    .sort((a, b) => String(b.properties[dateField?.name ?? ""] ?? "").localeCompare(String(a.properties[dateField?.name ?? ""] ?? ""))
      || fileName(a.properties[field.name]).localeCompare(fileName(b.properties[field.name]), "pl"));

  const upload = async (files: File[]) => {
    setError(null);
    const failed: string[] = [];
    for (const [i, file] of files.entries()) {
      setProgress(files.length > 1 ? `Wysyłanie ${i + 1}/${files.length}…` : "Wysyłanie…");
      try {
        await api.uploadFile(config.slug, layer.id, field.name, file, config.crs, { layerId: parentLayerId, pk: parentPk });
      } catch (e) {
        failed.push(`${file.name}: ${(e as Error).message}`);
      }
    }
    setProgress(null);
    if (failed.length) setError(failed.join("\n"));
    onChanged();
  };

  const remove = async (f: GeoJSONFeature) => {
    if (!confirm(`Usunąć dokument „${fileName(f.properties[field.name])}” (rekord w tabeli dokumentów)?`)) return;
    try {
      await api.deleteFeature(config.slug, layer.id, String(f.id));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="documents">
      <h4>{group.name} <span className="muted">({rows.length})</span></h4>
      {layer.perms.insert && (
        <div className="toolgroup">
          <PickFiles field={field} multiple busy={!!progress} onFiles={upload} label="Dodaj pliki" />
          {progress && <span className="muted">{progress}</span>}
        </div>
      )}
      {error && <div className="error" style={{ whiteSpace: "pre-line" }}>{error}</div>}
      <ul>
        {rows.map((f) => {
          const name = fileName(f.properties[field.name]);
          const day = dateField ? dayOf(f.properties[dateField.name]) : null;
          return (
            <li key={f.id}>
              <a href={api.fileUrl(config.slug, layer.id, String(f.id), field.name, f.properties[field.name])}
                target="_blank" rel="noreferrer" title="Otwórz / pobierz">{iconFor(name)} {name}</a>
              {day && <span className="muted"> {day.split("-").reverse().join(".")}</span>}
              <span className="row-actions">
                <button className="icon" title="Otwórz rekord dokumentu" onClick={() => onOpenRecord(layer.id, String(f.id))}>✎</button>
                {layer.perms.delete && <button className="icon" title="Usuń dokument" onClick={() => remove(f)}>✕</button>}
              </span>
            </li>
          );
        })}
        {!rows.length && <li className="muted">Brak dokumentów.</li>}
      </ul>
    </section>
  );
}
