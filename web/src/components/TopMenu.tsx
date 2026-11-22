import { useEffect, useRef, useState } from "react";
import type { PluginInfo, PluginPage } from "../plugins";

export interface MenuWindow { plugin: PluginInfo; w: PluginPage }
type Entry = { kind: "button"; order: number; item: MenuWindow } | { kind: "menu"; order: number; label: string; items: MenuWindow[] };

const orderOf = (x: MenuWindow) => (typeof x.w.order === "number" ? x.w.order : 500);

/** Okna wtyczek w górnym pasku: wg `order`, okna z tym samym `menu` w jednym menu rozwijanym
 *  (na miejscu pierwszego z nich). Menu z jednym dostępnym oknem — zwykły przycisk. */
export function menuEntries(windows: MenuWindow[]): Entry[] {
  const sorted = [...windows].sort((a, b) => orderOf(a) - orderOf(b) || a.w.title.localeCompare(b.w.title, "pl"));
  const groups = new Map<string, MenuWindow[]>();
  for (const x of sorted) {
    const m = x.w.menu?.trim();
    if (m) groups.set(m, [...(groups.get(m) ?? []), x]);
  }
  const out: Entry[] = [];
  const done = new Set<string>();
  for (const x of sorted) {
    const m = x.w.menu?.trim();
    if (!m || groups.get(m)!.length === 1) { out.push({ kind: "button", order: orderOf(x), item: x }); continue; }
    if (done.has(m)) continue;
    done.add(m);
    out.push({ kind: "menu", order: orderOf(x), label: m, items: groups.get(m)! });
  }
  return out;
}

function Dropdown({ label, items, onOpen }: { label: string; items: MenuWindow[]; onOpen: (x: MenuWindow) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="topmenu" ref={ref}>
      <button aria-haspopup="menu" aria-expanded={open} className={open ? "open" : undefined} onClick={() => setOpen((o) => !o)}>
        {label} <span className="caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="topmenu-list" role="menu">
          {items.map((x) => (
            <button key={`${x.plugin.id}:${x.w.id}`} role="menuitem" onClick={() => { setOpen(false); onOpen(x); }}>{x.w.title}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TopMenu({ windows, onOpen }: { windows: MenuWindow[]; onOpen: (x: MenuWindow) => void }) {
  return (
    <nav className="topnav" aria-label="Okna">
      {menuEntries(windows).map((e) => e.kind === "button"
        ? <button key={`${e.item.plugin.id}:${e.item.w.id}`} onClick={() => onOpen(e.item)}>{e.item.w.title}</button>
        : <Dropdown key={`m:${e.label}`} label={e.label} items={e.items} onOpen={onOpen} />)}
    </nav>
  );
}
