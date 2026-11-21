import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type OlMap from "ol/Map";
import { api, ApiError } from "./api";
import { ensureProjection } from "./projections";
import type { Basemap, FetchResult, GeoJSONFeature, ProjectConfig, ProjectSummary, TreeNode, User } from "./types";
import { MapView, type PointTool, type Tool } from "./components/MapView";
import { LayerTree, initialVisibility, nodeKey, visibleWmsNames } from "./components/LayerTree";
import { FeaturePanel, type FeaturePanelHandle } from "./components/FeaturePanel";
import { AttributeTable } from "./components/AttributeTable";
import { PrintPanel } from "./components/PrintPanel";
import GeoJSON from "ol/format/GeoJSON";
import { Toolbar } from "./components/Toolbar";
import { FetchCard } from "./components/FetchCard";
import { AdminPanel } from "./components/AdminPanel";
import { setMapFocusHandler, type MapFocus, type PluginInfo } from "./plugins";
import { BasemapSwitcher, initialBasemapChoice, saveBasemapChoice } from "./components/BasemapSwitcher";
import { loadOpacity, saveOpacity, useOpenSliders } from "./components/OpacitySlider";

/**
 * Mapa bez projektu (brak dostępnych projektów, niezalogowany gość): same podkłady z katalogu
 * w EPSG:2180, widok na całą Polskę.
 */
const BASE_CONFIG: ProjectConfig = {
  slug: "", title: "Sophia", role: null, crs: "EPSG:2180", version: 0,
  extent: [170000, 130000, 870000, 780000], options: {},
  tree: { kind: "group", name: "", layer_id: null, visible: true, expanded: true, mutually_exclusive: false, children: [] },
  layers: {}, relations: [], reports: [], tools: [], scope: null, rights: { photos: false, files: false },
};

interface Selection {
  layerId: string;
  feature: GeoJSONFeature;
  isNew: boolean;
  cutFrom?: string;            // pierścień wypełniony: obiekt, w którym zapis wytnie dziurę
}

/** Niezapisane zmiany w formularzu, a użytkownik otwiera inny obiekt / zamyka okno. */
function UnsavedDialog({ onSave, onDiscard, onCancel }: { onSave: () => void; onDiscard: () => void; onCancel: () => void }) {
  return (
    <div className="modal" onClick={(e) => e.target === e.currentTarget && onCancel()}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <div className="dialog" role="alertdialog" aria-labelledby="unsaved-title">
        <h3 id="unsaved-title">Niezapisane zmiany</h3>
        <p>Formularz ma zmiany, które nie zostały zapisane.</p>
        <div className="actions">
          <button className="primary" onClick={onSave} autoFocus>Zapisz</button>
          <button className="danger" onClick={onDiscard}>Odrzuć</button>
          <button onClick={onCancel}>Anuluj</button>
        </div>
      </div>
    </div>
  );
}

function LoginForm({ onLogin }: { onLogin: () => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form className="login" onSubmit={async (e) => {
      e.preventDefault();
      try { await api.login(login, password); onLogin(); } catch (err) { setError((err as Error).message); }
    }}>
      <h2>Logowanie</h2>
      {error && <div className="error">{error}</div>}
      <input placeholder="Login" value={login} onChange={(e) => setLogin(e.target.value)} autoFocus />
      <input placeholder="Hasło" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button className="primary" type="submit">Zaloguj</button>
    </form>
  );
}

