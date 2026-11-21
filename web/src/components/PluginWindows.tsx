import { useEffect, useRef, useState, type ComponentType } from "react";
import { loadPlugin, type PluginInfo, type PluginWindowProps, type SophiaHost } from "../plugins";
import type { User } from "../types";
import { PluginBoundary } from "./PluginsTab";

export interface OpenWindow {
  key: string;                  // <pluginId>:<windowId>
  plugin: PluginInfo;
  windowId: string;
  title: string;
  props: Record<string, unknown>;
  z: number;
  pos: { x: number; y: number };
}

/** Okna wtyczek nad mapą: przeciągane za nagłówek, zmiana rozmiaru w rogu, kliknięcie przenosi na wierzch. */
export function PluginWindows({ windows, user, notify, onClose, onFocus, onMove }: {
  windows: OpenWindow[]; user: User; notify: (m: string) => void;
  onClose: (key: string) => void; onFocus: (key: string) => void; onMove: (key: string, pos: { x: number; y: number }) => void;
}) {
  return <>{windows.map((w) => <PluginWindow key={w.key} w={w} user={user} notify={notify}
    onClose={() => onClose(w.key)} onFocus={() => onFocus(w.key)} onMove={(p) => onMove(w.key, p)} />)}</>;
}

function PluginWindow({ w, user, notify, onClose, onFocus, onMove }: {
  w: OpenWindow; user: User; notify: (m: string) => void; onClose: () => void; onFocus: () => void;
  onMove: (pos: { x: number; y: number }) => void;
}) {
  const [loaded, setLoaded] = useState<{ C: ComponentType<PluginWindowProps>; host: SophiaHost } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  useEffect(() => {
    let alive = true;
    loadPlugin(w.plugin, user, notify)
      .then(({ windows, host }) => {
        if (!alive) return;
        const C = windows[w.windowId];
        if (C) setLoaded({ C, host }); else setError(`Wtyczka nie ma okna „${w.windowId}”`);
      })
      .catch((e) => alive && setError(`Nie udało się wczytać wtyczki: ${(e as Error).message}`));
    return () => { alive = false; };
  }, [w.plugin.id, w.plugin.version, w.windowId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const startDrag = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    drag.current = { dx: e.clientX - w.pos.x, dy: e.clientY - w.pos.y };
    const move = (ev: MouseEvent) => {
      if (!drag.current) return;
      onMove({ x: Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - drag.current.dx)),
               y: Math.max(0, Math.min(window.innerHeight - 40, ev.clientY - drag.current.dy)) });
    };
    const up = () => { drag.current = null; window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  return (
    <section className="plugin-window" style={{ left: w.pos.x, top: w.pos.y, zIndex: 15 + w.z }} onMouseDown={onFocus}
      role="dialog" aria-label={w.title}>
      <header onMouseDown={startDrag}>
        <b>{w.title}</b>
        <button onClick={onClose} aria-label="Zamknij">✕</button>
      </header>
      <div className="plugin-window-body">
        {error ? <div className="error">{error}</div> : !loaded ? <p className="muted">Wczytywanie…</p> : (
          <PluginBoundary name={w.plugin.name}><loaded.C host={loaded.host} props={w.props} close={onClose} /></PluginBoundary>
        )}
      </div>
    </section>
  );
}
