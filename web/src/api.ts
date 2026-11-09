import type {
  Attachment, GeoJSONFeature, ProjectConfig, ProjectSummary, RelatedGroup, User,
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
};
