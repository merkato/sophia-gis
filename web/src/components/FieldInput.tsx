import { useEffect, useState } from "react";
import { api } from "../api";
import type { FieldDef } from "../types";

interface Source { slug: string; layerId: string; version: number }
type Option = { value: string; label: string };

// Listy wartości dzielone między formularzami (klucz: projekt/warstwa/pole/wersja projektu)
const optionsCache = new Map<string, Promise<Option[]>>();

/** RelationReference (klucz obcy -> rekord warstwy nadrzędnej) i ValueRelation (słownik z innej warstwy). */
function RelationSelect({ field, value, onChange, disabled, source }: {
  field: FieldDef; value: unknown; onChange: (v: unknown) => void; disabled: boolean; source: Source;
}) {
  const [options, setOptions] = useState<Option[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const key = `${source.slug}/${source.layerId}/${field.name}@${source.version}`;
    let p = optionsCache.get(key);
    if (!p) {
      p = api.fieldOptions(source.slug, source.layerId, field.name).then((r) => r.options);
      p.catch(() => optionsCache.delete(key));
      optionsCache.set(key, p);
    }
    let cancelled = false;
    p.then((o) => !cancelled && setOptions(o)).catch((e) => !cancelled && setError((e as Error).message));
    return () => { cancelled = true; };
  }, [source.slug, source.layerId, source.version, field.name]);

  const cfg = field.widget_config as Record<string, unknown>;
  const allowNull = cfg.AllowNULL !== false && cfg.AllowNull !== false && !field.not_null;
  const numeric = /int|double|real|numeric|decimal/i.test(field.type ?? "");
  const str = value === null || value === undefined ? "" : String(value);
  if (error) return <input value={str} disabled title={error} />;
  const known = !str || (options ?? []).some((o) => o.value === str);
  return (
    <select value={str} disabled={disabled || options === null}
      onChange={(e) => onChange(e.target.value === "" ? null : numeric ? Number(e.target.value) : e.target.value)}>
      {(allowNull || !str) && <option value="">{options === null ? "wczytywanie…" : "—"}</option>}
      {!known && <option value={str}>{str} (brak w słowniku)</option>}
      {(options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

/** Kontrolka formularza odwzorowująca widżet edycji z projektu QGIS. */
export function FieldInput({ field, value, onChange, readOnly, source }: {
  field: FieldDef;
  value: unknown;
  onChange: (v: unknown) => void;
  readOnly: boolean;
  source?: Source;                    // potrzebne dla widżetów relacyjnych (lista wartości z API)
}) {
  const cfg = field.widget_config as Record<string, unknown>;
  const disabled = readOnly || !field.editable;
  const str = value === null || value === undefined ? "" : String(value);

  switch (field.widget) {
    case "ValueMap": {
      // QGIS: {"map": [{"Etykieta": "wartość"}, ...]} lub {"map": {"Etykieta": "wartość"}}
      const raw = cfg.map;
      const entries: [string, string][] = Array.isArray(raw)
        ? raw.flatMap((o) => Object.entries(o as Record<string, string>))
        : Object.entries((raw ?? {}) as Record<string, string>);
      return (
        <select value={str} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">—</option>
          {entries.map(([label, v]) => <option key={v} value={v}>{label}</option>)}
        </select>
      );
    }
    case "CheckBox": {
      const on = cfg.CheckedState ?? true;
      const off = cfg.UncheckedState ?? false;
      const checked = value === true || (value !== null && String(value) === String(on));
      return (
        <input type="checkbox" checked={checked} disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? (on === "" ? true : on) : (off === "" ? false : off))} />
      );
    }
    case "DateTime": {
      const fmt = String(cfg.field_format ?? "yyyy-MM-dd");
      const isDateTime = fmt.includes("HH");
      return (
        <input type={isDateTime ? "datetime-local" : "date"} value={str.slice(0, isDateTime ? 16 : 10)}
          disabled={disabled} onChange={(e) => onChange(e.target.value || null)} />
      );
    }
    case "Range":
      return (
        <input type="number" value={str} disabled={disabled}
          min={cfg.Min as number | undefined} max={cfg.Max as number | undefined} step={(cfg.Step as number) ?? "any"}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
      );
    case "RelationReference":
    case "ValueRelation":
      if (source) return <RelationSelect field={field} value={value} onChange={onChange} disabled={disabled} source={source} />;
    // fallthrough — bez źródła: zwykłe pole
    case "TextEdit":
      if (cfg.IsMultiline) {
        return <textarea rows={4} value={str} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
      }
    // fallthrough
    default: {
      const numeric = /int|double|real|numeric|decimal/i.test(field.type ?? "");
      return (
        <input type={numeric ? "number" : "text"} value={str} disabled={disabled}
          onChange={(e) => onChange(numeric ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)} />
      );
    }
  }
}
