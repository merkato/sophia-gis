// Wtyczki Sophii po stronie WebUI: moduł ES wtyczki ładowany dynamicznie z /api/plugins/<id>/web/…
// Kontrakt (wersja 1, docs/WTYCZKI.md): moduł eksportuje `register(host)` i zwraca
// `{ pages: { <idStrony>: KomponentReact } }`. Sophia daje wtyczce Reacta (bez dublowania go w paczce),
// zapytania do jej API, dane użytkownika i powiadomienia.
import React from "react";
import { request } from "./api";
import type { User } from "./types";

export interface PluginPage { id: string; title: string; capability?: string }
export interface PluginInfo {
  id: string; name: string; version: string; capabilities: string[];
  web: string | null;           // adres modułu ES (null = wtyczka bez interfejsu)
  pages: PluginPage[];          // strony w panelu administracji, które użytkownik może otworzyć
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
}

export interface MapFocus {
  project?: string;                                 // slug projektu; brak = bieżący
  targets?: { table: string; pk: string }[];        // „schemat.tabela” + klucz główny obiektu
  geometry?: { type: string; coordinates: unknown } | null;   // EPSG:4326
  label?: string;
}

let mapFocusHandler: ((f: MapFocus) => void) | null = null;
/** App rejestruje tu obsługę `host.showOnMap`. */
export function setMapFocusHandler(fn: ((f: MapFocus) => void) | null) { mapFocusHandler = fn; }

export interface PluginModule {
  register: (host: SophiaHost) => { pages?: Record<string, React.ComponentType<{ host: SophiaHost }>> };
}

export interface LoadedPlugin { pages: Record<string, React.ComponentType<{ host: SophiaHost }>>; host: SophiaHost }
const modules = new Map<string, Promise<LoadedPlugin>>();

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
      showOnMap: (f) => { if (mapFocusHandler) mapFocusHandler(f); else notify("Mapa nie jest dostępna"); },
    };
    m = (import(/* @vite-ignore */ p.web!) as Promise<PluginModule>)
      .then((mod) => ({ pages: mod.register(host).pages ?? {}, host }));
    modules.set(key, m);
    m.catch(() => modules.delete(key));
  }
  return m;
}
