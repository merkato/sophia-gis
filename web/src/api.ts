import type {
  AdminProject, AdminUser, Basemap, FetchResult, FileMeta, GeoJSONFeature, Group, PhotoMeta, ProjectAccess, ProjectConfig, ProjectScopeInfo,
  ProjectSummary, RelatedGroup, User, WmtsCapabilities,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* odpowiedź nie-JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const enc = encodeURIComponent;
const featuresUrl = (slug: string, layerId: string) =>
  `/api/projects/${enc(slug)}/layers/${enc(layerId)}/features`;

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (login: string, password: string) =>
    request<{ token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ login, password }) }),
  logout: () => request("/api/auth/logout", { method: "POST" }),

  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (slug: string) => request<ProjectConfig>(`/api/projects/${enc(slug)}`),

  // bbox = null: wszystkie rekordy (tabele bez geometrii)
  features: (slug: string, layerId: string, bbox: number[] | null, crs: string) =>
    request<{ features: GeoJSONFeature[]; truncated: boolean }>(
      `${featuresUrl(slug, layerId)}?${bbox ? `bbox=${bbox.join(",")}&` : ""}crs=${enc(crs)}&limit=5000`),
  /** Strona tabeli atrybutów: bez geometrii, z sortowaniem, wyszukiwaniem i łączną liczbą rekordów. */
  tablePage: (slug: string, layerId: string, crs: string,
    o: { offset: number; limit: number; sort?: string | null; desc?: boolean; q?: string }) =>
    request<{ features: GeoJSONFeature[]; truncated: boolean; total: number }>(
      `${featuresUrl(slug, layerId)}?${new URLSearchParams({
        crs, geometry: "false", total: "true", offset: String(o.offset), limit: String(o.limit),
        ...(o.sort ? { sort: o.sort, desc: String(!!o.desc) } : {}), ...(o.q?.trim() ? { q: o.q.trim() } : {}),
      })}`),
  feature: (slug: string, layerId: string, pk: string, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}/${enc(pk)}?crs=${enc(crs)}`),
  createFeature: (slug: string, layerId: string, f: Partial<GeoJSONFeature>, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}?crs=${enc(crs)}`,
      { method: "POST", body: JSON.stringify(f) }),
  updateFeature: (slug: string, layerId: string, pk: string, f: Partial<GeoJSONFeature>, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}/${enc(pk)}?crs=${enc(crs)}`,
      { method: "PATCH", body: JSON.stringify({ type: "Feature", properties: {}, ...f }) }),
  /** Podział linią (POST …/split): dryRun — tylko klucze obiektów, które linia dzieli. */
  splitFeatures: (slug: string, layerId: string, line: GeoJSONFeature["geometry"], crs: string,
    o: { pks?: string[]; dryRun?: boolean } = {}) =>
    request<{ pks?: string[]; updated?: GeoJSONFeature[]; created?: GeoJSONFeature[] }>(
      `${featuresUrl(slug, layerId)}/split?crs=${enc(crs)}`,
      { method: "POST", body: JSON.stringify({ line, pks: o.pks ?? null, dry_run: !!o.dryRun }) }),
  deleteFeature: (slug: string, layerId: string, pk: string) =>
    request<void>(`${featuresUrl(slug, layerId)}/${enc(pk)}`, { method: "DELETE" }),
  related: (slug: string, layerId: string, pk: string, crs: string) =>
    request<RelatedGroup[]>(`${featuresUrl(slug, layerId)}/${enc(pk)}/related?crs=${enc(crs)}`),

  /** Zdjęcie do pola „Załącznik”. Z parent: od razu rekord w tabeli zdjęć powiązanej relacją. */
  uploadPhoto: (slug: string, layerId: string, field: string, file: File, crs: string,
    parent?: { layerId: string; pk: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("field", field);
    fd.append("crs", crs);
    if (parent) { fd.append("parent_layer", parent.layerId); fd.append("parent_pk", parent.pk); }
    return request<PhotoMeta & Partial<GeoJSONFeature> & { photo?: PhotoMeta }>(
      `/api/projects/${enc(slug)}/layers/${enc(layerId)}/photos`, { method: "POST", body: fd });
  },
  /** Dokument (PDF, GML…) do pola „Załącznik” — bez zmian; z parent: rekord w tabeli dokumentów. */
  uploadFile: (slug: string, layerId: string, field: string, file: File, crs: string,
    parent?: { layerId: string; pk: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("field", field);
    fd.append("crs", crs);
    if (parent) { fd.append("parent_layer", parent.layerId); fd.append("parent_pk", parent.pk); }
    return request<FileMeta & Partial<GeoJSONFeature> & { file?: FileMeta }>(
      `/api/projects/${enc(slug)}/layers/${enc(layerId)}/files`, { method: "POST", body: fd });
  },
  /** Plik z pola „Załącznik” zapisanego obiektu; v = wartość pola, żeby zmiana zdjęcia omijała cache. */
  fileUrl: (slug: string, layerId: string, pk: string, field: string, value: unknown, thumb = false) =>
    `${featuresUrl(slug, layerId)}/${enc(pk)}/files/${enc(field)}?${new URLSearchParams({
      ...(thumb ? { thumb: "1" } : {}), v: String(value ?? "") })}`,

  fetchTool: (slug: string, toolId: string, x: number, y: number, crs: string) =>
    request<FetchResult>(`/api/projects/${enc(slug)}/tools/${enc(toolId)}/fetch?${new URLSearchParams({
      x: String(x), y: String(y), crs })}`),

  reportInfo: (slug: string, layout: string, basemapIds: number[]) =>
    request<ReportInfo>(`/api/projects/${enc(slug)}/reports/${enc(layout)}/info?basemaps=${basemapIds.join(",")}`),
  reportUrl: (slug: string, layout: string, params: Record<string, string>) =>
    `/api/projects/${enc(slug)}/reports/${enc(layout)}?${new URLSearchParams(params)}`,

  basemaps: () => request<Basemap[]>("/api/basemaps"),

  // RelationReference / ValueRelation: wartości do wyboru dla pola formularza
  fieldOptions: (slug: string, layerId: string, field: string) =>
    request<{ layer_id: string; layer_name: string; options: { value: string; label: string }[] }>(
      `/api/projects/${enc(slug)}/layers/${enc(layerId)}/fields/${enc(field)}/options`),
};

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

/** Panel administratora (wymaga konta z is_admin). */
export const adminApi = {
  users: () => request<AdminUser[]>("/api/admin/users"),
  createUser: (u: UserInput) => request<{ id: number }>("/api/admin/users", json("POST", u)),
  updateUser: (id: number, u: UserInput) => request(`/api/admin/users/${id}`, json("PUT", u)),
  deleteUser: (id: number) => request<void>(`/api/admin/users/${id}`, { method: "DELETE" }),

  groups: () => request<Group[]>("/api/admin/groups"),
  createGroup: (g: Omit<Group, "id">) => request<{ id: number }>("/api/admin/groups", json("POST", g)),
  updateGroup: (id: number, g: Omit<Group, "id">) => request(`/api/admin/groups/${id}`, json("PUT", g)),
  deleteGroup: (id: number) => request<void>(`/api/admin/groups/${id}`, { method: "DELETE" }),

  projects: () => request<AdminProject[]>("/api/admin/projects"),
  projectFiles: () => request<{ file_name: string; registered: boolean }[]>("/api/admin/project-files"),
  createProject: (p: Omit<AdminProject, "id">) => request<{ id: number }>("/api/admin/projects", json("POST", p)),
  updateProject: (id: number, p: Omit<AdminProject, "id">) => request(`/api/admin/projects/${id}`, json("PUT", p)),
  deleteProject: (id: number) => request<void>(`/api/admin/projects/${id}`, { method: "DELETE" }),
  projectAccess: (id: number) => request<ProjectAccess>(`/api/admin/projects/${id}/access`),
  setProjectAccess: (id: number, a: ProjectAccess) => request(`/api/admin/projects/${id}/access`, json("PUT", a)),
  projectScope: (id: number) => request<ProjectScopeInfo>(`/api/admin/projects/${id}/scope`),
  uploads: (minAgeDays: number) => request<UploadsOverview>(`/api/admin/uploads?min_age_days=${minAgeDays}`),
  cleanupUploads: (id: number, minAgeDays: number) =>
    request<{ moved: number; size: number }>(`/api/admin/uploads/${id}/cleanup?min_age_days=${minAgeDays}`, { method: "POST" }),
  purgeTrash: (id: number, olderThanDays: number) =>
    request<{ deleted: number; size: number }>(`/api/admin/uploads/${id}/purge-trash?older_than_days=${olderThanDays}`, { method: "POST" }),

  basemaps: () => request<Basemap[]>("/api/admin/basemaps"),
  createBasemap: (b: BasemapInput) => request<Basemap>("/api/admin/basemaps", json("POST", b)),
  updateBasemap: (id: number, b: BasemapInput) => request<Basemap>(`/api/admin/basemaps/${id}`, json("PUT", b)),
  deleteBasemap: (id: number) => request<void>(`/api/admin/basemaps/${id}`, { method: "DELETE" }),
  capabilities: (src: { url?: string; xml?: string }) =>
    request<WmtsCapabilities>("/api/admin/basemaps/capabilities", json("POST", src)),
};

/** Szablon wydruku QGIS dla panelu: rozmiar mapy, etykiety, czy podkład da się wydrukować. */
export interface ReportInfo {
  layout: string;
  map_mm: [number, number] | null;
  labels: string[];
  title_label: string | null;
  note_label: string | null;
  basemaps: { id: number; name: string; layer: string | null }[];
}

/** Pliki zdjęć i dokumentów w projektach (zakładka „Pliki” panelu). */
export interface UploadsOverview {
  min_age_days: number;
  projects: {
    project_id: number; title: string; slug: string; files: number; size: number;
    orphans: number; orphans_size: number; orphan_paths: string[]; recent: number; missing: number;
    trash_files: number; trash_size: number; error: string | null;
  }[];
  unregistered: { slug: string; files: number; size: number }[];
}

export type UserInput = Omit<AdminUser, "id" | "last_login_at"> & { password?: string };
export type BasemapInput = Omit<Basemap, "id" | "version">;
