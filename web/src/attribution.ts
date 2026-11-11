// Atrybucje warstw projektu (QGIS: Właściwości warstwy → QGIS Server → Atrybucja, albo Metadane → Prawa).
// Na mapie: kontrolka atrybucji OpenLayers (HTML z linkiem); na wydruku: zwykły tekst w „Źródła”.
import type { ProjectConfig, TreeNode } from "./types";

export interface Attribution { text: string; url: string | null }

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** Atrybucje warstw o podanych nazwach WMS (warstwy i grupy rastrów — z warstw w grupie), bez powtórzeń. */
export function projectAttributions(config: ProjectConfig, wmsNames: string[]): Attribution[] {
  const byName = new Map(Object.values(config.layers).map((l) => [l.wms_name, l]));
  const groups = new Map<string, TreeNode>();
  const walk = (n: TreeNode) => {
    if (n.kind === "raster_group") groups.set(n.name, n);
    n.children.forEach(walk);
  };
  if (config.tree) walk(config.tree);

  const out = new Map<string, Attribution>();
  const add = (layerId: string | null | undefined) => {
    const l = layerId ? config.layers[layerId] : undefined;
    if (l?.attribution && !out.has(l.attribution)) out.set(l.attribution, { text: l.attribution, url: l.attribution_url });
  };
  const addNode = (n: TreeNode) => { add(n.layer_id); n.children.forEach(addNode); };
  for (const name of wmsNames) {
    const g = groups.get(name);
    if (g) addNode(g);
    else add(byName.get(name)?.id);
  }
  return [...out.values()];
}

/** HTML dla kontrolki atrybucji OpenLayers. */
export function attributionHtml(a: Attribution[]): string[] {
  return a.map((x) => x.url
    ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.text)}</a>` : esc(x.text));
}
