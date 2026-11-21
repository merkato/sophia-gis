// Wtyczki Sophii po stronie WebUI: moduł ES wtyczki ładowany dynamicznie z /api/plugins/<id>/web/…
// Kontrakt (wersja 1, docs/WTYCZKI.md): moduł eksportuje `register(host)` i zwraca
// `{ pages: { <idStrony>: KomponentReact } }`. Sophia daje wtyczce Reacta (bez dublowania go w paczce),
// zapytania do jej API, dane użytkownika i powiadomienia.
import React from "react";
import { request } from "./api";
import type { User } from "./types";

export interface PluginPage { id: string; title: string; capability?: string; toolbar?: boolean }
export interface PluginInfo {
  id: string; name: string; menu?: string; version: string; capabilities: string[];
  web: string | null;           // adres modułu ES (null = wtyczka bez interfejsu)
  pages: PluginPage[];          // strony w panelu administracji, które użytkownik może otworzyć
  windows?: PluginPage[];       // okna otwierane z górnego paska (nad mapą)
}

export interface SophiaHost {
  apiVersion: 1;
  React: typeof React;
  pluginId: string;
  user: Pick<User, "id" | "login" | "full_name" | "is_admin">;
  capabilities: string[];
  can: (capability: string) => boolean;
  /** Zapytanie do API wtyczki: ścieżka względem /api/plugins/<id> (np. "/importy"). JSON albo FormData. */
  api: <T = unknown>(path: string, init?: RequestInit) => Promise<T>;
  /** Zapytanie do dowolnego endpointu Sophii (pełna ścieżka /api/…). */
  request: <T = unknown>(path: string, init?: RequestInit) => Promise<T>;
  notify: (message: string) => void;
  /**
   * Pokazuje obiekt na mapie: zamyka panel administracji, otwiera projekt (jeśli podany), a potem —
   * gdy projekt ma warstwę z którejś z tabel `targets` — otwiera ten obiekt (formularz + przybliżenie);
   * inaczej przybliża i podświetla `geometry` (GeoJSON w EPSG:4326).
   */
  showOnMap: (focus: MapFocus) => void;
  /** Otwiera (albo odświeża) okno wtyczki nad mapą; `props` trafiają do komponentu okna. */
  openWindow: (windowId: string, opts?: { props?: Record<string, unknown>; title?: string }) => void;
  closeWindow: (windowId: string) => void;
}

export interface PluginWindowProps { host: SophiaHost; props: Record<string, unknown>; close: () => void }
type WindowHandler = (pluginId: string, windowId: string, opts?: { props?: Record<string, unknown>; title?: string } | null) => void;
let windowHandler: WindowHandler | null = null;
/** App rejestruje tu obsługę okien wtyczek (null w opts = zamknij). */
export function setWindowHandler(fn: WindowHandler | null) { windowHandler = fn; }

export interface MapFocus {
  newTab?: boolean;                                 // otwórz mapę w nowej karcie (panel zostaje na miejscu)
  project?: string;                                 // slug projektu; brak = bieżący
  targets?: { table: string; pk: string }[];        // „schemat.tabela” + klucz główny obiektu
  geometry?: { type: string; coordinates: unknown } | null;   // EPSG:4326
  label?: string;
}

let mapFocusHandler: ((f: MapFocus) => void) | null = null;
/** App rejestruje tu obsługę `host.showOnMap`. */
export function setMapFocusHandler(fn: ((f: MapFocus) => void) | null) { mapFocusHandler = fn; }

export interface PluginModule {
  register: (host: SophiaHost) => {
    pages?: Record<string, React.ComponentType<{ host: SophiaHost }>>;
    windows?: Record<string, React.ComponentType<PluginWindowProps>>;
  };
}

export interface LoadedPlugin {
  pages: Record<string, React.ComponentType<{ host: SophiaHost }>>;
  windows: Record<string, React.ComponentType<PluginWindowProps>>;
  host: SophiaHost;
}
const modules = new Map<string, Promise<LoadedPlugin>>();

/**
 * Nowa karta z mapą: obiekt do pokazania przekazany przez localStorage (geometria bywa za duża na adres),
 * nowa karta odczytuje go z parametru ?fokus=<klucz> i usuwa (takeMapFocus).
 */
function openMapTab(f: MapFocus) {
  const key = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  try { localStorage.setItem(`sophia-fokus-${key}`, JSON.stringify({ ...f, newTab: false })); } catch { /* bez pamięci: tylko projekt */ }
  const q = new URLSearchParams({ ...(f.project ? { p: f.project } : {}), fokus: key });
  window.open(`${location.pathname}?${q}`, "_blank");
}

export function takeMapFocus(key: string): MapFocus | null {
  try {
    const k = `sophia-fokus-${key}`;
    const v = localStorage.getItem(k);
    localStorage.removeItem(k);
    // przy okazji: porzucone wpisy starsze niż doba
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const n = localStorage.key(i);
      if (n?.startsWith("sophia-fokus-") && Date.now() - parseInt(n.slice(13, 21), 36) > 86400000) localStorage.removeItem(n);
    }
    return v ? (JSON.parse(v) as MapFocus) : null;
  } catch {
    return null;
  }
}

/** Ładuje moduł wtyczki raz na sesję i wywołuje `register`. */
export function loadPlugin(p: PluginInfo, user: User, notify: (m: string) => void): Promise<LoadedPlugin> {
  const key = `${p.id}@${p.version}`;
  let m = modules.get(key);
  if (!m) {
    const host: SophiaHost = {
      apiVersion: 1, React, pluginId: p.id,
      user: { id: user.id, login: user.login, full_name: user.full_name, is_admin: user.is_admin },
      capabilities: p.capabilities,
      can: (c) => p.capabilities.includes(c),
      api: (path, init) => request(`/api/plugins/${p.id}${path}`, init),
      request: (path, init) => request(path, init),
      notify,
      showOnMap: (f) => {
        if (f.newTab) { openMapTab(f); return; }
        if (mapFocusHandler) mapFocusHandler(f); else notify("Mapa nie jest dostępna");
      },
      openWindow: (id, opts) => { if (windowHandler) windowHandler(p.id, id, opts ?? {}); },
      closeWindow: (id) => { if (windowHandler) windowHandler(p.id, id, null); },
    };
    m = (import(/* @vite-ignore */ p.web!) as Promise<PluginModule>)
      .then((mod) => { const r = mod.register(host); return { pages: r.pages ?? {}, windows: r.windows ?? {}, host }; });
    modules.set(key, m);
    m.catch(() => modules.delete(key));
  }
  return m;
}
