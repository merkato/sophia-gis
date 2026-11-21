import { Component, useCallback, useEffect, useState, type ReactNode } from "react";
import { adminApi, type AdminPlugin, type PluginAccessEntry } from "../api";
import { loadPlugin, type PluginInfo, type PluginPage, type SophiaHost } from "../plugins";
import type { AdminProject, AdminUser, Group, User } from "../types";

type Run = (fn: () => Promise<unknown>) => Promise<boolean>;

/**
 * Panel administratora → Wtyczki: zainstalowane wtyczki (wersja, zależności, migracje, błędy),
 * włącz/wyłącz, a dla każdego uprawnienia wtyczki — grupy i pojedynczy użytkownicy.
 * Instalacja jest krokiem administratora serwera (scripts/server/plugin.sh), nie tego panelu.
 */
export function PluginsTab({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const [list, setList] = useState<AdminPlugin[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [edit, setEdit] = useState<{ id: string; access: PluginAccessEntry[] } | null>(null);
  const [cfg, setCfg] = useState<{ id: string; values: Record<string, string> } | null>(null);
  const [projects, setProjects] = useState<AdminProject[]>([]);

  const load = useCallback(() => run(async () => {
    const [p, g, u, pr] = await Promise.all([adminApi.plugins(), adminApi.groups(), adminApi.users(), adminApi.projects()]);
    setList(p); setGroups(g); setUsers(u); setProjects(pr);
  }), [run]);
  useEffect(() => { load(); }, [load]);

  const toggle = async (p: AdminPlugin) => {
    if (await run(() => adminApi.updatePlugin(p.id, { enabled: !p.enabled }))) { load(); onChanged(); }
  };
  const saveAccess = async () => {
    if (!edit) return;
    if (await run(() => adminApi.setPluginAccess(edit.id, edit.access))) { setEdit(null); load(); onChanged(); }
  };

  const saveSettings = async () => {
    const p = cfg && list.find((x) => x.id === cfg.id);
    if (!p || !cfg) return;
    const settings = { ...p.settings, ...Object.fromEntries(Object.entries(cfg.values).map(([k, v]) => [k, v.trim() || null])) };
    if (await run(() => adminApi.updatePlugin(p.id, { enabled: p.enabled, settings }))) { setCfg(null); load(); onChanged(); }
  };

  const has = (cap: string, k: "group_id" | "user_id", id: number) =>
    !!edit?.access.some((a) => a.capability === cap && a[k] === id);
  const flip = (cap: string, k: "group_id" | "user_id", id: number) => setEdit((e) => e && ({
    ...e,
    access: has(cap, k, id) ? e.access.filter((a) => !(a.capability === cap && a[k] === id))
      : [...e.access, { capability: cap, [k]: id } as PluginAccessEntry],
  }));

  if (!list.length) {
    return <p className="muted">Brak zainstalowanych wtyczek. Instalacja: <code>scripts/server/plugin.sh install …</code> na
      serwerze, potem restart API (docs/WTYCZKI.md).</p>;
  }
  return (
    <div className="plugins">
      <table className="grid">
        <thead><tr><th>Wtyczka</th><th>Wersja</th><th>Stan</th><th>Uprawnienia</th><th /></tr></thead>
        <tbody>
          {list.map((p) => (
            <tr key={p.id} className={edit?.id === p.id ? "selected" : ""}>
              <td><b>{p.name}</b> <code>{p.id}</code>
                {p.description && <div className="muted">{p.description}</div>}
                {Object.keys(p.requires).length > 0 && <div className="muted">Wymaga: {Object.entries(p.requires).map(([d, v]) => `${d} ${v}`).join(", ")}</div>}
                {p.error && <div className="error">{p.error}</div>}
                {p.migrations.pending.length > 0 && <div className="muted">Migracje do wykonania przy włączeniu: {p.migrations.pending.join(", ")}</div>}
              </td>
              <td>{p.version}</td>
              <td>{p.enabled ? "włączona" : "wyłączona"}</td>
              <td>{p.capabilities.map((c) => {
                const who = p.access.filter((a) => a.capability === c.id).map((a) => a.group_name ?? a.login);
                return <div key={c.id}><span title={c.id}>{c.title ?? c.id}</span>: {who.length ? who.join(", ") : <span className="muted">tylko administrator</span>}</div>;
              })}</td>
              <td className="actions">
                <button disabled={!!p.error && !p.enabled} onClick={() => toggle(p)}>{p.enabled ? "Wyłącz" : "Włącz"}</button>
                {p.capabilities.length > 0 && <button onClick={() => { setCfg(null); setEdit({ id: p.id, access: p.access.map(({ capability, group_id, user_id }) => ({ capability, group_id, user_id })) }); }}>Uprawnienia</button>}
                {p.settings_schema.length > 0 && <button onClick={() => { setEdit(null); setCfg({ id: p.id, values: Object.fromEntries(p.settings_schema.map((f) => [f.id, String(p.settings[f.id] ?? "")])) }); }}>Ustawienia</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {cfg && (() => {
        const p = list.find((x) => x.id === cfg.id)!;
        const set = (k: string, v: string) => setCfg((c) => c && { ...c, values: { ...c.values, [k]: v } });
        return (
          <div className="form plugin-access">
            <h3>Ustawienia: {p.name}</h3>
            {p.settings_schema.map((f) => (
              <label key={f.id} className="field"><span>{f.title ?? f.id}</span>
                {f.type === "project"
                  ? <select value={cfg.values[f.id] ?? ""} onChange={(e) => set(f.id, e.target.value)}>
                      <option value="">— brak —</option>
                      {projects.map((pr) => <option key={pr.slug} value={pr.slug}>{pr.title} ({pr.slug})</option>)}
                    </select>
                  : <input value={cfg.values[f.id] ?? ""} onChange={(e) => set(f.id, e.target.value)} />}
                {f.description && <small className="muted">{f.description}</small>}
              </label>
            ))}
            <div className="actions"><button className="primary" onClick={saveSettings}>Zapisz</button><button onClick={() => setCfg(null)}>Anuluj</button></div>
          </div>
        );
      })()}
      {edit && (() => {
        const p = list.find((x) => x.id === edit.id)!;
        return (
          <div className="form plugin-access">
            <h3>Uprawnienia: {p.name}</h3>
            <p className="muted">Kto widzi funkcje wtyczki. Administrator ma zawsze wszystkie.</p>
            {p.capabilities.map((c) => (
              <fieldset key={c.id}>
                <legend>{c.title ?? c.id} <code>{c.id}</code></legend>
                <div className="checks"><span className="muted">Grupy:</span>
                  {groups.map((g) => <label key={g.id}><input type="checkbox" checked={has(c.id, "group_id", g.id)} onChange={() => flip(c.id, "group_id", g.id)} /> {g.name}</label>)}
                </div>
                <div className="checks"><span className="muted">Użytkownicy:</span>
                  {users.filter((u) => !u.is_admin).map((u) => <label key={u.id}><input type="checkbox" checked={has(c.id, "user_id", u.id)} onChange={() => flip(c.id, "user_id", u.id)} /> {u.full_name || u.login}</label>)}
                </div>
              </fieldset>
            ))}
            <div className="actions"><button className="primary" onClick={saveAccess}>Zapisz</button><button onClick={() => setEdit(null)}>Anuluj</button></div>
          </div>
        );
      })()}
    </div>
  );
}

/** Strona wtyczki w panelu administracji (moduł ES wtyczki, z izolacją błędów). */
export function PluginPageView({ plugin, page, user, notify }: { plugin: PluginInfo; page: PluginPage; user: User; notify: (m: string) => void }) {
  const [loaded, setLoaded] = useState<{ C: React.ComponentType<{ host: SophiaHost }>; host: SophiaHost } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setLoaded(null); setError(null);
    loadPlugin(plugin, user, notify)
      .then(({ pages, host }) => {
        if (!alive) return;
        const C = pages[page.id];
        if (C) setLoaded({ C, host }); else setError(`Wtyczka nie ma strony „${page.id}”`);
      })
      .catch((e) => alive && setError(`Nie udało się wczytać wtyczki: ${(e as Error).message}`));
    return () => { alive = false; };
  }, [plugin.id, plugin.version, page.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className="error">{error}</div>;
  if (!loaded) return <p className="muted">Wczytywanie wtyczki…</p>;
  return <PluginBoundary name={plugin.name}><loaded.C host={loaded.host} /></PluginBoundary>;
}

class PluginBoundary extends Component<{ name: string; children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: Error) { return { error: e.message }; }
  render() {
    return this.state.error ? <div className="error">Błąd wtyczki „{this.props.name}”: {this.state.error}</div> : this.props.children;
  }
}
