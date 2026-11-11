import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type OlMap from "ol/Map";
import { api, ApiError } from "./api";
import { ensureProjection } from "./projections";
import type { Basemap, GeoJSONFeature, ProjectConfig, ProjectSummary, TreeNode, User } from "./types";
import { MapView, type Tool } from "./components/MapView";
import { LayerTree, initialVisibility, nodeKey, visibleWmsNames } from "./components/LayerTree";
import { FeaturePanel, type FeaturePanelHandle } from "./components/FeaturePanel";
import { RecordList } from "./components/RecordList";
import { AdminPanel } from "./components/AdminPanel";
import { BasemapSwitcher, initialBasemapChoice, saveBasemapChoice } from "./components/BasemapSwitcher";

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

  const openFeature = (layerId: string, pk: string) => guard(async () => {
    if (!config) return;
    try {
      const f = await api.feature(config.slug, layerId, pk, config.crs);
      setSelection({ layerId, feature: f, isNew: false });
    } catch (e) {
      setMessage((e as Error).message);
    }
  });

  const editLayer = editLayerId ? config?.layers[editLayerId] : null;

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

      <div className="body">
        <aside className="sidebar">
          <BasemapSwitcher basemaps={basemaps} baseId={baseId} overlayIds={overlayIds}
            onBase={chooseBase} onToggleOverlay={toggleOverlay} />
          {config ? (
            <>
              <h3>Warstwy</h3>
              <LayerTree tree={config.tree} visible={visible} onToggle={toggle}
                editableIds={editableIds} editLayerId={editLayerId}
                onEditLayer={(id) => guard(() => {
                  setEditLayerId(id);
                  // tabela bez geometrii: nic do zaznaczania na mapie — lista rekordów w panelu
                  setTool(id && config.layers[id]?.geometry_type ? "select" : "identify");
                  setSelection(null);
                })} />

              {editLayer && (
                <section className="edit-tools">
                  <h3>Edycja: {editLayer.name}</h3>
                  {!editLayer.geometry_type ? (
                    <RecordList config={config} layer={editLayer} reloadToken={reloadToken}
                      selectedId={selection && selection.layerId === editLayer.id && !selection.isNew ? String(selection.feature.id) : null}
                      onOpen={(pk) => openFeature(editLayer.id, pk)}
                      onNew={() => guard(() => setSelection({ layerId: editLayer.id, isNew: true, feature: { type: "Feature", id: "", geometry: null, properties: {} } }))} />
                  ) : (
                  <div className="toolgroup">
                    <button className={tool === "select" ? "active" : ""} onClick={() => setTool("select")}>Wybierz</button>
                    {editLayer.perms.insert && editLayer.geometry_type && (
                      <button className={tool === "draw" ? "active" : ""} onClick={() => setTool("draw")}>
                        Rysuj {({ Point: "punkt", Line: "linię", Polygon: "poligon" })[editLayer.geometry_type]}
                      </button>
                    )}
                    {editLayer.perms.update && editLayer.geometry_type && (
                      <button className={tool === "modify" ? "active" : ""} onClick={() => setTool("modify")}>Zmień geometrię</button>
                    )}
                  </div>
                  )}
                </section>
              )}

              {config.reports.some((r) => !r.layer_id) && (
                <section>
                  <h3>Wydruki</h3>
                  {config.reports.filter((r) => !r.layer_id).map((r) => (
                    <button key={r.layout} className="block" onClick={() => {
                      const map = mapRef.current;
                      if (!map) return;
                      const extent = map.getView().calculateExtent(map.getSize());
                      window.open(api.reportUrl(config.slug, r.layout, {
                        extent: extent.join(","), layers: [...wmsLayers].reverse().join(","),
                      }), "_blank");
                    }}>🖨 {r.title}</button>
                  ))}
                </section>
              )}
            </>
          ) : <p className="muted">Wybierz projekt z menu.</p>}
        </aside>

        <main className="mapwrap">
          {config && (
            <MapView
              config={config} wmsLayers={wmsLayers} editLayerId={editLayerId} tool={tool}
              reloadToken={reloadToken} mapRef={mapRef}
              basemaps={basemaps} baseId={baseId} overlayIds={overlayIds}
              onIdentify={openFeature}
              onSelect={(layerId, feature) => guard(() => setSelection({ layerId, feature, isNew: false }))}
              onDrawn={(layerId, geometry) => guard(() =>
                setSelection({ layerId, isNew: true, feature: { type: "Feature", id: "", geometry, properties: {} } }))}
              onGeometryModified={async (layerId, pk, geometry) => {
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
