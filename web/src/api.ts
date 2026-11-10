import type {
  AdminProject, AdminUser, Attachment, Basemap, GeoJSONFeature, Group, ProjectAccess, ProjectConfig,
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

  features: (slug: string, layerId: string, bbox: number[], crs: string) =>
    request<{ features: GeoJSONFeature[]; truncated: boolean }>(
      `${featuresUrl(slug, layerId)}?bbox=${bbox.join(",")}&crs=${enc(crs)}&limit=5000`),
  feature: (slug: string, layerId: string, pk: string, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}/${enc(pk)}?crs=${enc(crs)}`),
  createFeature: (slug: string, layerId: string, f: Partial<GeoJSONFeature>, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}?crs=${enc(crs)}`,
      { method: "POST", body: JSON.stringify(f) }),
  updateFeature: (slug: string, layerId: string, pk: string, f: Partial<GeoJSONFeature>, crs: string) =>
    request<GeoJSONFeature>(`${featuresUrl(slug, layerId)}/${enc(pk)}?crs=${enc(crs)}`,
      { method: "PATCH", body: JSON.stringify({ type: "Feature", properties: {}, ...f }) }),
  deleteFeature: (slug: string, layerId: string, pk: string) =>
    request<void>(`${featuresUrl(slug, layerId)}/${enc(pk)}`, { method: "DELETE" }),
  related: (slug: string, layerId: string, pk: string, crs: string) =>
    request<RelatedGroup[]>(`${featuresUrl(slug, layerId)}/${enc(pk)}/related?crs=${enc(crs)}`),

  attachments: (slug: string, layerId: string, pk: string) =>
    request<Attachment[]>(`${featuresUrl(slug, layerId)}/${enc(pk)}/attachments`),
  attachmentUrl: (slug: string, layerId: string, pk: string, id: string) =>
    `${featuresUrl(slug, layerId)}/${enc(pk)}/attachments/${id}`,
  uploadAttachment: (slug: string, layerId: string, pk: string, file: File, description?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (description) fd.append("description", description);
    return request<Attachment>(`${featuresUrl(slug, layerId)}/${enc(pk)}/attachments`, { method: "POST", body: fd });
  },
  deleteAttachment: (slug: string, layerId: string, pk: string, id: string) =>
    request<void>(`${featuresUrl(slug, layerId)}/${enc(pk)}/attachments/${id}`, { method: "DELETE" }),

  reportUrl: (slug: string, layout: string, params: Record<string, string>) =>
    `/api/projects/${enc(slug)}/reports/${enc(layout)}?${new URLSearchParams(params)}`,

  basemaps: () => request<Basemap[]>("/api/basemaps"),
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

  basemaps: () => request<Basemap[]>("/api/admin/basemaps"),
  createBasemap: (b: BasemapInput) => request<Basemap>("/api/admin/basemaps", json("POST", b)),
  updateBasemap: (id: number, b: BasemapInput) => request<Basemap>(`/api/admin/basemaps/${id}`, json("PUT", b)),
  deleteBasemap: (id: number) => request<void>(`/api/admin/basemaps/${id}`, { method: "DELETE" }),
  capabilities: (src: { url?: string; xml?: string }) =>
    request<WmtsCapabilities>("/api/admin/basemaps/capabilities", json("POST", src)),
};

export type UserInput = Omit<AdminUser, "id" | "last_login_at"> & { password?: string };
export type BasemapInput = Omit<Basemap, "id" | "version">;
