import { useCallback, useEffect, useState } from "react";
import { adminApi, type UserInput } from "../api";
import type { AdminProject, AdminUser, Basemap, Group, ProjectAccess } from "../types";
import { AccessEditor } from "./AccessEditor";
import { UploadsTab } from "./UploadsTab";
import { BasemapEditor } from "./BasemapEditor";

type Tab = "users" | "groups" | "projects" | "basemaps" | "uploads";
const TABS: [Tab, string][] = [["users", "Użytkownicy"], ["groups", "Grupy"], ["projects", "Projekty"], ["basemaps", "Podkłady"], ["uploads", "Pliki"]];

/** Panel administratora: pełnoekranowa nakładka nad mapą. onChanged = odśwież menu projektów/podkłady. */
export function AdminPanel({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<Tab>("users");
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); return true; } catch (e) { setError((e as Error).message); return false; }
  }, []);

  return (
    <div className="admin">
      <header className="admin-head">
        <h2>Administracja</h2>
        <nav className="tabs">
          {TABS.map(([t, label]) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => { setTab(t); setError(null); }}>{label}</button>
          ))}
        </nav>
        <div className="spacer" />
        <button onClick={onClose}>Zamknij</button>
      </header>
      {error && <div className="error" onClick={() => setError(null)}>{error}</div>}
      <div className="admin-body">
        {tab === "users" && <UsersTab run={run} />}
        {tab === "groups" && <GroupsTab run={run} />}
        {tab === "projects" && <ProjectsTab run={run} onChanged={onChanged} />}
        {tab === "basemaps" && <BasemapsTab run={run} onChanged={onChanged} />}
        {tab === "uploads" && <UploadsTab run={run} />}
      </div>
    </div>
  );
}

type Run = (fn: () => Promise<unknown>) => Promise<boolean>;

