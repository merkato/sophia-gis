import { useEffect, useState } from "react";
import { adminApi } from "../api";
import type { AdminProject, Group, GroupAccess, ProjectAccess, ProjectRole, ProjectScopeInfo } from "../types";

const ROLES: [ProjectRole | "", string][] = [["", "— brak dostępu —"], ["viewer", "podgląd"], ["editor", "edycja"], ["manager", "zarządzanie"]];
const MODE_LABEL: Record<string, string> = {
  spatial: "przestrzennie (w granicy obszaru)", attribute: "atrybut", relation: "przez relację z obiektem", none: "bez ograniczeń",
};

const newGrant = (group_id: number, role: ProjectRole): GroupAccess =>
  ({ group_id, role, can_photos: true, can_files: true, scope_all: true, scope_codes: [] });

/**
 * Dostęp grup do projektu: rola, prawo do zdjęć i dokumentów, zakres danych (cały obszar albo
 * wybrane kody obszarów z warstwy granic zdefiniowanej w Fii). docs/user/uprawnienia.md
 */
export function AccessEditor({ project, groups, access, onChange, onSave, onCancel }: {
  project: AdminProject; groups: Group[]; access: ProjectAccess;
  onChange: (a: ProjectAccess) => void; onSave: () => void; onCancel: () => void;
}) {
  const [scope, setScope] = useState<ProjectScopeInfo["scope"] | undefined>(undefined);
  const [filter, setFilter] = useState<Record<number, string>>({});
  useEffect(() => {
    let cancelled = false;
    adminApi.projectScope(project.id).then((s) => !cancelled && setScope(s.scope)).catch(() => !cancelled && setScope(null));
    return () => { cancelled = true; };
  }, [project.id]);

  const grantOf = (gid: number) => access.groups.find((g) => g.group_id === gid);
  const put = (gid: number, patch: Partial<GroupAccess> | null) => {
    const others = access.groups.filter((g) => g.group_id !== gid);
    const cur = grantOf(gid);
    onChange({ ...access, groups: patch === null ? others : [...others, { ...(cur ?? newGrant(gid, "viewer")), ...patch }] });
  };
  const toggleCode = (gid: number, code: string) => {
    const g = grantOf(gid);
    if (!g) return;
    const codes = g.scope_codes.includes(code) ? g.scope_codes.filter((c) => c !== code) : [...g.scope_codes, code].sort();
    put(gid, { scope_codes: codes });
  };

  return (
    <section className="admin-form form access-editor">
      <h3>Dostęp grup: {project.title}</h3>
      {project.is_public && <p className="muted">Projekt jest publiczny — każdy ogląda go bez ograniczeń zakresu. Role poniżej nadają edycję.</p>}
      {scope === undefined && <p className="muted">Wczytywanie zakresu danych…</p>}
      {scope && (
        <details className="scope-info">
          <summary>Zakres danych: <b>{scope.label}</b> (warstwa „{scope.layer}”, pole <code>{scope.field}</code>, {scope.codes.length} obszarów)</summary>
          <ul className="plain">
            {Object.entries(scope.layers).map(([lid, l]) => (
              <li key={lid}>{l.name}: <span className="muted">{MODE_LABEL[l.mode] ?? l.mode}{l.field ? ` — pole ${l.field}` : ""}</span></li>
            ))}
          </ul>
        </details>
      )}
      {scope === null && <p className="muted">Projekt nie ma wymiaru zakresu (ustawiany w Fii) — grupy widzą cały projekt.</p>}
      {groups.length === 0 && <p className="muted">Brak grup — utwórz je w zakładce Grupy.</p>}

      {groups.map((grp) => {
        const g = grantOf(grp.id);
        const q = (filter[grp.id] ?? "").toLowerCase();
        return (
          <fieldset key={grp.id} className={g ? "grant" : "grant off"}>
            <legend>{grp.name}</legend>
            <select value={g?.role ?? ""} aria-label={`Rola grupy ${grp.name}`}
              onChange={(e) => put(grp.id, e.target.value ? { role: e.target.value as ProjectRole } : null)}>
              {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            {g && (
              <>
                <div className="inline-checks">
                  <label className="check"><input type="checkbox" checked={g.can_photos} onChange={(e) => put(grp.id, { can_photos: e.target.checked })} /> zdjęcia</label>
                  <label className="check"><input type="checkbox" checked={g.can_files} onChange={(e) => put(grp.id, { can_files: e.target.checked })} /> dokumenty</label>
                </div>
                {scope && (
                  <div className="scope-pick">
                    <label className="check"><input type="radio" checked={g.scope_all} onChange={() => put(grp.id, { scope_all: true })} /> cały obszar</label>
                    <label className="check"><input type="radio" checked={!g.scope_all} onChange={() => put(grp.id, { scope_all: false })} /> wybrane: {scope.label.toLowerCase()}</label>
                    {!g.scope_all && (
                      <>
                        {scope.codes.length > 12 && (
                          <input placeholder="Szukaj kodu…" value={filter[grp.id] ?? ""}
                            onChange={(e) => setFilter((f) => ({ ...f, [grp.id]: e.target.value }))} />
                        )}
                        <div className="codes">
                          {scope.codes.filter((c) => !q || c.toLowerCase().includes(q) || g.scope_codes.includes(c)).map((c) => (
                            <label key={c} className={`code${g.scope_codes.includes(c) ? " on" : ""}`}>
                              <input type="checkbox" checked={g.scope_codes.includes(c)} onChange={() => toggleCode(grp.id, c)} /> {c}
                            </label>
                          ))}
                        </div>
                        {!g.scope_codes.length && <div className="error">Nie wybrano żadnego obszaru — grupa nie zobaczy danych objętych zakresem.</div>}
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </fieldset>
        );
      })}
      <div className="actions">
        <button className="primary" onClick={onSave}>Zapisz</button>
        <button onClick={onCancel}>Anuluj</button>
      </div>
    </section>
  );
}
