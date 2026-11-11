export interface User {
  id: number;
  login: string;
  full_name: string | null;
  is_admin: boolean;
  can_publish?: boolean;
  groups: string[];
}

export interface ProjectSummary {
  slug: string;
  title: string;
  description: string | null;
}

export interface FieldDef {
  name: string;
  alias: string | null;
  type: string | null;
  widget: string;
  widget_config: Record<string, unknown>;
  editable: boolean;
  not_null: boolean;
  default_expression: string | null;
}

export interface LayerPerms {
  view: boolean;
  insert: boolean;
  update: boolean;
  delete: boolean;
}

export interface LayerInfo {
  id: string;
  name: string;
  wms_name: string;
  type: "vector" | "raster";
  tile_format: string | null;        // rastry: kafle WMS w tym formacie; wektory: null (bez kafli)
  geometry_type: "Point" | "Line" | "Polygon" | null;
  crs: string | null;
  popup: boolean;
  display_expression: string | null;
  primary_key: string | null;
  fields: FieldDef[];
  perms: LayerPerms;
}

export interface TreeNode {
  kind: "group" | "layer" | "raster_group";
  name: string;
  layer_id: string | null;
  visible: boolean;
  expanded: boolean;
  mutually_exclusive: boolean;
  children: TreeNode[];
}

export interface RelationDef {
  id: string;
  name: string;
  parent_layer: string;
  child_layer: string;
  pairs: [string, string][];
  strength: string;
}

export interface ReportDef {
  layout: string;
  title: string;
  layer_id: string | null;
}

export interface ProjectConfig {
  slug: string;
  title: string;
  role: string | null;
  crs: string;
  version: number;                   // zmienia się przy publikacji projektu (adresy kafli)
  extent: [number, number, number, number] | null;
  options: Record<string, unknown>;
  tree: TreeNode;
  layers: Record<string, LayerInfo>;
  relations: RelationDef[];
  reports: ReportDef[];
  tools: ToolInfo[];
  scope: { label: string; codes: string[] | null } | null;   // codes null = cały obszar
  rights: { photos: boolean; files: boolean };
}

/** Narzędzie pobierania z Fii (np. działka z ULDK -> warstwa projektu). */
export interface ToolInfo {
  id: string;
  label: string;
  source: string;                    // uldk_dzialka | uldk_budynek | …
  source_name: string;
  layer_id: string;
  open_form: boolean;
}

/** Wynik zapytania narzędzia: obiekt z usługi, atrybuty zmapowane na pola warstwy docelowej. */
export interface FetchResult {
  tool_id: string;
  layer_id: string;
  source: string;
  source_name: string;
  key: string | null;
  properties: Record<string, string | null>;
  labels: Record<string, string>;
  mapped: Record<string, string | null>;
  geometry: GeoJSONFeature["geometry"];
  existing_pk: string | null;
  open_form: boolean;
}

export interface GeoJSONFeature {
  type: "Feature";
  id: string;
  geometry: { type: string; coordinates: unknown } | null;
  properties: Record<string, unknown>;
}

/** Zdjęcie po przetworzeniu na serwerze (ścieżka względna do wpisania w pole „Załącznik”). */
export interface PhotoMeta {
  path: string;
  width: number;
  height: number;
  taken_at: string | null;
  lon: number | null;
  lat: number | null;
}

/** Dokument zapisany na serwerze bez zmian (suma SHA-256 — np. do weryfikacji pliku z podpisem). */
export interface FileMeta {
  path: string;
  name: string;
  size: number;
  sha256: string;
}

export interface RelatedGroup {
  relation: string;
  name: string;
  direction: "child" | "parent";
  layer_id: string;
  pairs: [string, string][];
  features: GeoJSONFeature[];
}

// --- podkłady (wspólny katalog dla wszystkich projektów)
export interface WmtsTileGrid {
  crs: string;
  origin: [number, number];
  origins?: [number, number][] | null;
  resolutions: number[];
  matrix_ids: string[];
  tile_size: [number, number];
}

export interface Basemap {
  id: number;
  name: string;
  kind: "wmts" | "xyz" | "sophia";
  is_overlay: boolean;
  opacity: number;
  visible_default: boolean;
  enabled?: boolean;
  sort_order: number;
  attribution: string | null;
  // wmts: url, request_encoding, layer, style, format, matrix_set, tile_grid, capabilities_url
  // xyz: url, max_zoom   sophia: project, layers, format
  config: Record<string, any>;
  version: number;
}

export interface WmtsCapabilities {
  title: string | null;
  kvp_url: string | null;
  capabilities_url: string | null;
  layers: {
    identifier: string; title: string; formats: string[]; styles: string[]; default_style: string | null;
    matrix_sets: string[]; wgs84_bbox: number[] | null; resource_urls: Record<string, string>;
  }[];
  matrix_sets: Record<string, WmtsTileGrid>;
}

// --- panel administratora
export interface AdminUser {
  id: number; login: string; full_name: string | null; email: string | null;
  is_admin: boolean; is_active: boolean; can_publish: boolean; last_login_at: string | null; group_ids: number[];
}
export interface Group { id: number; name: string; description: string | null }
export interface AdminProject {
  id: number; slug: string; title: string; description: string | null; file_name: string;
  sort_order: number; is_public: boolean;
}
export type ProjectRole = "viewer" | "editor" | "manager";
/** Grupa w projekcie: rola, prawa do zdjęć/dokumentów i zakres danych. */
export interface GroupAccess {
  group_id: number;
  role: ProjectRole;
  can_photos: boolean;
  can_files: boolean;
  scope_all: boolean;               // cały obszar; inaczej tylko scope_codes
  scope_codes: string[];
}
export interface ProjectAccess {
  groups: GroupAccess[];
  layers: Record<string, unknown>[];
}
/** Wymiar zakresu projektu (z Fii) i kody obszarów z warstwy granic. */
export interface ProjectScopeInfo {
  scope: null | {
    label: string; layer: string; field: string; codes: string[];
    layers: Record<string, { name: string; mode: string; field: string | null }>;
  };
}
