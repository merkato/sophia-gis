// Wtyczki Sophii po stronie WebUI: moduł ES wtyczki ładowany dynamicznie z /api/plugins/<id>/web/…
// Kontrakt (wersja 1, docs/WTYCZKI.md): moduł eksportuje `register(host)` i zwraca
// `{ pages: { <idStrony>: KomponentReact } }`. Sophia daje wtyczce Reacta (bez dublowania go w paczce),
// zapytania do jej API, dane użytkownika i powiadomienia.
import React, { useSyncExternalStore } from "react";
import { request } from "./api";
import type { User } from "./types";

export interface PluginPage {
  id: string; title: string; capability?: string; toolbar?: boolean;
  menu?: string;     // okna: nazwa menu rozwijanego w górnym pasku (okna o tej samej nazwie — w jednym menu)
  order?: number;    // okna: kolejność w górnym pasku (rosnąco; brak = 500)
}
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
  /** Rysowanie nowego obiektu w warstwie projektu z tabeli `table` z wypełnionymi polami (np. klucz rodzica);
   *  `geometry` (EPSG:4326) — gdzie przybliżyć mapę. Warstwa bez geometrii: od razu formularz. */
  startDraw: (opts: { project?: string; table: string; defaults?: Record<string, unknown>; geometry?: MapFocus["geometry"]; label?: string }) => void;
  closeWindow: (windowId: string) => void;
  /** Slug projektu otwartego w oknie mapy (null — bez projektu). Sophia ≥ 0.6. */
  currentProject: () => string | null;
  /** Zasięg bieżącego widoku mapy: [minX, minY, maxX, maxY] w układzie projektu (`crs`), null bez mapy. Sophia ≥ 0.7. */
  currentExtent: () => { bbox: [number, number, number, number]; crs: string } | null;
}

export interface PluginWindowProps { host: SophiaHost; props: Record<string, unknown>; close: () => void }
type WindowHandler = (pluginId: string, windowId: string, opts?: { props?: Record<string, unknown>; title?: string } | null) => void;
let windowHandler: WindowHandler | null = null;
/** App rejestruje tu obsługę okien wtyczek (null w opts = zamknij). */
export function setWindowHandler(fn: WindowHandler | null) { windowHandler = fn; }

export interface MapFocus {
  newTab?: boolean;                                 // otwórz mapę w nowej karcie (panel zostaje na miejscu)
  draw?: { table: string; defaults?: Record<string, unknown> };   // po przybliżeniu: rysowanie nowego obiektu w warstwie
  project?: string;                                 // slug projektu; brak = bieżący
  targets?: { table: string; pk: string }[];        // „schemat.tabela” + klucz główny obiektu
  geometry?: { type: string; coordinates: unknown } | null;   // EPSG:4326
  label?: string;
}

let mapFocusHandler: ((f: MapFocus) => void) | null = null;
let projectGetter: (() => string | null) | null = null;
/** App rejestruje tu odczyt bieżącego projektu mapy (`host.currentProject`). */
export function setCurrentProjectGetter(fn: (() => string | null) | null) { projectGetter = fn; }
type Extent = { bbox: [number, number, number, number]; crs: string };
let extentGetter: (() => Extent | null) | null = null;
/** App rejestruje tu odczyt zasięgu widoku mapy (`host.currentExtent`). */
export function setCurrentExtentGetter(fn: (() => Extent | null) | null) { extentGetter = fn; }
/** App rejestruje tu obsługę `host.showOnMap`. */
export function setMapFocusHandler(fn: ((f: MapFocus) => void) | null) { mapFocusHandler = fn; }

/** Przycisk wtyczki w formularzu obiektu (np. „Decyzja (PDF)” przy konturze). */
export interface FeatureAction { label: string; title?: string; run: () => void }
/** Obiekt, dla którego wtyczka podaje akcje: tabela źródłowa warstwy („schemat.tabela”), klucz i atrybuty. */
export interface FeatureRef { table: string; pk: string; layerId: string; project: string; properties: Record<string, unknown> }
export type FeatureActionsFn = (f: FeatureRef) => FeatureAction[];

