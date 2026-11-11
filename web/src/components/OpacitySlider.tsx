import { useState } from "react";

/**
 * Przycisk „◐” przy warstwie rastrowej, podkładzie albo nakładce: rozwija suwak przezroczystości.
 * Wartość 0–100 (% krycia); stan trzyma App (zapamiętany w przeglądarce).
 */
export function OpacityButton({ open, value, onToggle, label }: {
  open: boolean; value: number; onToggle: () => void; label: string;
}) {
  return (
    <button className={`edit-btn opacity-btn${open ? " active" : ""}${value < 100 ? " changed" : ""}`}
      title={`Przezroczystość: ${label} (${value}%)`} aria-label={`Przezroczystość: ${label}`}
      aria-expanded={open} onClick={onToggle}>◐</button>
  );
}

export function OpacityRow({ value, onChange, indent = 0 }: {
  value: number; onChange: (v: number) => void; indent?: number;
}) {
  return (
    <div className="opacity-row" style={{ paddingLeft: indent }}>
      <input type="range" min={0} max={100} step={5} value={value} aria-label="Krycie"
        onChange={(e) => onChange(Number(e.target.value))} />
      <span className="muted">{value}%</span>
      {value !== 100 && <button className="link" onClick={() => onChange(100)} title="Pełne krycie">↺</button>}
    </div>
  );
}

/** Stan rozwinięcia suwaków (który wiersz pokazuje suwak) — lokalny dla listy. */
export function useOpenSliders() {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(key)) n.delete(key); else n.add(key);
    return n;
  });
  return { isOpen: (key: string) => open.has(key), toggle };
}

// --- zapamiętane krycie: { "<slug>/<warstwa WMS>": 70, "bm:<id>": 50 }
const KEY = "sophia.opacity";

export function loadOpacity(): Record<string, number> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return v && typeof v === "object" ? v : {};
  } catch { return {}; }
}

export function saveOpacity(o: Record<string, number>) {
  try { localStorage.setItem(KEY, JSON.stringify(o)); } catch { /* brak dostępu do localStorage */ }
}
