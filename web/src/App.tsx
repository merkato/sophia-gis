import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type OlMap from "ol/Map";
import { api, ApiError } from "./api";
import { ensureProjection } from "./projections";
import type { Basemap, FetchResult, GeoJSONFeature, ProjectConfig, ProjectSummary, TreeNode, User } from "./types";
import { MapView, type Tool } from "./components/MapView";
import { LayerTree, initialVisibility, nodeKey, visibleWmsNames } from "./components/LayerTree";
import { FeaturePanel, type FeaturePanelHandle } from "./components/FeaturePanel";
import { AttributeTable } from "./components/AttributeTable";
import { PrintPanel } from "./components/PrintPanel";
import GeoJSON from "ol/format/GeoJSON";
import { Toolbar } from "./components/Toolbar";
import { FetchCard } from "./components/FetchCard";
import { AdminPanel } from "./components/AdminPanel";
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

  const refreshSession = useCallback(async () => {
    setUser(await api.me().catch(() => null));
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
    if (!slug) { setConfig(null); return; }
    history.replaceState(null, "", `?p=${encodeURIComponent(slug)}`);
    setSelection(null);
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
          {projects.length === 0 && <option value="">Brak dostępnych projektów</option>}
          {projects.map((p) => <option key={p.slug} value={p.slug}>{p.title}</option>)}
        </select>
        <div className="spacer" />
        {user ? (
          <>
            <span className="muted">{user.full_name ?? user.login}</span>
            {user.is_admin && <button onClick={() => setShowAdmin(true)}>Administracja</button>}
            <button onClick={async () => { await api.logout(); await refreshSession(); }}>Wyloguj</button>
          </>
        ) : (
          <button className="primary" onClick={() => setShowLogin(true)}>Zaloguj</button>
        )}
      </header>

      <Toolbar config={config} editLayerId={editLayerId} onEditLayer={chooseEditLayer} tool={tool} onTool={chooseTool}
        canDelete={canDelete} onDelete={deleteSelected} onNewRecord={newRecord}
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
              preview={fetchTool ? fetchState.result?.geometry ?? null : null}
              printFrame={showPrint ? printFrame : null}
              opacity={opacity}
              onSelect={(layerId, feature) => guard(() => setSelection({ layerId, feature, isNew: false }))}
              onDrawn={(layerId, geometry) => guard(() =>
                setSelection({ layerId, isNew: true, feature: { type: "Feature", id: "", geometry, properties: {} } }))}
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
          {message && <div className="toast" onClick={() => setMessage(null)}>{message}</div>}
          {config && selection && (
            <FeaturePanel
              ref={panelRef}
              config={config} layerId={selection.layerId} feature={selection.feature} isNew={selection.isNew}
              onSaved={(f) => {
                // po zapisie nowego obiektu: następne kliknięcie wybiera obiekt, nie zaczyna rysowania
                if (selection.isNew && tool === "draw") setTool("select");
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

      {showAdmin && user?.is_admin && (
        <AdminPanel onClose={() => setShowAdmin(false)} onChanged={refreshSession} />
      )}

      {showLogin && !user && (
        <div className="modal" onClick={(e) => e.target === e.currentTarget && setShowLogin(false)}>
          <LoginForm onLogin={async () => { setShowLogin(false); await refreshSession(); }} />
        </div>
      )}
    </div>
  );
}
