import { useCallback, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

// Pływające okno nad mapą (formularz obiektu, tabela atrybutów): przesuwane za nagłówek, pozycja
// zapamiętana w przeglądarce pod własnym kluczem, dwuklik w nagłówek — na środek. Na telefonie
// okna są pełnoekranowe (CSS), bez przesuwania.

interface Pos { x: number; y: number }


const MOBILE = "(max-width: 800px)";
const KEEP_VISIBLE = 80;   // ile px okna musi zostać nad mapą przy przesuwaniu

function loadPos(key: string): Pos | null {
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? "null");
    return v && typeof v.x === "number" && typeof v.y === "number" ? v : null;
  } catch { return null; }
}

function savePos(key: string, p: Pos | null) {
  try { if (p) localStorage.setItem(key, JSON.stringify(p)); else localStorage.removeItem(key); } catch { /* brak storage */ }
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
export function useFloatingWindow(storageKey: string) {
  const ref = useRef<HTMLElement | null>(null);
  const [pos, setPos] = useState<Pos | null>(() => loadPos(storageKey));
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
    setPos((p) => { savePos(storageKey, p); return p; });
  }, []);

  const center = useCallback(() => { setPos(null); savePos(storageKey, null); }, [storageKey]);

  return {
    ref,
    style: pos ? { left: pos.x, top: pos.y, bottom: "auto", transform: "none" } : undefined,
    handle: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, onDoubleClick: center },
  };
}
