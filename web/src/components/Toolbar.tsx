import type { ComponentType, ReactNode, SVGProps } from "react";
import type { LayerInfo, ProjectConfig } from "../types";
import type { Tool } from "./MapView";
import {
  GEOMETRY_ICON, IconAddPolygon, IconAddRecord, IconDelete, IconEdit, IconFetchBuilding, IconFetchParcel, IconIdentify,
  IconDeletePart, IconDeleteRing, IconFillRing, IconLayers, IconMerge, IconMove, IconPrint, IconRing, IconSelect, IconSplit,
  IconAddPart, IconCopy, IconReshape, IconRotate, IconTable, IconUndo, IconVertex,
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
export function Toolbar({ config, editLayerId, onEditLayer, tool, onTool, canDelete, onDelete, onNewRecord, onUndo,
  sidebarOpen, onToggleSidebar, fetchToolId, onFetchTool, onOpenTable, onPrint, widgets }: {
  config: ProjectConfig | null;
  editLayerId: string | null;
  onEditLayer: (id: string | null) => void;
  tool: Tool;
  onTool: (t: Tool) => void;
  canDelete: boolean;              // zaznaczony (zapisany) obiekt warstwy edycyjnej i prawo usuwania
  onDelete: () => void;
  onNewRecord: () => void;
  onUndo: (() => void) | null;     // cofnij ostatnią własną operację (null = niezalogowany)
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  fetchToolId: string | null;      // aktywne narzędzie pobierania (ULDK…)
  onFetchTool: (id: string) => void;
  onOpenTable: () => void;         // tabela atrybutów warstwy edycyjnej
  onPrint: (() => void) | null;    // wydruk widoku mapy (null = mapa jeszcze niegotowa)
  widgets?: ReactNode[];           // elementy wtyczek (np. pole wyszukiwania) — po prawej
}) {
  const editable: LayerInfo[] = Object.values(config?.layers ?? {})
    .filter((l) => l.perms.insert || l.perms.update || l.perms.delete)
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));
  const layer = editLayerId ? config?.layers[editLayerId] ?? null : null;
  const geom = layer?.geometry_type ?? null;
  const DrawIcon = geom ? GEOMETRY_ICON[geom] : IconAddPolygon;
  const poly = geom === "Polygon";
  const lineOrPoly = geom === "Polygon" || geom === "Line";

  return (
    <div className="toolbar" role="toolbar" aria-label="Narzędzia">
      <ToolButton icon={IconLayers} label={sidebarOpen ? "Ukryj panel warstw" : "Pokaż panel warstw"}
        active={sidebarOpen} onClick={onToggleSidebar} />
      <span className="sep" />
      <ToolButton icon={IconIdentify} label="Identyfikuj obiekty" active={tool === "identify"}
        disabled={!config} onClick={() => onTool("identify")} />
      <ToolButton icon={IconPrint} label="Wydruk widoku mapy (PDF)" disabled={!onPrint} onClick={() => onPrint?.()} />

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
          <ToolButton icon={IconMove} label="Przesuń obiekt (przeciągnij)" active={tool === "move"}
            disabled={!geom || !layer?.perms.update} onClick={() => onTool("move")} />
          <ToolButton icon={IconRotate} label="Obróć obiekt (przeciągnij wokół środka; Shift = co 15°)" active={tool === "rotate"}
            disabled={!lineOrPoly || !layer?.perms.update} onClick={() => onTool("rotate")} />
          <ToolButton icon={IconCopy} label="Kopiuj obiekt (przeciągnij kopię w nowe miejsce)" active={tool === "copy"}
            disabled={!geom || !layer?.perms.insert} onClick={() => onTool("copy")} />
          <ToolButton icon={IconReshape} label="Przekształć obiekt (linia przecinająca granicę dwa razy)" active={tool === "reshape"}
            disabled={!lineOrPoly || !layer?.perms.update} onClick={() => onTool("reshape")} />
          <ToolButton icon={IconSplit} label="Podziel obiekty (linią; zaznaczony obiekt albo wszystkie przecięte)"
            active={tool === "split"} onClick={() => onTool("split")}
            disabled={!(geom === "Polygon" || geom === "Line") || !layer?.perms.update || !layer?.perms.insert} />
          <ToolButton icon={IconMerge} label="Połącz obiekty (kliknij kolejne; pierwszy zostaje)" active={tool === "merge"}
            disabled={!geom || !layer?.perms.update || !layer?.perms.delete} onClick={() => onTool("merge")} />
          <ToolButton icon={IconRing} label="Dodaj pierścień (dziura w poligonie)" active={tool === "ring"}
            disabled={!poly || !layer?.perms.update} onClick={() => onTool("ring")} />
          <ToolButton icon={IconFillRing} label="Wypełnij pierścień (dziura z nowym obiektem)" active={tool === "fillring"}
            disabled={!poly || !layer?.perms.update || !layer?.perms.insert} onClick={() => onTool("fillring")} />
          <ToolButton icon={IconDeleteRing} label="Usuń pierścień (kliknij w dziurę)" active={tool === "delring"}
            disabled={!poly || !layer?.perms.update} onClick={() => onTool("delring")} />
          <ToolButton icon={IconAddPart} label={layer && geom && !layer.multi
            ? "Dodaj część — warstwa nie ma obiektów wieloczęściowych" : "Dodaj część do obiektu otwartego w formularzu"}
            active={tool === "addpart"} disabled={!geom || !layer?.multi || !layer?.perms.update} onClick={() => onTool("addpart")} />
          <ToolButton icon={IconDeletePart} label={layer && geom && !layer.multi
            ? "Usuń część — warstwa nie ma obiektów wieloczęściowych" : "Usuń część obiektu wieloczęściowego (kliknij część)"}
            active={tool === "delpart"} disabled={!geom || !layer?.multi || !layer?.perms.update} onClick={() => onTool("delpart")} />
          <ToolButton icon={IconDelete} label="Usuń zaznaczony obiekt" disabled={!canDelete} onClick={onDelete} />
          <ToolButton icon={IconTable} label={layer ? `Otwórz tabelę atrybutów: ${layer.name}` : "Otwórz tabelę atrybutów"}
            disabled={!layer} onClick={onOpenTable} />
          <ToolButton icon={IconUndo} label="Cofnij ostatnią operację (Ctrl+Z)" disabled={!onUndo} onClick={() => onUndo?.()} />
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
      {widgets && widgets.length > 0 && <div className="toolbar-widgets">{widgets}</div>}
    </div>
  );
}
