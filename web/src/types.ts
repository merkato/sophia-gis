export interface User {
  id: number;
  login: string;
  full_name: string | null;
  is_admin: boolean;
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
  attachments: boolean;
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
}

export interface GeoJSONFeature {
  type: "Feature";
  id: string;
  geometry: { type: string; coordinates: unknown } | null;
  properties: Record<string, unknown>;
}

export interface Attachment {
  id: string;
  file_name: string;
  size_bytes: number;
  description: string | null;
  uploaded_at: string;
  uploaded_by: string | null;
}

export interface RelatedGroup {
  relation: string;
  name: string;
  direction: "child" | "parent";
  layer_id: string;
  pairs: [string, string][];
  features: GeoJSONFeature[];
}
