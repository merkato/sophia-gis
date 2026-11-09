import type { FieldDef } from "../types";

/** Kontrolka formularza odwzorowująca widżet edycji z projektu QGIS. */
export function FieldInput({ field, value, onChange, readOnly }: {
  field: FieldDef;
  value: unknown;
  onChange: (v: unknown) => void;
  readOnly: boolean;
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
