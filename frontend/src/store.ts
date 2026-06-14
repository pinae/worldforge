// store.ts -- editor state with undo/redo.
// Undo model: every mutating action snapshots `constraints` first
// (structural sharing via shallow copy keeps this cheap at editor scale).

import {create} from "zustand";
import type {Constraint, RiverVertex, Tool, Vec} from "./types";
import {newId} from "./types";

type CMap = Record<string, Constraint>;

interface EditorState {
    size: number; // heightmap size in pixels
    tool: Tool;
    selection: string | null;
    constraints: CMap;
    order: string[]; // stable display order
    hidden: Record<string, true>;
    draft: RiverVertex[] | null; // river being traced
    pendingFixed: Vec | null; // awaiting elevation entry
    cursor: Vec | null;
    past: { constraints: CMap; order: string[] }[];
    future: { constraints: CMap; order: string[] }[];
    status: string;

    setTool: (t: Tool) => void;
    select: (id: string | null) => void;
    setCursor: (v: Vec | null) => void;
    setStatus: (s: string) => void;
    toggleHidden: (id: string) => void;

    placePeak: (pos: Vec) => void;
    requestFixed: (pos: Vec) => void;
    confirmFixed: (height: number) => void;
    cancelFixed: () => void;
    draftAdd: (pos: Vec) => void;
    draftFinish: () => void;
    draftCancel: () => void;

    update: (id: string, patch: Partial<Constraint>) => void;
    moveVertex: (id: string, index: number | null, pos: Vec) => void;
    remove: (id: string) => void;
    undo: () => void;
    redo: () => void;
}

const snap = (s: EditorState) => ({
    constraints: {...s.constraints},
    order: [...s.order],
});

export const useEditor = create<EditorState>((set, get) => {
    const commit = () =>
        set((s) => ({past: [...s.past, snap(s)].slice(-100), future: []}));

    const add = (c: Constraint) => {
        commit();
        set((s) => ({
            constraints: {...s.constraints, [c.id]: c},
            order: [...s.order, c.id],
            selection: c.id,
        }));
    };

    return {
        size: 512,
        tool: "select",
        selection: null,
        constraints: {},
        order: [],
        hidden: {},
        draft: null,
        pendingFixed: null,
        cursor: null,
        past: [],
        future: [],
        status: "",

        setTool: (tool) =>
            set({tool, draft: null, pendingFixed: null, status: ""}),
        select: (selection) => set({selection}),
        setCursor: (cursor) => set({cursor}),
        setStatus: (status) => set({status}),
        toggleHidden: (id) =>
            set((s) => {
                const hidden = {...s.hidden};
                if (hidden[id]) delete hidden[id];
                else hidden[id] = true;
                return {hidden};
            }),

        placePeak: (pos) => add({id: newId(), type: "peak", pos}),

        requestFixed: (pos) => set({pendingFixed: pos}),
        confirmFixed: (height) => {
            const pos = get().pendingFixed;
            if (!pos) return;
            set({pendingFixed: null});
            add({id: newId(), type: "fixed", pos, height});
        },
        cancelFixed: () => set({pendingFixed: null}),

        draftAdd: (pos) =>
            set((s) => ({draft: [...(s.draft ?? []), pos]})),
        draftFinish: () => {
            const d = get().draft;
            set({draft: null});
            if (d && d.length >= 2) add({id: newId(), type: "river", points: d});
        },
        draftCancel: () => set({draft: null}),

        update: (id, patch) => {
            commit();
            set((s) => ({
                constraints: {
                    ...s.constraints,
                    [id]: {...s.constraints[id], ...patch} as Constraint,
                },
            }));
        },

        // index null = move a point constraint; number = move a river vertex.
        // NOTE: callers commit() implicitly via update -- but drags should
        // snapshot once per gesture, so MapView calls beginGesture() pattern:
        // we approximate by committing only when `gesture` flag flips.
        moveVertex: (id, index, pos) =>
            set((s) => {
                const c = s.constraints[id];
                if (!c) return {};
                if (c.type === "river" && index != null) {
                    const points = c.points.map((p, i) =>
                        i === index ? {...p, x: pos.x, y: pos.y} : p,
                    );
                    return {constraints: {...s.constraints, [id]: {...c, points}}};
                }
                if (c.type !== "river")
                    return {constraints: {...s.constraints, [id]: {...c, pos}}};
                return {};
            }),

        remove: (id) => {
            commit();
            set((s) => {
                const constraints = {...s.constraints};
                delete constraints[id];
                return {
                    constraints,
                    order: s.order.filter((o) => o !== id),
                    selection: s.selection === id ? null : s.selection,
                };
            });
        },

        undo: () =>
            set((s) => {
                const prev = s.past[s.past.length - 1];
                if (!prev) return {};
                return {
                    past: s.past.slice(0, -1),
                    future: [snap(s), ...s.future],
                    ...prev,
                    selection: null,
                };
            }),
        redo: () =>
            set((s) => {
                const next = s.future[0];
                if (!next) return {};
                return {
                    future: s.future.slice(1),
                    past: [...s.past, snap(s)],
                    ...next,
                    selection: null,
                };
            }),
    };
});

// One undo entry per drag gesture: call at pointerdown.
export const beginGesture = () => {
    const s = useEditor.getState();
    useEditor.setState({
        past: [...s.past, {constraints: {...s.constraints}, order: [...s.order]}],
        future: [],
    });
};