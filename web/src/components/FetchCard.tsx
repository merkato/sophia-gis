import type { FetchResult, ProjectConfig, ToolInfo } from "../types";

/** Kolejność i etykiety najważniejszych pól w karcie (pozostałe po nich). */
const ORDER = ["teryt", "numer", "obreb", "obreb_nr", "gmina", "powiat", "wojewodztwo", "gmina_teryt"];

/**
 * Karta wyniku narzędzia pobierania (np. działka z ULDK): co znaleziono, dokąd trafi
 * (warstwa i pola z konfiguracji Fii) i decyzja — dodać czy nie.
 */
export function FetchCard({ config, tool, state, onAdd, onOpenExisting, onClose }: {
  config: ProjectConfig;
  tool: ToolInfo;
  state: { loading: boolean; error: string | null; result: FetchResult | null };
  onAdd: (r: FetchResult) => void;
  onOpenExisting: (r: FetchResult) => void;
  onClose: () => void;
}) {
  const layer = config.layers[tool.layer_id];
  const { loading, error, result } = state;
  const fieldLabel = (name: string) => layer?.fields.find((f) => f.name === name)?.alias ?? name;
  const keys = result
    ? [...ORDER.filter((k) => k in result.properties), ...Object.keys(result.properties).filter((k) => !ORDER.includes(k))]
    : [];
  const mappedBack = result ? Object.fromEntries(Object.entries(result.mapped).map(([dst]) => [dst, true])) : {};

  return (
    <div className="fetch-card" role="dialog" aria-label={tool.label}>
      <header>
        <strong>{tool.label}</strong>
        <button className="icon" onClick={onClose} title="Zamknij" aria-label="Zamknij">✕</button>
      </header>
      {loading && <p className="muted">Szukam w usłudze: {tool.source_name}…</p>}
      {!loading && !result && !error && <p className="muted">Kliknij na mapie miejsce, w którym leży obiekt.</p>}
      {error && <div className="error">{error}</div>}
      {result && !loading && (
        <>
          <table className="fetch-props">
            <tbody>
              {keys.map((k) => (
                <tr key={k}>
                  <th>{result.labels[k] ?? k}</th>
                  <td>{result.properties[k] ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Trafi do warstwy <b>{layer?.name ?? tool.layer_id}</b>
            {Object.keys(mappedBack).length > 0 && <> — pola: {Object.keys(result.mapped).map(fieldLabel).join(", ")}</>}
            {result.open_form ? ", potem formularz do uzupełnienia." : "."}
          </p>
          {result.existing_pk && (
            <div className="notice">Ten obiekt jest już w warstwie (#{result.existing_pk}).</div>
          )}
          <div className="actions">
            {result.existing_pk ? (
              <>
                <button className="primary" onClick={() => onOpenExisting(result)}>Otwórz istniejący</button>
                <button onClick={() => onAdd(result)}>Dodaj mimo to</button>
              </>
            ) : (
              <button className="primary" onClick={() => onAdd(result)}>Dodaj do warstwy</button>
            )}
            <button onClick={onClose}>Anuluj</button>
          </div>
          <p className="muted">Kliknij inne miejsce na mapie, aby pobrać inny obiekt.</p>
        </>
      )}
    </div>
  );
}
