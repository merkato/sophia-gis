import type { ComponentType, SVGProps } from "react";
import type { LayerInfo, ProjectConfig } from "../types";
import type { Tool } from "./MapView";
import {
  GEOMETRY_ICON, IconAddPolygon, IconAddRecord, IconDelete, IconEdit, IconFetchBuilding, IconFetchParcel, IconIdentify,
  IconLayers, IconSelect, IconVertex,
} from "./Icons";

const DRAW_LABEL = { Point: "Dodaj obiekt punktowy", Line: "Dodaj obiekt liniowy", Polygon: "Dodaj obiekt poligonowy" };

function ToolButton({ icon: Icon, label, active, disabled, onClick }: {
  icon: ComponentType<SVGProps<SVGSVGElement>>; label: string; active?: boolean; disabled?: boolean; onClick: () => void;
}) {
  return (
    <button type="button" className={`tool${active ? " active" : ""}`} title={label} aria-label={label}
      aria-pressed={active} disabled={disabled} onClick={onClick}>
      <Icon />
    </button>
  );
}

/**
 * Pasek narzędzi pod paskiem tytułu (jak paski „Digitalizacja” i „Atrybuty” w QGIS).
 * Narzędzia edycji są zawsze widoczne; bez aktywnej warstwy edycyjnej są wyszarzone.
 */
export function Toolbar({ config, editLayerId, onEditLayer, tool, onTool, canDelete, onDelete, onNewRecord,
  sidebarOpen, onToggleSidebar, fetchToolId, onFetchTool }: {
  config: ProjectConfig | null;
  editLayerId: string | null;
  onEditLayer: (id: string | null) => void;
  tool: Tool;
  onTool: (t: Tool) => void;
  canDelete: boolean;              // zaznaczony (zapisany) obiekt warstwy edycyjnej i prawo usuwania
  onDelete: () => void;
  onNewRecord: () => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  fetchToolId: string | null;      // aktywne narzędzie pobierania (ULDK…)
  onFetchTool: (id: string) => void;
}) {
  const editable: LayerInfo[] = Object.values(config?.layers ?? {})
    .filter((l) => l.perms.insert || l.perms.update || l.perms.delete)
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));
  const layer = editLayerId ? config?.layers[editLayerId] ?? null : null;
  const geom = layer?.geometry_type ?? null;
  const DrawIcon = geom ? GEOMETRY_ICON[geom] : IconAddPolygon;

  return (
    <div className="toolbar" role="toolbar" aria-label="Narzędzia">
      <ToolButton icon={IconLayers} label={sidebarOpen ? "Ukryj panel warstw" : "Pokaż panel warstw"}
        active={sidebarOpen} onClick={onToggleSidebar} />
      <span className="sep" />
      <ToolButton icon={IconIdentify} label="Identyfikuj obiekty" active={tool === "identify"}
        disabled={!config} onClick={() => onTool("identify")} />

      {config && editable.length > 0 && (
        <>
          <span className="sep" />
          <ToolButton icon={IconEdit} label={layer ? `Zakończ edycję: ${layer.name}` : "Włącz edycję wybranej warstwy"}
            active={!!layer} onClick={() => onEditLayer(layer ? null : editable[0].id)} />
          <select className="edit-layer" value={editLayerId ?? ""} aria-label="Warstwa edycyjna"
            title="Warstwa edycyjna" onChange={(e) => onEditLayer(e.target.value || null)}>
            <option value="">— bez edycji —</option>
            {editable.map((l) => <option key={l.id} value={l.id}>{l.name}{l.geometry_type ? "" : " (tabela)"}</option>)}
          </select>
          <span className="sep" />
          <ToolButton icon={IconSelect} label="Zaznacz obiekt (kliknięcie otwiera formularz)"
            active={tool === "select"} disabled={!geom} onClick={() => onTool("select")} />
          {layer && !geom ? (
            <ToolButton icon={IconAddRecord} label="Dodaj rekord" disabled={!layer.perms.insert} onClick={onNewRecord} />
          ) : (
            <ToolButton icon={DrawIcon} label={geom ? DRAW_LABEL[geom] : "Dodaj obiekt"} active={tool === "draw"}
              disabled={!geom || !layer?.perms.insert} onClick={() => onTool("draw")} />
          )}
          <ToolButton icon={IconVertex} label="Narzędzie wierzchołków (zmiana geometrii)" active={tool === "modify"}
            disabled={!geom || !layer?.perms.update} onClick={() => onTool("modify")} />
          <ToolButton icon={IconDelete} label="Usuń zaznaczony obiekt" disabled={!canDelete} onClick={onDelete} />
        </>
      )}

      {config && (config.tools ?? []).length > 0 && (
        <>
          <span className="sep" />
          {(config.tools ?? []).map((t) => (
            <ToolButton key={t.id} icon={t.source.includes("budynek") ? IconFetchBuilding : IconFetchParcel}
              label={`${t.label} → ${config.layers[t.layer_id]?.name ?? t.layer_id}`}
              active={tool === "fetch" && fetchToolId === t.id} onClick={() => onFetchTool(t.id)} />
          ))}
        </>
      )}

      {config?.scope && config.scope.codes && (
        <span className="scope-badge" title={`Twój zakres danych: ${config.scope.codes.join(", ") || "brak"}`}>
          {config.scope.label}: {config.scope.codes.length ? config.scope.codes.join(", ") : "brak"}
        </span>
      )}
    </div>
  );
}