/** „obiekt” w liczbie mnogiej: 2–4 obiekty, 5+ obiektów (bez 12–14). */
function objectsWord(n: number): string {
  const t = n % 10, h = n % 100;
  return t >= 2 && t <= 4 && !(h >= 12 && h <= 14) ? "obiekty" : "obiektów";
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [slug, setSlug] = useState<string | null>(() => new URLSearchParams(location.search).get("p"));
  const [config, setConfig] = useState<ProjectConfig | null>(null);
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const [baseReady, setBaseReady] = useState(false);
  useEffect(() => { ensureProjection("EPSG:2180").then(() => setBaseReady(true)).catch(() => setBaseReady(true)); }, []);
  const [showPrint, setShowPrint] = useState(false);
  // krycie rastrów projektu i podkładów (0–100), zapamiętane w przeglądarce
  const [opacity, setOpacity] = useState<Record<string, number>>(loadOpacity);
  const setOpacityKey = (key: string, v: number) => setOpacity((o) => {
    const next = { ...o };
    if (v === 100 && !key.startsWith("bm:")) delete next[key]; else next[key] = v;
    saveOpacity(next);
    return next;
  });
  const treeSliders = useOpenSliders();
  const [printFrame, setPrintFrame] = useState<[number, number] | null>(null);
  const [editLayerId, setEditLayerId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("identify");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [showLogin, setShowLogin] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showAdmin, setShowAdmin] = useState(false);
  const [basemaps, setBasemaps] = useState<Basemap[]>([]);
  const [baseId, setBaseId] = useState<number | null>(null);
  const [overlayIds, setOverlayIds] = useState<Set<number>>(new Set());
  const mapRef = useRef<OlMap | null>(null);
  const panelRef = useRef<FeaturePanelHandle>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => !matchMedia("(max-width: 800px)").matches);
  // narzędzie pobierania (ULDK…): aktywne narzędzie i wynik ostatniego kliknięcia
  const [fetchToolId, setFetchToolId] = useState<string | null>(null);
  const [fetchState, setFetchState] = useState<{ loading: boolean; error: string | null; result: FetchResult | null }>(
    { loading: false, error: null, result: null });
  const fetchSeq = useRef(0);
  const [pending, setPending] = useState<(() => void) | null>(null);
  // obiekt do pokazania po wczytaniu projektu: z adresu (?p=…&obiekt=schemat.tabela:klucz) albo z wtyczki
  const [focus, setFocus] = useState<MapFocus | null>(() => {
    const q = new URLSearchParams(location.search);
    const o = q.get("obiekt");
    const i = o ? o.indexOf(":") : -1;
    return o && i > 0 ? { project: q.get("p") ?? undefined, targets: [{ table: o.slice(0, i), pk: o.slice(i + 1) }] } : null;
  });
  const [focusGeom, setFocusGeom] = useState<GeoJSONFeature["geometry"] | null>(null);

  /**
   * Każda zmiana obiektu w formularzu (kliknięcie na mapie, lista rekordów, powiązane,
   * nowy obiekt, zamknięcie) idzie przez guard: przy niezapisanych zmianach pyta
   * zapisz / odrzuć / anuluj, inaczej od razu podmienia formularz.
   */
  const guard = (action: () => void) => {
    if (panelRef.current?.isDirty()) setPending(() => action);
    else action();
  };

  const resolvePending = async (choice: "save" | "discard" | "cancel") => {
    const action = pending;
    setPending(null);
    if (!action) return;
    if (choice === "save") {
      if (await panelRef.current?.save()) action();   // błąd zapisu widać w formularzu
    } else if (choice === "discard") {
      if (selection?.isNew) setReloadToken((t) => t + 1);   // usuń szkic z mapy
      action();
    } else {
      setReloadToken((t) => t + 1);   // zdejmij zaznaczenie / szkic klikniętego obiektu
    }
  };

  // wtyczki z uprawnieniami zalogowanego (strony w administracji)
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const pluginPages = plugins.some((p) => p.pages.length > 0);

  const refreshSession = useCallback(async () => {
    const me = await api.me().catch(() => null);
    setUser(me);
    setPlugins(me ? await api.plugins().catch(() => []) : []);
    const [list, bms] = await Promise.all([api.projects().catch(() => []), api.basemaps().catch(() => [])]);
    setProjects(list);
    setSlug((s) => (s && list.some((p) => p.slug === s) ? s : list[0]?.slug ?? null));
    setBasemaps(bms);
    const choice = initialBasemapChoice(bms);
    setBaseId(choice.baseId);
    setOverlayIds(choice.overlayIds);
  }, []);

  const chooseBase = (id: number | null) => { setBaseId(id); saveBasemapChoice(id, overlayIds); };
  const toggleOverlay = (id: number) => {
    const next = new Set(overlayIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    setOverlayIds(next);
    saveBasemapChoice(baseId, next);
  };

  useEffect(() => { refreshSession(); }, [refreshSession]);

  useEffect(() => {
    if (!slug) {   // bez projektu: same podkłady z katalogu
      setConfig(null);
      setSelection(null);
      setEditLayerId(null);
      setTool("identify");
      if (location.search) history.replaceState(null, "", location.pathname);
      return;
    }
    history.replaceState(null, "", `?p=${encodeURIComponent(slug)}${location.search.match(/[?&](obiekt=[^&]*)/)?.[0].replace("?", "&") ?? ""}`);
    setSelection(null);
    setFocusGeom(null);
    setEditLayerId(null);
    setTool("identify");
    api.project(slug)
      .then(async (cfg) => {
        await ensureProjection(cfg.crs);
        setConfig(cfg);
        setVisible(initialVisibility(cfg.tree));
      })
      .catch((e) => {
        setConfig(null);
        if (e instanceof ApiError && e.status === 401) setShowLogin(true);
        else setMessage(e.message);
      });
  }, [slug, user?.id]);

  const wmsLayers = useMemo(
    () => (config ? visibleWmsNames(config.tree, visible, (id) => config.layers[id]?.wms_name) : []),
    [config, visible]);

  // mapa bez projektu: same podkłady (projekt jeszcze się wczytuje albo żaden nie jest dostępny)
  const mapConfig = config ?? (baseReady && (!slug || projects.length === 0) ? BASE_CONFIG : null);

  /** Wydruk: aktywne podkłady w kolejności rysowania i nazwy widocznych warstw projektu. */
  const printBasemaps = useMemo(() => basemaps
    .filter((b) => (b.is_overlay ? overlayIds.has(b.id) : b.id === baseId))
    .sort((a, b) => Number(a.is_overlay) - Number(b.is_overlay)), [basemaps, baseId, overlayIds]);
  const printLayerNames = useMemo(() => {
    if (!config) return [];
    return [...wmsLayers].reverse().map((n) => Object.values(config.layers).find((l) => l.wms_name === n)?.name ?? n);
  }, [config, wmsLayers]);

  const editableIds = useMemo(
    () => new Set(Object.values(config?.layers ?? {}).filter((l) => l.perms.insert || l.perms.update || l.perms.delete).map((l) => l.id)),
    [config]);

  const toggle = (node: TreeNode, parent: TreeNode | null) => {
    setVisible((prev) => {
      const next = new Set(prev);
      const key = nodeKey(node);
      if (parent?.mutually_exclusive) parent.children.forEach((c) => next.delete(nodeKey(c)));
      if (prev.has(key) && !parent?.mutually_exclusive) next.delete(key); else next.add(key);
      return next;
    });
  };

  const openFeature = (layerId: string, pk: string, zoom = false) => guard(async () => {
    if (!config) return;
    try {
      const f = await api.feature(config.slug, layerId, pk, config.crs);
      setSelection({ layerId, feature: f, isNew: false });
      if (zoom && f.geometry) zoomTo(f.geometry);
    } catch (e) {
      setMessage((e as Error).message);
    }
  });

  // host.showOnMap wtyczek: zamknij administrację, przełącz projekt, resztę zrobi efekt poniżej
  useEffect(() => {
    setMapFocusHandler((f) => {
      if (f.project && !projects.some((p) => p.slug === f.project)) {
        setMessage(`Brak dostępu do projektu „${f.project}”`);
        return;
      }
      setShowAdmin(false);
      if (f.project && f.project !== slug) setSlug(f.project);
      setFocus({ ...f, project: f.project ?? slug ?? undefined });
    });
    return () => setMapFocusHandler(null);
  }, [projects, slug]);

  useEffect(() => {
    if (!focus || !config || (focus.project && focus.project !== config.slug)) return;
    if (!mapRef.current) {   // mapa jeszcze się montuje — spróbuj za chwilę
      const t = setTimeout(() => setFocus((x) => (x ? { ...x } : x)), 200);
      return () => clearTimeout(t);
    }
    const f = focus;
    const map = mapRef.current;
    setFocus(null);
    const fit = (g: ReturnType<GeoJSON["readGeometry"]>) => {
      if (g) map.getView().fit(g.getExtent(), { padding: [80, 80, 80, 80], maxZoom: 17, duration: 300 });
    };
    const lyr = (f.targets ?? []).map((t) => ({ t, l: Object.values(config.layers).find((l) => l.source_table === t.table && l.primary_key) }))
      .find((x) => x.l);
    if (lyr?.l) {
      const { t, l } = lyr;
      setVisible((prev) => new Set(prev).add(`l:${l.id}`));
      history.replaceState(null, "", `?p=${encodeURIComponent(config.slug)}&obiekt=${encodeURIComponent(`${t.table}:${t.pk}`)}`);
      guard(async () => {
        try {
          const feat = await api.feature(config.slug, l.id, t.pk, config.crs);
          setSelection({ layerId: l.id, feature: feat, isNew: false });
          if (feat.geometry) fit(new GeoJSON().readGeometry(feat.geometry));
        } catch (e) {
          setMessage((e as Error).message);
        }
      });
      return;
    }
    if (f.geometry) {
      const fmt = new GeoJSON();
      const g = fmt.readGeometry(f.geometry, { dataProjection: "EPSG:4326", featureProjection: config.crs });
      if (!g) return;
      fit(g);
      setFocusGeom(fmt.writeGeometryObject(g) as GeoJSONFeature["geometry"]);
      if (f.label) setMessage(f.label);
    } else if (f.targets?.length) {
      setMessage("Obiektu nie ma na żadnej warstwie tego projektu");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, config]);

  /** Przybliżenie mapy do obiektu (wiersz tabeli atrybutów) — bez zmiany skali, gdy obiekt jest widoczny. */
  const zoomTo = (geometry: GeoJSONFeature["geometry"]) => {
    const map = mapRef.current;
    if (!map || !geometry || !config) return;
    const g = new GeoJSON().readGeometry(geometry, { dataProjection: config.crs, featureProjection: config.crs });
    if (!g) return;
    const ext = g.getExtent();
    const view = map.getView();
    const visible = view.calculateExtent(map.getSize());
    const inside = ext[0] >= visible[0] && ext[1] >= visible[1] && ext[2] <= visible[2] && ext[3] <= visible[3];
    if (!inside) view.fit(ext, { padding: [60, 60, 60, 60], maxZoom: Math.max(view.getZoom() ?? 0, 14), duration: 300 });
  };

  // tabela atrybutów (okno na środku ekranu) — jedna naraz
  const [tableLayerId, setTableLayerId] = useState<string | null>(null);
  useEffect(() => { setTableLayerId(null); setShowPrint(false); }, [slug]);
  const tableIds = useMemo(
    () => new Set(Object.values(config?.layers ?? {}).filter((l) => l.primary_key && l.type === "vector").map((l) => l.id)),
    [config]);

  const editLayer = editLayerId ? config?.layers[editLayerId] : null;

  /** Wybór warstwy edycyjnej — z drzewa (ołówek) albo z paska narzędzi. */
  const chooseEditLayer = (id: string | null) => guard(() => {
    setEditLayerId(id);
    // tabela bez geometrii: nic do zaznaczania na mapie — otwieramy jej tabelę atrybutów
    const geom = id ? config?.layers[id]?.geometry_type : null;
    chooseTool(geom ? "select" : "identify");
    if (id && !geom) setTableLayerId(id);
    setSelection(null);
  });

  const newRecord = () => editLayer && guard(() =>
    setSelection({ layerId: editLayer.id, isNew: true, feature: { type: "Feature", id: "", geometry: null, properties: {} } }));

  const fetchTool = tool === "fetch" ? config?.tools?.find((t) => t.id === fetchToolId) ?? null : null;

  const chooseTool = (t: Tool) => {
    setTool(t);
    if (t !== "fetch") setFetchState({ loading: false, error: null, result: null });
  };

  const startFetchTool = (id: string) => {
    if (tool === "fetch" && fetchToolId === id) { chooseTool(editLayerId ? "select" : "identify"); return; }
    setFetchToolId(id);
    setFetchState({ loading: false, error: null, result: null });
    setTool("fetch");
  };

  const fetchAt = async (coordinate: number[]) => {
    if (!config || !fetchTool) return;
    const seq = ++fetchSeq.current;
    setFetchState({ loading: true, error: null, result: null });
    try {
      const result = await api.fetchTool(config.slug, fetchTool.id, coordinate[0], coordinate[1], config.crs);
      if (seq === fetchSeq.current) setFetchState({ loading: false, error: null, result });
    } catch (e) {
      if (seq === fetchSeq.current) setFetchState({ loading: false, error: (e as Error).message, result: null });
    }
  };

  /** Dodanie pobranego obiektu: formularz nowego obiektu z wypełnionymi polami albo od razu zapis. */
  const addFetched = (r: FetchResult) => {
    if (!config) return;
    if (r.open_form) {
      guard(() => {
        setSelection({ layerId: r.layer_id, isNew: true, feature: { type: "Feature", id: "", geometry: r.geometry, properties: { ...r.mapped } } });
        setFetchState({ loading: false, error: null, result: null });
      });
      return;
    }
    api.createFeature(config.slug, r.layer_id, { type: "Feature", geometry: r.geometry, properties: r.mapped }, config.crs)
      .then((f) => {
        setFetchState({ loading: false, error: null, result: null });
        setReloadToken((t) => t + 1);
        setMessage(`Dodano do warstwy ${config.layers[r.layer_id]?.name ?? ""}: #${f.id}${r.key ? ` (${r.key})` : ""}`);
      })
      .catch((e) => setFetchState((s) => ({ ...s, error: (e as Error).message })));
  };

  /**
   * Podział linią: zaznaczony (otwarty w formularzu) obiekt warstwy edycyjnej, a bez zaznaczenia —
   * wszystkie obiekty, które linia dzieli (z potwierdzeniem, gdy więcej niż jeden). Liczy API.
   */
  const splitLine = async (layerId: string, line: GeoJSONFeature["geometry"]) => {
    if (!config) return;
    const name = config.layers[layerId]?.name ?? "";
    const target = selection && selection.layerId === layerId && !selection.isNew ? String(selection.feature.id) : null;
    try {
      let pks = target ? [target] : null;
      if (!pks) {
        pks = (await api.splitFeatures(config.slug, layerId, line, config.crs, { dryRun: true })).pks ?? [];
        if (!pks.length) {
          setMessage("Linia nie dzieli żadnego obiektu — musi przeciąć obiekt na wylot.");
          return;
        }
        if (pks.length > 1 && !confirm(`Linia dzieli ${pks.length} ${objectsWord(pks.length)} warstwy „${name}”. Podzielić wszystkie?`)) return;
      }
      const r = await api.splitFeatures(config.slug, layerId, line, config.crs, { pks });
      const created = r.created ?? [];
      setReloadToken((t) => t + 1);
      setMessage(`Podzielono: ${pks.map((p) => `#${p}`).join(", ")} → nowe: ${created.map((f) => `#${f.id}`).join(", ")}`);
      if (target && r.updated?.[0]) setSelection({ layerId, feature: r.updated[0], isNew: false });
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  /** Otwarty w formularzu (zapisany) obiekt warstwy — cel narzędzi, gdy jest; inaczej wskazuje API. */
  const targetOf = (layerId: string) =>
    selection && selection.layerId === layerId && !selection.isNew ? String(selection.feature.id) : null;

  /** Po zmianie geometrii przez API: odśwież mapę, formularz pokazuje zmieniony obiekt. */
  const afterGeometryEdit = (layerId: string, f: GeoJSONFeature, note: string) => {
    setReloadToken((t) => t + 1);
    setMessage(note);
    if (selection && selection.layerId === layerId && !selection.isNew) setSelection({ layerId, feature: f, isNew: false });
  };

  const ringTool = async (layerId: string, ring: GeoJSONFeature["geometry"], fill: boolean) => {
    if (!config) return;
    try {
      const target = targetOf(layerId);
      if (!fill) {
        const f = await api.addRing(config.slug, layerId, ring, config.crs, { pk: target });
        afterGeometryEdit(layerId, f, `Dodano pierścień w obiekcie #${f.id}.`);
        return;
      }
      // wypełniony: najpierw sprawdzenie, w którym obiekcie leży, potem formularz nowego obiektu
      const { pk } = await api.addRing(config.slug, layerId, ring, config.crs, { pk: target, dryRun: true });
      setSelection({ layerId, isNew: true, cutFrom: pk, feature: { type: "Feature", id: "", geometry: ring, properties: {} } });
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const pointTool = async (layerId: string, t: PointTool, coordinate: number[], tolerance: number) => {
    if (!config) return;
    const op = t === "delring" ? "delete-ring" : "delete-part";
    try {
      const o = { pk: targetOf(layerId) };
      if (t === "delpart") {
        const dry = await api.pointEdit(config.slug, layerId, op, coordinate, tolerance, config.crs, { ...o, dryRun: true });
        if (!confirm(`Usunąć klikniętą część obiektu #${dry.pk} (części: ${dry.parts})?`)) return;
        o.pk = dry.pk ?? o.pk;
      }
      const f = await api.pointEdit(config.slug, layerId, op, coordinate, tolerance, config.crs, o);
      afterGeometryEdit(layerId, f, t === "delring" ? `Usunięto pierścień w obiekcie #${f.id}.` : `Usunięto część obiektu #${f.id}.`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  // Połącz obiekty: zestaw klikniętych obiektów; pierwszy zostaje (klucz, atrybuty, zdjęcia)
  const [mergeSet, setMergeSet] = useState<string[]>([]);
  useEffect(() => { if (tool !== "merge") setMergeSet([]); }, [tool, editLayerId]);
  const mergePick = (pk: string) =>
    setMergeSet((s) => (s.includes(pk) ? s.filter((x) => x !== pk) : [...s, pk]));
  const doMerge = async () => {
    if (!config || !editLayer || mergeSet.length < 2) return;
    const [keep, ...rest] = mergeSet;
    if (!confirm(`Połączyć ${mergeSet.length} ${objectsWord(mergeSet.length)} warstwy „${editLayer.name}”?\n`
      + `Zostanie #${keep} z jego atrybutami. Obiekty ${rest.map((p) => `#${p}`).join(", ")} zostaną usunięte, `
      + "a ich zdjęcia, dokumenty i rekordy powiązane przejdą do #" + keep + ".")) return;
    try {
      const f = await api.mergeFeatures(config.slug, editLayer.id, mergeSet, keep, config.crs);
      setMergeSet([]);
      setReloadToken((t) => t + 1);
      setSelection({ layerId: editLayer.id, feature: f, isNew: false });
      setMessage(`Połączono w obiekt #${f.id}.`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const addPart = async (layerId: string, part: GeoJSONFeature["geometry"]) => {
    if (!config) return;
    const target = targetOf(layerId);
    if (!target) {
      setMessage("Najpierw otwórz obiekt (Zaznacz obiekt), do którego dodajesz część.");
      setReloadToken((t) => t + 1);
      return;
    }
    try {
      const f = await api.addPart(config.slug, layerId, target, part, config.crs);
      afterGeometryEdit(layerId, f, `Dodano część do obiektu #${f.id}.`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const reshape = async (layerId: string, line: GeoJSONFeature["geometry"]) => {
    if (!config) return;
    try {
      const f = await api.reshape(config.slug, layerId, line, config.crs, targetOf(layerId));
      afterGeometryEdit(layerId, f, `Przekształcono obiekt #${f.id}.`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const copyFeature = async (layerId: string, pk: string, geometry: GeoJSONFeature["geometry"]) => {
    if (!config) return;
    try {
      const f = await api.copyFeature(config.slug, layerId, pk, geometry, config.crs);
      setReloadToken((t) => t + 1);
      setSelection({ layerId, feature: f, isNew: false });
      setMessage(`Skopiowano #${pk} jako #${f.id} — uzupełnij atrybuty w formularzu.`);
    } catch (e) {
      setMessage((e as Error).message);
      setReloadToken((t) => t + 1);
    }
  };

  /** Cofnij ostatnią własną operację edycji (z dziennika zmian), po potwierdzeniu. */
  const undoLast = async () => {
    if (!config?.slug || !user) return;
    try {
      const last = await api.lastOperation(config.slug);
      if (!last) {
        setMessage("Brak operacji do cofnięcia.");
        return;
      }
      const time = new Date(last.at).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
      if (!confirm(`Cofnąć ostatnią operację (${time})?\n${last.items.map((i) => `• ${i.label}`).join("\n")}`)) return;
      await api.undo(config.slug, last.op);
      setReloadToken((t) => t + 1);
      if (selection && last.items.some((i) => i.layer_id === selection.layerId && i.pk === String(selection.feature.id))) {
        setSelection(null);
      }
      setMessage(`Cofnięto: ${last.items.map((i) => i.label).join(", ")}.`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };
  const undoRef = useRef<() => void>(() => {});
  undoRef.current = () => guard(() => { void undoLast(); });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undoRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const canDelete = !!(selection && editLayer && selection.layerId === editLayer.id && !selection.isNew && editLayer.perms.delete);
  const deleteSelected = async () => {
    if (!config || !selection || !canDelete) return;
    if (!confirm(`Usunąć obiekt #${selection.feature.id} z warstwy „${editLayer!.name}”? Tej operacji nie można cofnąć.`)) return;
    try {
      await api.deleteFeature(config.slug, selection.layerId, String(selection.feature.id));
      setSelection(null);
      setReloadToken((t) => t + 1);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand">Sophia</strong>
        <select value={slug ?? ""} onChange={(e) => setSlug(e.target.value || null)} aria-label="Projekt">
          <option value="">{projects.length === 0 ? "Brak dostępnych projektów" : "— bez projektu (same podkłady) —"}</option>
          {projects.map((p) => <option key={p.slug} value={p.slug}>{p.title}</option>)}
        </select>
        <div className="spacer" />
        {user ? (
          <>
            <span className="muted">{user.full_name ?? user.login}</span>
            {(user.is_admin || pluginPages) && <button onClick={() => setShowAdmin(true)}>Administracja</button>}
            <button onClick={async () => { await api.logout(); await refreshSession(); }}>Wyloguj</button>
          </>
        ) : (
          <button className="primary" onClick={() => setShowLogin(true)}>Zaloguj</button>
        )}
      </header>

      <Toolbar config={config} editLayerId={editLayerId} onEditLayer={chooseEditLayer} tool={tool} onTool={chooseTool}
        canDelete={canDelete} onDelete={deleteSelected} onNewRecord={newRecord}
        onUndo={user ? () => undoRef.current() : null}
        sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen((o) => !o)}
        fetchToolId={fetchToolId} onFetchTool={startFetchTool}
        onOpenTable={() => editLayerId && setTableLayerId(editLayerId)}
        onPrint={mapConfig ? () => setShowPrint(true) : null} />

      <div className="body">
        {sidebarOpen && <aside className="sidebar">
          {config ? (
            <>
              <h3>Warstwy</h3>
              <LayerTree tree={config.tree} visible={visible} onToggle={toggle}
                editableIds={editableIds} editLayerId={editLayerId}
                onEditLayer={chooseEditLayer} tableIds={tableIds} onOpenTable={setTableLayerId}
                rasterKey={(n) => {
                  const wms = n.kind === "raster_group" ? n.name
                    : n.kind === "layer" && n.layer_id && config.layers[n.layer_id]?.type === "raster" ? config.layers[n.layer_id].wms_name : null;
                  return wms ? `${config.slug}/${wms}` : null;
                }}
                opacityOf={(k) => opacity[k] ?? 100} onOpacity={setOpacityKey} sliders={treeSliders} />


            </>
          ) : <p className="muted">{projects.length ? "Wybierz projekt z menu." : user
            ? "Nie masz dostępu do żadnego projektu — poproś administratora o nadanie uprawnień."
            : "Mapa podkładów. Zaloguj się, aby zobaczyć projekty."}</p>}
          <BasemapSwitcher basemaps={basemaps} baseId={baseId} overlayIds={overlayIds}
            onBase={chooseBase} onToggleOverlay={toggleOverlay}
            opacityOf={(b) => opacity[`bm:${b.id}`] ?? Math.round(b.opacity * 100)}
            onOpacity={(b, v) => setOpacityKey(`bm:${b.id}`, v)} />
        </aside>}

        <main className="mapwrap">
          {mapConfig && (
            <MapView
              config={mapConfig} wmsLayers={config ? wmsLayers : []} editLayerId={config ? editLayerId : null} tool={tool}
              reloadToken={reloadToken} mapRef={mapRef}
              basemaps={basemaps} baseId={baseId} overlayIds={overlayIds}
              onIdentify={openFeature}
              onFetchClick={fetchAt}
              preview={fetchTool ? fetchState.result?.geometry ?? null : selection?.cutFrom ? selection.feature.geometry : focusGeom}
              printFrame={showPrint ? printFrame : null}
              opacity={opacity}
              onSelect={(layerId, feature) => guard(() => setSelection({ layerId, feature, isNew: false }))}
              onDrawn={(layerId, geometry) => guard(() =>
                setSelection({ layerId, isNew: true, feature: { type: "Feature", id: "", geometry, properties: {} } }))}
              onSplitLine={(layerId, line) => guard(() => { void splitLine(layerId, line); })}
              onRing={(layerId, ring, fill) => guard(() => { void ringTool(layerId, ring, fill); })}
              onPointTool={(layerId, t, c, tol) => guard(() => { void pointTool(layerId, t, c, tol); })}
              onMergePick={(_, pk) => mergePick(pk)}
              onAddPart={(layerId, part) => guard(() => { void addPart(layerId, part); })}
              onReshape={(layerId, line) => guard(() => { void reshape(layerId, line); })}
              onCopy={(layerId, pk, g) => guard(() => { void copyFeature(layerId, pk, g); })}
              marked={mergeSet}
              onGeometryModified={async (layerId, pk, geometry) => {
                if (!config) return;
                try {
                  await api.updateFeature(config.slug, layerId, pk, { geometry }, config.crs);
                  setReloadToken((t) => t + 1);
                } catch (e) {
                  setMessage((e as Error).message);
                  setReloadToken((t) => t + 1);   // przywróć geometrię z bazy
                }
              }}
            />
          )}
          {config && tableLayerId && config.layers[tableLayerId] && (
            <AttributeTable config={config} layerId={tableLayerId} reloadToken={reloadToken}
              selectedId={selection && selection.layerId === tableLayerId && !selection.isNew ? String(selection.feature.id) : null}
              onOpen={(pk) => openFeature(tableLayerId, pk, !!config.layers[tableLayerId].geometry_type)}
              onNew={!config.layers[tableLayerId].geometry_type && config.layers[tableLayerId].perms.insert
                ? () => guard(() => setSelection({ layerId: tableLayerId, isNew: true, feature: { type: "Feature", id: "", geometry: null, properties: {} } }))
                : null}
              onClose={() => setTableLayerId(null)} />
          )}
          {config && fetchTool && (
            <FetchCard config={config} tool={fetchTool} state={fetchState} onAdd={addFetched}
              onOpenExisting={(r) => openFeature(r.layer_id, r.existing_pk!)}
              onClose={() => chooseTool(editLayerId ? "select" : "identify")} />
          )}
          {showPrint && mapConfig && (
            <PrintPanel config={mapConfig} basemaps={printBasemaps} wmsLayers={config ? wmsLayers : []}
              layerNames={printLayerNames} opacity={opacity} onFrame={setPrintFrame} onClose={() => setShowPrint(false)}
              getView={() => {
                const map = mapRef.current;
                if (!map) return null;
                const view = map.getView();
                return { extent: view.calculateExtent(map.getSize()), center: view.getCenter() ?? [0, 0] };
              }} />
          )}
          {tool === "merge" && editLayer && (
            <div className="merge-bar" role="status">
              {mergeSet.length === 0 ? "Kliknij obiekty do połączenia — pierwszy kliknięty zostaje (atrybuty, zdjęcia)."
                : <>Do połączenia: {mergeSet.map((p, i) => <b key={p}>#{p}{i === 0 ? " (zostaje)" : ""}{i < mergeSet.length - 1 ? ", " : ""}</b>)}</>}
              <button className="primary" disabled={mergeSet.length < 2} onClick={doMerge}>Połącz</button>
              <button disabled={!mergeSet.length} onClick={() => setMergeSet([])}>Wyczyść</button>
            </div>
          )}
          {message && <div className="toast" onClick={() => setMessage(null)}>{message}</div>}
          {config && selection && (
            <FeaturePanel
              ref={panelRef}
              config={config} layerId={selection.layerId} feature={selection.feature} isNew={selection.isNew}
              cutFrom={selection.cutFrom}
              onSaved={(f) => {
                // po zapisie nowego obiektu: następne kliknięcie wybiera obiekt, nie zaczyna rysowania
                if (selection.isNew && tool === "draw") setTool("select");
                if (selection.cutFrom) setMessage(`Dodano obiekt #${f.id} i wycięto go z #${selection.cutFrom}.`);
                setSelection({ layerId: selection.layerId, feature: f, isNew: false });
                setReloadToken((t) => t + 1);
              }}
              onDeleted={() => { setSelection(null); setReloadToken((t) => t + 1); }}
              onClose={() => guard(() => { if (selection.isNew) setReloadToken((t) => t + 1); setSelection(null); })}
              onOpenRelated={openFeature}
            />
          )}
        </main>
      </div>

      {pending && (
        <UnsavedDialog onSave={() => resolvePending("save")} onDiscard={() => resolvePending("discard")}
          onCancel={() => resolvePending("cancel")} />
      )}

      {showAdmin && user && (user.is_admin || pluginPages) && (
        <AdminPanel onClose={() => setShowAdmin(false)} onChanged={refreshSession} user={user} plugins={plugins}
          notify={setMessage} />
      )}

      {showLogin && !user && (
        <div className="modal" onClick={(e) => e.target === e.currentTarget && setShowLogin(false)}>
          <LoginForm onLogin={async () => { setShowLogin(false); await refreshSession(); }} />
        </div>
      )}
    </div>
  );
}