function randomPassword(): string {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

// ------------------------------------------------------------------------------ użytkownicy

const emptyUser: UserInput = { login: "", full_name: "", email: "", is_admin: false, is_active: true, can_publish: false, group_ids: [], password: "" };

function UsersTab({ run }: { run: Run }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [edit, setEdit] = useState<{ id: number | null; data: UserInput } | null>(null);
  const [shownPassword, setShownPassword] = useState<string | null>(null);

  const load = useCallback(() => run(async () => {
    const [u, g] = await Promise.all([adminApi.users(), adminApi.groups()]);
    setUsers(u); setGroups(g);
  }), [run]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!edit) return;
    const data = { ...edit.data, password: edit.data.password || undefined };
    const ok = await run(() => (edit.id === null ? adminApi.createUser(data) : adminApi.updateUser(edit.id, data)));
    if (ok) {
      setShownPassword(edit.data.password ? `${edit.data.login}: ${edit.data.password}` : null);
      setEdit(null);
      load();
    }
  };

  const groupName = (id: number) => groups.find((g) => g.id === id)?.name ?? `#${id}`;
  const set = (patch: Partial<UserInput>) => setEdit((e) => (e ? { ...e, data: { ...e.data, ...patch } } : e));

  return (
    <div className="admin-split">
      <section>
        <div className="admin-actions">
          <button className="primary" onClick={() => { setShownPassword(null); setEdit({ id: null, data: { ...emptyUser, password: randomPassword() } }); }}>+ Nowy użytkownik</button>
        </div>
        {shownPassword && (
          <div className="notice">Hasło do przekazania użytkownikowi (nie będzie pokazane ponownie): <code>{shownPassword}</code></div>
        )}
        <table className="grid">
          <thead><tr><th>Login</th><th>Imię i nazwisko</th><th>Grupy</th><th>Rola</th><th>Ostatnie logowanie</th><th /></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                <td>{u.login}</td>
                <td>{u.full_name}</td>
                <td>{u.group_ids.map(groupName).join(", ")}</td>
                <td>{u.is_admin ? "administrator" : !u.is_active ? "zablokowany" : u.can_publish ? "autor projektów" : "użytkownik"}</td>
                <td className="muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}</td>
                <td className="row-actions">
                  <button onClick={() => { setShownPassword(null); setEdit({ id: u.id, data: { login: u.login, full_name: u.full_name ?? "", email: u.email ?? "", is_admin: u.is_admin, is_active: u.is_active, can_publish: u.can_publish, group_ids: u.group_ids, password: "" } }); }}>Edytuj</button>
                  <button className="danger" onClick={() => confirm(`Usunąć konto ${u.login}?`) && run(adminApi.deleteUser.bind(null, u.id)).then(load)}>Usuń</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {edit && (
        <section className="admin-form form">
          <h3>{edit.id === null ? "Nowy użytkownik" : `Edycja: ${edit.data.login}`}</h3>
          <label className="field"><span>Login</span>
            <input value={edit.data.login} onChange={(e) => set({ login: e.target.value })} autoFocus /></label>
          <label className="field"><span>Imię i nazwisko</span>
            <input value={edit.data.full_name ?? ""} onChange={(e) => set({ full_name: e.target.value })} /></label>
          <label className="field"><span>E-mail</span>
            <input type="email" value={edit.data.email ?? ""} onChange={(e) => set({ email: e.target.value })} /></label>
          <label className="field"><span>{edit.id === null ? "Hasło" : "Nowe hasło (puste = bez zmian)"}</span>
            <span className="inline">
              <input value={edit.data.password ?? ""} onChange={(e) => set({ password: e.target.value })} autoComplete="new-password" />
              <button type="button" onClick={() => set({ password: randomPassword() })}>Generuj</button>
            </span></label>
          <fieldset>
            <legend>Grupy</legend>
            {groups.length === 0 && <p className="muted">Brak grup — utwórz je w zakładce Grupy.</p>}
            {groups.map((g) => (
              <label key={g.id} className="check">
                <input type="checkbox" checked={edit.data.group_ids.includes(g.id)}
                  onChange={(e) => set({ group_ids: e.target.checked ? [...edit.data.group_ids, g.id] : edit.data.group_ids.filter((i) => i !== g.id) })} />
                {g.name}
              </label>
            ))}
          </fieldset>
          <label className="check"><input type="checkbox" checked={edit.data.is_active} onChange={(e) => set({ is_active: e.target.checked })} /> Konto aktywne</label>
          <label className="check"><input type="checkbox" checked={edit.data.is_admin} onChange={(e) => set({ is_admin: e.target.checked })} /> Administrator (pełny dostęp)</label>
          <label className="check" title="Publikacja projektów z QGIS (Fia) bez pełnych praw administratora; autor zarządza swoimi projektami">
            <input type="checkbox" checked={edit.data.can_publish || edit.data.is_admin} disabled={edit.data.is_admin}
              onChange={(e) => set({ can_publish: e.target.checked })} /> Autor projektów (publikacja z QGIS)</label>
          <div className="actions">
            <button className="primary" onClick={save} disabled={!edit.data.login || (edit.id === null && !edit.data.password)}>Zapisz</button>
            <button onClick={() => setEdit(null)}>Anuluj</button>
          </div>
        </section>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------ grupy

function GroupsTab({ run }: { run: Run }) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const load = useCallback(() => run(async () => setGroups(await adminApi.groups())), [run]);
  useEffect(() => { load(); }, [load]);

  return (
    <section className="narrow">
      <p className="muted">Grupy nadają dostęp do projektów (zakładka Projekty) i łączą użytkowników.</p>
      <table className="grid">
        <thead><tr><th>Nazwa</th><th>Opis</th><th /></tr></thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.id}>
              <td><input defaultValue={g.name} onBlur={(e) => e.target.value !== g.name && run(() => adminApi.updateGroup(g.id, { name: e.target.value, description: g.description })).then(load)} /></td>
              <td><input defaultValue={g.description ?? ""} onBlur={(e) => e.target.value !== (g.description ?? "") && run(() => adminApi.updateGroup(g.id, { name: g.name, description: e.target.value || null })).then(load)} /></td>
              <td className="row-actions"><button className="danger" onClick={() => confirm(`Usunąć grupę ${g.name}?`) && run(() => adminApi.deleteGroup(g.id)).then(load)}>Usuń</button></td>
            </tr>
          ))}
          <tr>
            <td><input placeholder="Nowa grupa" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></td>
            <td><input placeholder="Opis" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></td>
            <td><button className="primary" disabled={!draft.name} onClick={() => run(() => adminApi.createGroup({ name: draft.name, description: draft.description || null })).then((ok) => { if (ok) { setDraft({ name: "", description: "" }); load(); } })}>Dodaj</button></td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

// ------------------------------------------------------------------------------ projekty


function ProjectsTab({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [files, setFiles] = useState<{ file_name: string; registered: boolean }[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [access, setAccess] = useState<{ project: AdminProject; data: ProjectAccess } | null>(null);

  const load = useCallback(() => run(async () => {
    const [p, f, g] = await Promise.all([adminApi.projects(), adminApi.projectFiles(), adminApi.groups()]);
    setProjects(p); setFiles(f.filter((x) => !x.registered)); setGroups(g);
  }), [run]);
  useEffect(() => { load(); }, [load]);

  const update = (p: AdminProject, patch: Partial<AdminProject>) => {
    const { id, ...rest } = { ...p, ...patch };
    return run(() => adminApi.updateProject(id, rest)).then((ok) => { if (ok) { load(); onChanged(); } });
  };

  const register = (file_name: string) => {
    const slug = (file_name.split("/").slice(-1)[0] ?? file_name).replace(/\.(qgz|qgs)$/i, "")
      .toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return run(() => adminApi.createProject({ slug, title: slug, description: null, file_name, sort_order: 0, is_public: false }))
      .then((ok) => { if (ok) { load(); onChanged(); } });
  };


  return (
    <div className="admin-split">
      <section>
        <p className="muted">
          <b>Publiczny</b> — widoczny bez logowania (tylko podgląd). <b>Z uprawnieniami</b> — tylko dla
          zalogowanych z grup, którym nadano dostęp. Edycja zawsze wymaga roli „edycja” lub wyższej.
          W „Grupy…” ustawiasz też prawo do zdjęć i dokumentów oraz zakres danych (obszary).
        </p>
        <table className="grid">
          <thead><tr><th>Tytuł (menu)</th><th>Dostęp</th><th>Kolejność</th><th>Plik</th><th /></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><input defaultValue={p.title} onBlur={(e) => e.target.value !== p.title && update(p, { title: e.target.value })} /></td>
                <td>
                  <select value={p.is_public ? "public" : "private"} onChange={(e) => update(p, { is_public: e.target.value === "public" })}>
                    <option value="public">publiczny</option>
                    <option value="private">z uprawnieniami</option>
                  </select>
                </td>
                <td><input type="number" className="num" defaultValue={p.sort_order} onBlur={(e) => Number(e.target.value) !== p.sort_order && update(p, { sort_order: Number(e.target.value) })} /></td>
                <td className="muted">{p.file_name}</td>
                <td className="row-actions">
                  <button onClick={() => run(async () => setAccess({ project: p, data: await adminApi.projectAccess(p.id) }))}>Grupy i zakres…</button>
                  <button className="danger" title="Usuwa projekt z menu; plik zostaje na serwerze"
                    onClick={() => confirm(`Usunąć „${p.title}” z portalu? Plik projektu zostanie na serwerze.`) && run(() => adminApi.deleteProject(p.id)).then(() => { load(); onChanged(); })}>Usuń</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {files.length > 0 && (
          <>
            <h3>Pliki projektów niezarejestrowane w portalu</h3>
            <ul className="plain">
              {files.map((f) => (
                <li key={f.file_name}><code>{f.file_name}</code> <button onClick={() => register(f.file_name)}>Zarejestruj</button></li>
              ))}
            </ul>
          </>
        )}
      </section>

      {access && (
        <AccessEditor project={access.project} groups={groups} access={access.data}
          onChange={(data) => setAccess((a) => a && { ...a, data })}
          onSave={() => run(() => adminApi.setProjectAccess(access.project.id, access.data)).then((ok) => { if (ok) { setAccess(null); onChanged(); } })}
          onCancel={() => setAccess(null)} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------ podkłady

const KIND_LABEL = { wmts: "WMTS", xyz: "XYZ", sophia: "warstwa Sophii" } as const;

function BasemapsTab({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const [items, setItems] = useState<Basemap[]>([]);
  const [edit, setEdit] = useState<Basemap | "new" | null>(null);
  const load = useCallback(() => run(async () => setItems(await adminApi.basemaps())), [run]);
  useEffect(() => { load(); }, [load]);

  const saveRaw = (b: Basemap, patch: Partial<Basemap>) => {
    const { id, version: _v, ...rest } = { ...b, ...patch };
    return adminApi.updateBasemap(id, { ...rest, enabled: rest.enabled ?? true });
  };
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= items.length) return;
    const order = items.map((b, k) => ({ b, sort: k * 10 }));
    [order[i].sort, order[j].sort] = [order[j].sort, order[i].sort];
    run(() => Promise.all(order.filter((o) => o.sort !== o.b.sort_order).map((o) => saveRaw(o.b, { sort_order: o.sort }))))
      .then(() => { load(); onChanged(); });
  };

  if (edit) {
    return (
      <BasemapEditor
        basemap={edit === "new" ? null : edit}
        nextSortOrder={(items.length + 1) * 10}
        onCancel={() => setEdit(null)}
        onSaved={() => { setEdit(null); load(); onChanged(); }}
      />
    );
  }

  return (
    <section>
      <p className="muted">
        Podkłady są wspólne dla wszystkich projektów — każda usługa ma jedno źródło kafli. Usługi WMTS/XYZ
        pobiera przeglądarka bezpośrednio od dostawcy; „warstwa Sophii” idzie przez serwer i wspólny cache.
        Nakładki (np. cieniowanie) rysują się nad podkładem.
      </p>
      <div className="admin-actions"><button className="primary" onClick={() => setEdit("new")}>+ Dodaj podkład</button></div>
      <table className="grid">
        <thead><tr><th>Kolejność</th><th>Nazwa</th><th>Rodzaj</th><th>Typ</th><th>Domyślnie</th><th>Włączony</th><th /></tr></thead>
        <tbody>
          {items.map((b, i) => (
            <tr key={b.id} className={b.enabled ? "" : "inactive"}>
              <td className="row-actions">
                <button className="icon" disabled={i === 0} onClick={() => move(i, -1)} title="Wyżej">↑</button>
                <button className="icon" disabled={i === items.length - 1} onClick={() => move(i, 1)} title="Niżej">↓</button>
              </td>
              <td>{b.name}</td>
              <td>{b.is_overlay ? "nakładka" : "podkład"}</td>
              <td className="muted">{KIND_LABEL[b.kind]}{b.kind === "wmts" ? ` · ${b.config.matrix_set}` : ""}</td>
              <td>{b.visible_default ? "tak" : ""}</td>
              <td><input type="checkbox" checked={!!b.enabled} onChange={(e) => run(() => saveRaw(b, { enabled: e.target.checked })).then(() => { load(); onChanged(); })} /></td>
              <td className="row-actions">
                <button onClick={() => setEdit(b)}>Edytuj</button>
                <button className="danger" onClick={() => confirm(`Usunąć podkład ${b.name}?`) && run(() => adminApi.deleteBasemap(b.id)).then(() => { load(); onChanged(); })}>Usuń</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
