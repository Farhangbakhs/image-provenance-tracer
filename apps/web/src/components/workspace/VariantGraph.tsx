"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo, useState } from "react";

import { API_URL, type RunAnalysisOut } from "@/lib/api/client";
import type { WorkspaceModel } from "@/lib/workspace";

const NARRATIVE_COLOURS = ["#8fb3e8", "#d98fd0", "#8fd9c2", "#e8c48f", "#b0a2ef"];

type VariantNodeData = {
  label: string;
  count: number;
  image: string | null;
  colour: string;
  earliest: boolean;
  selected: boolean;
};

function VariantNode({ data }: NodeProps<Node<VariantNodeData>>) {
  return (
    <div
      className="w-36 border bg-surface-1 text-[11px]"
      style={{ borderColor: data.earliest ? "var(--accent)" : data.colour, borderWidth: data.selected ? 2 : 1 }}
    >
      <Handle type="target" position={Position.Top} />
      {data.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={data.image} alt={`Variant ${data.label}`} className="h-20 w-full object-cover" />
      ) : null}
      <div className="flex justify-between px-1.5 py-1">
        <span className="mono">{data.label}</span>
        <span className="text-muted">
          {data.count} cop{data.count === 1 ? "y" : "ies"}
        </span>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { variant: VariantNode };

/** Variants as a tree: parents above children, siblings side by side. */
export function layoutTree(ids: string[], parentOf: Record<string, string>): Record<string, { x: number; y: number }> {
  const children: Record<string, string[]> = {};
  for (const id of ids) {
    const parent = parentOf[id];
    if (parent) (children[parent] ??= []).push(id);
  }
  const roots = ids.filter((id) => !parentOf[id]);
  const positions: Record<string, { x: number; y: number }> = {};
  let column = 0;
  const place = (id: string, depth: number): number => {
    const kids = children[id] ?? [];
    if (kids.length === 0) {
      positions[id] = { x: column++ * 190, y: depth * 170 };
      return positions[id].x;
    }
    const xs = kids.map((kid) => place(kid, depth + 1));
    positions[id] = { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: depth * 170 };
    return positions[id].x;
  };
  for (const root of roots) place(root, 0);
  return positions;
}

export function VariantGraph({
  model,
  analysis,
  selected,
  onSelect,
}: {
  model: WorkspaceModel;
  analysis: RunAnalysisOut;
  selected: string | null;
  onSelect: (sightingId: string) => void;
}) {
  const [byNarrative, setByNarrative] = useState(false);

  const { nodes, edges } = useMemo(() => {
    const narrativeColour: Record<string, string> = {};
    model.lanes.forEach((lane, i) => (narrativeColour[lane.id] = NARRATIVE_COLOURS[i % NARRATIVE_COLOURS.length]));
    const parentOf: Record<string, string> = {};
    for (const e of analysis.edges) parentOf[e.child_variant_id] = e.parent_variant_id;
    const positions = layoutTree(
      analysis.variants.map((v) => v.id),
      parentOf,
    );
    const nodes: Node<VariantNodeData>[] = analysis.variants.map((v) => {
      const rep = v.representative_sighting_id ?? v.sighting_ids[0] ?? null;
      const lane = rep ? model.laneOf[rep] : undefined;
      return {
        id: v.id,
        type: "variant",
        position: positions[v.id] ?? { x: 0, y: 0 },
        data: {
          label: v.label,
          count: v.sighting_ids.length,
          image: rep ? `${API_URL}/sightings/${rep}/image` : null,
          colour: byNarrative && lane ? narrativeColour[lane] : "var(--line)",
          earliest: model.earliestId !== null && v.sighting_ids.includes(model.earliestId),
          selected: selected !== null && v.sighting_ids.includes(selected),
        },
      };
    });
    const grouped: Record<string, string[]> = {};
    for (const e of analysis.edges) (grouped[`${e.parent_variant_id}>${e.child_variant_id}`] ??= []).push(e.kind);
    const edges: Edge[] = Object.entries(grouped).map(([key, kinds]) => {
      const [source, target] = key.split(">");
      return {
        id: key,
        source,
        target,
        label: kinds.join(", "),
        style: { stroke: "var(--muted)" },
        labelStyle: { fill: "var(--text)", fontSize: 10 },
        labelBgStyle: { fill: "var(--surface-2)" },
      };
    });
    return { nodes, edges };
  }, [analysis, model, selected, byNarrative]);

  const firstSightingOf = Object.fromEntries(analysis.variants.map((v) => [v.id, v.representative_sighting_id ?? v.sighting_ids[0]]));

  return (
    <div>
      <div className="flex items-center justify-between px-3 py-1.5 text-[11px] text-muted">
        <span>Each box is a variant: copies of the same picture in the same form. Arrows point from source to edit.</span>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={byNarrative} onChange={(e) => setByNarrative(e.target.checked)} />
          Colour by narrative
        </label>
      </div>
      <div className="h-[460px] border-t border-line">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          colorMode="dark"
          fitView
          nodesDraggable={false}
          onNodeClick={(_, node) => firstSightingOf[node.id] && onSelect(firstSightingOf[node.id])}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--line)" gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
