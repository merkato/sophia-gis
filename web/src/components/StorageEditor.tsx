import { useEffect, useState } from "react";
import { adminApi, type ProjectStorage } from "../api";
import type { AdminProject } from "../types";

const KIND: Record<string, string> = { photo: "zdjęcia", file: "dokumenty" };

/**
 * Przechowywanie plików w projekcie: zbiory, do których użytkownicy wgrywają pliki (pola „Załącznik” warstw,
 * zbiory wtyczek), z limitem wielkości pliku. Domyślnie limit globalny serwera; można go tylko obniżyć.
 * Limit ustawiony w Fii przychodzi przy publikacji i nadpisuje wpis z panelu dla tego zbioru. docs/user/zalaczniki.md
 */
export function StorageEditor({ project, onClose, onError }: {
  project: AdminProject; onClose: () => void; onError: (m: string) => void;
}) {
  const [data, setData] = useState<ProjectStorage | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const take = (d: ProjectStorage) => {
    setData(d);
    setDraft(Object.fromEntries(d.sets.map((s) => [s.id, s.limit ? String(s.limit.max_mb).replace(".", ",") : ""])));
  };
  useEffect(() => {
    let cancelled = false;
    adminApi.projectStorage(project.id).then((d) => !cancelled && take(d)).catch((e) => onError((e as Error).message));
    return () => { cancelled = true; };
  }, [project.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const parse = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
  const invalid = data ? data.sets.filter((s) => {
    const v = parse(draft[s.id] ?? "");
    return v !== null && (!Number.isFinite(v) || v <= 0 || v > s.default_mb);
  }).map((s) => s.id) : [];
  const changed = data ? data.sets.some((s) => parse(draft[s.id] ?? "") !== (s.limit ? s.limit.max_mb : null)) : false;

  const save = async () => {
    if (!data) return;
    setBusy(true);
    try {
      take(await adminApi.setProjectStorage(project.id, Object.fromEntries(data.sets.map((s) => [s.id, parse(draft[s.id] ?? "")]))));
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <section className="admin-form form storage-editor">
      <h3>Przechowywanie plików: {project.title}</h3>
      {!data ? <p className="muted">Wczytywanie…</p> : (
        <>
          <p className="muted">
            Limit wielkości jednego pliku w zbiorze. Puste pole = limit globalny serwera (zdjęcia {data.global.photo} MB,
            dokumenty {data.global.file} MB); można go tylko obniżyć. Limit ustawiony w Fii przychodzi przy publikacji
            projektu i zastępuje wpis z panelu dla tego zbioru.
          </p>
          {data.sets.length === 0 ? <p className="muted">Projekt nie ma zbiorów plików — pól z widżetem „Załącznik” w warstwach PostGIS ani zbiorów wtyczek.</p> : (
            <table className="grid">
              <thead><tr><th>Zbiór</th><th>Rodzaj</th><th>Limit (MB)</th><th>Źródło</th></tr></thead>
              <tbody>
                {data.sets.map((s) => (
                  <tr key={s.id}>
                    <td>{s.title}<div className="muted"><code>{s.source === "plugin" ? `wtyczka: ${s.plugin}` : s.field}</code></div></td>
                    <td>{KIND[s.kind] ?? s.kind}</td>
                    <td>
                      <input className={`num${invalid.includes(s.id) ? " invalid" : ""}`} inputMode="decimal" value={draft[s.id] ?? ""}
                        placeholder={`${s.default_mb} (globalny)`} aria-label={`Limit dla ${s.title}`}
                        onChange={(e) => setDraft({ ...draft, [s.id]: e.target.value })} />
                    </td>
                    <td className="muted">{s.limit ? `${s.limit.source === "fia" ? "Fia" : "panel"}${s.limit.updated_by ? ` · ${s.limit.updated_by}` : ""}` : "domyślny"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {invalid.length > 0 && <div className="error">Limit musi być większy od 0 i nie większy niż globalny dla danego rodzaju.</div>}
          {data.orphans.length > 0 && (
            <p className="muted">Zapisane limity bez zbioru w projekcie (usunięte pole lub wtyczka): {data.orphans.map((o) => o.id).join(", ")} — znikną przy zapisie.</p>
          )}
        </>
      )}
      <div className="actions">
        <button className="primary" disabled={!data || busy || invalid.length > 0 || (!changed && !(data && data.orphans.length))} onClick={save}>
          {busy ? "Zapisywanie…" : "Zapisz"}</button>
        <button onClick={onClose}>Zamknij</button>
      </div>
    </section>
  );
}
