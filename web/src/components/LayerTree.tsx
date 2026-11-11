import { useState } from "react";
import { IconTable } from "./Icons";
import type { TreeNode } from "../types";

export const nodeKey = (n: TreeNode) => (n.kind === "layer" ? `l:${n.layer_id}` : `g:${n.name}`);

/** Początkowo widoczne węzły — zgodnie ze stanem zaznaczenia w projekcie QGIS. */
export function initialVisibility(node: TreeNode, out = new Set<string>()): Set<string> {
  if (node.visible) out.add(nodeKey(node));
  if (node.kind === "group") node.children.forEach((c) => initialVisibility(c, out));
  return out;
}

interface Props {
  tree: TreeNode;
  visible: Set<string>;
  onToggle: (node: TreeNode, parent: TreeNode | null) => void;
  editableIds: Set<string>;
  editLayerId: string | null;
  onEditLayer: (id: string | null) => void;
  tableIds: Set<string>;               // warstwy PostGIS — mają tabelę atrybutów
  onOpenTable: (id: string) => void;
}

function Node({ node, parent, depth, ...p }: Props & { node: TreeNode; parent: TreeNode | null; depth: number }) {
  const [open, setOpen] = useState(node.expanded);
  const key = nodeKey(node);
  const checked = p.visible.has(key);
  const isGroup = node.kind === "group";
  const radio = parent?.mutually_exclusive;

  return (
    <li>
      <div className="tree-row" style={{ paddingLeft: depth * 14 }}>
        {isGroup ? (
          <button className="twisty" onClick={() => setOpen(!open)} aria-label={open ? "Zwiń" : "Rozwiń"}>
            {open ? "▾" : "▸"}
          </button>
        ) : <span className="twisty" />}
        <label>
          <input type={radio ? "radio" : "checkbox"} checked={checked} onChange={() => p.onToggle(node, parent)} />
          <span className={node.kind === "raster_group" ? "raster" : ""}>{node.name}</span>
        </label>
        {node.kind === "layer" && node.layer_id && p.tableIds.has(node.layer_id) && (
          <button className="edit-btn table-btn" title="Otwórz tabelę atrybutów" aria-label={`Tabela atrybutów: ${node.name}`}
            onClick={() => p.onOpenTable(node.layer_id!)}><IconTable width={16} height={16} /></button>
        )}
        {node.kind === "layer" && node.layer_id && p.editableIds.has(node.layer_id) && (
          <button
            className={`edit-btn ${p.editLayerId === node.layer_id ? "active" : ""}`}
            title="Edytuj warstwę"
            onClick={() => p.onEditLayer(p.editLayerId === node.layer_id ? null : node.layer_id)}
          >✎</button>
        )}
      </div>
      {isGroup && open && (
        <ul>
          {node.children.map((c) => (
            <Node key={nodeKey(c)} {...p} tree={p.tree} node={c} parent={node} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function LayerTree(props: Props) {
  return (
    <ul className="tree">
      {props.tree.children.map((c) => (
        <Node key={nodeKey(c)} {...props} node={c} parent={props.tree} depth={0} />
      ))}
    </ul>
  );
}

/** Lista nazw WMS widocznych warstw, od spodu do wierzchu (QGIS: góra drzewa = na wierzchu). */
export function visibleWmsNames(
  node: TreeNode, visible: Set<string>, wmsName: (layerId: string) => string | undefined,
): string[] {
  const out: string[] = [];
  const walk = (n: TreeNode) => {
    if (!visible.has(nodeKey(n)) && n.name) return;
    if (n.kind === "layer" && n.layer_id) {
      const name = wmsName(n.layer_id);
      if (name) out.push(name);
    } else if (n.kind === "raster_group") {
      out.push(n.name);           // cała mozaika GeoTIFF jako jedna warstwa WMS
    } else {
      n.children.forEach(walk);
    }
  };
  walk(node);
  return out.reverse();
}
