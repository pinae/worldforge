// types.ts -- constraint data model + type registry.
// Adding a new constraint type = extend the union, add a META entry,
// add a renderer in MapView. Nothing else changes.

export type Vec = { x: number; y: number }; // heightmap pixel coords

export type PeakC = { id: string; type: "peak"; pos: Vec; height?: number };
export type FixedC = { id: string; type: "fixed"; pos: Vec; height: number };
export type RiverVertex = Vec & { height?: number };
export type RiverC = { id: string; type: "river"; points: RiverVertex[] };
export type Constraint = PeakC | FixedC | RiverC;
export type CType = Constraint["type"];

export const TOOLS = ["select", "peak", "river", "fixed"] as const;
export type Tool = (typeof TOOLS)[number];

export const META: Record<
    CType,
    { label: string; geometry: "point" | "polyline"; hint: string }
> = {
    peak: {
        label: "Peak",
        geometry: "point",
        hint: "click to raise a summit \u00b7 esc to sheathe the tool",
    },
    river: {
        label: "River",
        geometry: "polyline",
        hint: "click to trace the course \u00b7 enter to finish \u00b7 esc to abandon",
    },
    fixed: {
        label: "Fixed point",
        geometry: "point",
        hint: "click to survey a point, then record its elevation",
    },
};

export const TOOL_HINTS: Record<Tool, string> = {
    select: "click a mark to inspect it \u00b7 drag to move \u00b7 del to remove",
    peak: META.peak.hint,
    river: META.river.hint,
    fixed: META.fixed.hint,
};

let counter = 0;
export const newId = () => `c${Date.now().toString(36)}${(counter++).toString(36)}`;

export function describe(c: Constraint): string {
    switch (c.type) {
        case "peak":
            return c.height != null ? `Peak \u00b7 ${c.height} m` : "Peak \u00b7 auto";
        case "fixed":
            return `Fixed \u00b7 ${c.height} m`;
        case "river":
            return `River \u00b7 ${c.points.length} pts`;
    }
}

// Backend payload: heightmap pixel coords, y down -- matches the masks
// the rasterizer builds for erosion.Constraints.
export function toPayload(constraints: Constraint[]) {
    return constraints.map((c) =>
        c.type === "river"
            ? {type: c.type, id: c.id, points: c.points}
            : {type: c.type, id: c.id, pos: c.pos, height: (c as PeakC).height ?? null},
    );
}