export interface PluginModule {
  register: (host: SophiaHost) => {
    pages?: Record<string, React.ComponentType<{ host: SophiaHost }>>;
    windows?: Record<string, React.ComponentType<PluginWindowProps>>;
    /** Akcje w formularzu obiektów warstw z danej tabeli: { "schemat.tabela": (obiekt) => [akcje] }. */
    featureActions?: Record<string, FeatureActionsFn>;
    /** Element w pasku narzędzi pod górnym paskiem (np. pole wyszukiwania); wtyczka sama sprawdza uprawnienia. Sophia ≥ 0.8. */
    toolbar?: React.ComponentType<{ host: SophiaHost }>;
  };
}

export interface LoadedPlugin {
  pages: Record<string, React.ComponentType<{ host: SophiaHost }>>;
  windows: Record<string, React.ComponentType<PluginWindowProps>>;
  featureActions: Record<string, FeatureActionsFn>;
  toolbar: React.ComponentType<{ host: SophiaHost }> | null;
  host: SophiaHost;
}
const modules = new Map<string, Promise<LoadedPlugin>>();

// wtyczki załadowane w tej sesji — źródło akcji formularza (wersja zmienia się po każdym załadowaniu)
const loaded = new Map<string, LoadedPlugin>();
let loadedVersion = 0;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** Akcje wtyczek dla obiektu (błąd jednej wtyczki nie psuje formularza). */
export function featureActions(f: FeatureRef): FeatureAction[] {
  const out: FeatureAction[] = [];
  for (const p of loaded.values()) {
    const fn = p.featureActions[f.table];
    if (!fn) continue;
    try { out.push(...(fn(f) ?? [])); } catch (e) { console.error(`Akcje wtyczki ${p.host.pluginId}:`, e); }
  }
  return out;
}

/** Elementy wtyczek w pasku narzędzi (w kolejności identyfikatorów wtyczek). */
export function toolbarWidgets(): { id: string; Widget: React.ComponentType<{ host: SophiaHost }>; host: SophiaHost }[] {
  return [...loaded.entries()].filter(([, p]) => p.toolbar).sort(([a], [b]) => a.localeCompare(b))
    .map(([id, p]) => ({ id, Widget: p.toolbar!, host: p.host }));
}

/** Odświeża komponent, gdy załadowano kolejną wtyczkę (np. formularz otwarty przed załadowaniem). */
export function usePluginsVersion(): number {
  return useSyncExternalStore(subscribe, () => loadedVersion);
}

/** Ładuje w tle moduły wszystkich wtyczek z interfejsem — akcje w formularzach obiektów są dostępne od razu. */
export function preloadPlugins(list: PluginInfo[], user: User, notify: (m: string) => void) {
  for (const p of list) if (p.web) loadPlugin(p, user, notify).catch((e) => console.error(`Wtyczka ${p.id}:`, e));
}

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
      startDraw: (o) => {
        if (mapFocusHandler) mapFocusHandler({ project: o.project, geometry: o.geometry, label: o.label, draw: { table: o.table, defaults: o.defaults } });
        else notify("Mapa nie jest dostępna");
      },
      closeWindow: (id) => { if (windowHandler) windowHandler(p.id, id, null); },
      currentProject: () => (projectGetter ? projectGetter() : null),
      currentExtent: () => (extentGetter ? extentGetter() : null),
    };
    m = (import(/* @vite-ignore */ p.web!) as Promise<PluginModule>)
      .then((mod) => {
        const r = mod.register(host);
        const lp: LoadedPlugin = { pages: r.pages ?? {}, windows: r.windows ?? {}, featureActions: r.featureActions ?? {}, toolbar: r.toolbar ?? null, host };
        loaded.set(p.id, lp);
        loadedVersion += 1;
        listeners.forEach((fn) => fn());
        return lp;
      });
    modules.set(key, m);
    m.catch(() => modules.delete(key));
  }
  return m;
}
