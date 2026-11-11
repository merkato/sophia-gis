import { useCallback, useEffect, useState } from "react";
import { adminApi, type UploadsOverview } from "../api";

const mb = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);

/**
 * Pliki zdjęć i dokumentów wysłanych z WebUI: rozmiar, osierocone (bez odwołania w bazie), kosz.
 * Sprzątanie przenosi sieroty do kosza projektu; kosz opróżnia się osobno. docs/user/README.md
 */
export function UploadsTab({ run }: { run: (fn: () => Promise<unknown>) => Promise<boolean> }) {
  const [minAge, setMinAge] = useState(7);
  const [data, setData] = useState<UploadsOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    return run(async () => setData(await adminApi.uploads(minAge))).finally(() => setLoading(false));
  }, [run, minAge]);
  useEffect(() => { load(); }, [load]);

  const cleanup = (id: number, title: string, n: number, size: number) => {
    if (!confirm(`Przenieść do kosza ${n} osieroconych plików (${mb(size)}) z projektu „${title}”?\n`
      + "Pliki można odzyskać z kosza do czasu jego opróżnienia.")) return;
    run(async () => {
      const r = await adminApi.cleanupUploads(id, minAge);
      setNotice(`„${title}”: przeniesiono do kosza ${r.moved} plików (${mb(r.size)}).`);
      await load();
    });
  };
  const purge = (id: number, title: string, all: boolean) => {
    if (!confirm(all ? `Trwale usunąć CAŁY kosz projektu „${title}”? Tego nie da się cofnąć.`
      : `Trwale usunąć z kosza projektu „${title}” pliki przeniesione ponad 30 dni temu?`)) return;
    run(async () => {
      const r = await adminApi.purgeTrash(id, all ? 0 : 30);
      setNotice(`„${title}”: usunięto z kosza ${r.deleted} plików (${mb(r.size)}).`);
      await load();
    });
  };

  return (
    <section className="narrow uploads-tab">
      <p className="muted">
        Zdjęcia i dokumenty dodane w WebUI leżą w <code>data/uploads/&lt;projekt&gt;</code>. <b>Osierocony</b> plik
        to taki, do którego nie odwołuje się już żaden rekord (zdjęcie usunięte z pola albo rekord zdjęcia
        usunięty). Sprzątanie <b>przenosi</b> takie pliki do kosza projektu — nic nie jest kasowane od razu.
      </p>
      <div className="inline">
        <label className="check">Pomijaj pliki młodsze niż
          <input type="number" className="num" min={1} value={minAge} onChange={(e) => setMinAge(Math.max(1, Number(e.target.value) || 7))} /> dni
        </label>
        <button onClick={load} disabled={loading}>{loading ? "Sprawdzanie…" : "Sprawdź ponownie"}</button>
      </div>
      <p className="muted">Próg chroni świeżo wysłane zdjęcia, których formularz nie został jeszcze zapisany.</p>
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}

      {data && (
        <table className="grid">
          <thead><tr><th>Projekt</th><th>Pliki</th><th>Osierocone</th><th>Kosz</th><th /></tr></thead>
          <tbody>
            {data.projects.map((p) => (
              <tr key={p.project_id}>
                <td>{p.title}<div className="muted">{p.slug}</div></td>
                <td>{p.files} · {mb(p.size)}
                  {p.missing > 0 && <div className="muted" title="Rekordy wskazują pliki, których nie ma na dysku">brak plików dla {p.missing} odwołań</div>}
                </td>
                <td>
                  {p.error ? <span className="muted" title={p.error}>pominięty — {p.error}</span> : (
                    <>
                      {p.orphans} · {mb(p.orphans_size)}
                      {p.recent > 0 && <div className="muted">+ {p.recent} świeżych (zostają)</div>}
                      {p.orphans > 0 && (
                        <details><summary className="muted">pokaż</summary>
                          <ul className="plain small">{p.orphan_paths.map((x) => <li key={x}><code>{x}</code></li>)}</ul>
                        </details>
                      )}
                    </>
                  )}
                </td>
                <td>{p.trash_files ? `${p.trash_files} · ${mb(p.trash_size)}` : "—"}</td>
                <td className="row-actions">
                  <button disabled={!!p.error || !p.orphans} onClick={() => cleanup(p.project_id, p.title, p.orphans, p.orphans_size)}>Do kosza</button>
                  <button disabled={!p.trash_files} onClick={() => purge(p.project_id, p.title, false)} title="Usuń wpisy kosza starsze niż 30 dni">Opróżnij (&gt;30 dni)</button>
                  <button className="danger" disabled={!p.trash_files} onClick={() => purge(p.project_id, p.title, true)}>Cały kosz</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && data.unregistered.length > 0 && (
        <>
          <h3>Katalogi bez zarejestrowanego projektu</h3>
          <p className="muted">Zostają nietknięte — usuń je ręcznie na serwerze, jeśli projekt nie wróci.</p>
          <ul className="plain">{data.unregistered.map((u) => <li key={u.slug}><code>data/uploads/{u.slug}</code> — {u.files} plików, {mb(u.size)}</li>)}</ul>
        </>
      )}
    </section>
  );
}
