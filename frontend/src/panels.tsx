// panels.tsx -- the furniture around the map: toolbar (left), outliner +
// inspector (right), status bar (bottom).

import {useEditor} from "./store";
import type {Constraint, RiverC, Tool} from "./types";
import {describe, toPayload, TOOL_HINTS} from "./types";
import {
    EyeIcon, PeakIcon, QuillIcon, RedoIcon, RiverIcon, RunIcon,
    SurveyIcon, UndoIcon,
} from "./icons";

const TOOL_DEFS: { tool: Tool; label: string; key: string; icon: () => JSX.Element }[] = [
    {tool: "select", label: "Select", key: "V", icon: QuillIcon},
    {tool: "peak", label: "Peak", key: "P", icon: PeakIcon},
    {tool: "river", label: "River", key: "R", icon: RiverIcon},
    {tool: "fixed", label: "Fixed point", key: "F", icon: SurveyIcon},
];

export function Toolbar() {
    const tool = useEditor((s) => s.tool);
    const setTool = useEditor((s) => s.setTool);
    const {undo, redo, past, future} = useEditor();
    const run = useRunErosion();
    return (
        <nav className="toolbar" aria-label="Tools">
            {TOOL_DEFS.map(({tool: t, label, key, icon: Icon}) => (
                <button
                    key={t}
                    className={tool === t ? "tool active" : "tool"}
                    title={`${label} (${key})`}
                    aria-label={label}
                    aria-pressed={tool === t}
                    onClick={() => setTool(t)}
                >
                    <Icon/>
                </button>
            ))}
            <div className="toolbar-rule"/>
            <button className="tool" title="Undo (ctrl+z)" aria-label="Undo"
                    onClick={undo} disabled={!past.length}><UndoIcon/></button>
            <button className="tool" title="Redo (ctrl+shift+z)" aria-label="Redo"
                    onClick={redo} disabled={!future.length}><RedoIcon/></button>
            <div className="toolbar-spacer"/>
            <button className="tool run" title="Run erosion" aria-label="Run erosion"
                    onClick={run}><RunIcon/></button>
        </nav>
    );
}

function useRunErosion() {
    const setStatus = useEditor((s) => s.setStatus);
    return async () => {
        const s = useEditor.getState();
        setStatus("Dispatching the expedition\u2026");
        try {
            const res = await fetch("/api/runs/", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({constraints: toPayload(s.order.map((id) => s.constraints[id]))}),
            });
            setStatus(res.ok ? "Erosion under way \u2014 the map will redraw itself."
                : `The expedition failed (${res.status}).`);
        } catch {
            setStatus("No word from the backend \u2014 is the server running?");
        }
    };
}

export function Outliner() {
    const s = useEditor();
    const items = s.order.map((id) => s.constraints[id]).filter(Boolean);
    return (
        <section className="panel outliner" aria-label="Placed constraints">
            <h2>Marks on the map</h2>
            {items.length === 0 && (
                <p className="empty">An unmarked land. Choose a tool and click the map
                    to place your first constraint.</p>
            )}
            <ul>
                {items.map((c) => (
                    <li
                        key={c.id}
                        className={c.id === s.selection ? "row sel" : "row"}
                        onClick={() => s.select(c.id)}
                    >
                        <span className={`swatch ${c.type}`} aria-hidden="true"/>
                        <span className="row-label">{describe(c)}</span>
                        <button
                            className="ghost"
                            aria-label={s.hidden[c.id] ? "Show" : "Hide"}
                            onClick={(e) => {
                                e.stopPropagation();
                                s.toggleHidden(c.id);
                            }}
                        >
                            <EyeIcon closed={!!s.hidden[c.id]}/>
                        </button>
                    </li>
                ))}
            </ul>
        </section>
    );
}

export function Inspector() {
    const s = useEditor();
    const c = s.selection ? s.constraints[s.selection] : null;
    return (
        <section className="panel inspector" aria-label="Inspector">
            <h2>Surveyor's notes</h2>
            {!c ? (
                <p className="empty">Select a mark to read its particulars.</p>
            ) : (
                <ConstraintForm c={c}/>
            )}
        </section>
    );
}

function ConstraintForm({c}: { c: Constraint }) {
    const update = useEditor((s) => s.update);
    const remove = useEditor((s) => s.remove);
    return (
        <div className="form">
            {c.type !== "river" && (
                <div className="field">
                    <label htmlFor="ins-h">
                        Elevation {c.type === "peak" && <em>(blank = let erosion decide)</em>}
                    </label>
                    <input
                        id="ins-h"
                        type="number"
                        value={(c as { height?: number }).height ?? ""}
                        placeholder="metres"
                        onChange={(e) => {
                            const v = e.target.value === "" ? undefined : Number(e.target.value);
                            if (c.type === "fixed" && v == null) return; // required here
                            update(c.id, {height: v} as Partial<Constraint>);
                        }}
                    />
                </div>
            )}
            {c.type === "river" && <RiverForm c={c}/>}
            <button className="danger" onClick={() => remove(c.id)}>
                Strike from the map
            </button>
        </div>
    );
}

function RiverForm({c}: { c: RiverC }) {
    const update = useEditor((s) => s.update);
    const setVertexHeight = (i: number, v: number | undefined) =>
        update(c.id, {
            points: c.points.map((p, j) => (j === i ? {...p, height: v} : p)),
        });
    return (
        <>
            <div className="field">
                <label>Course · {c.points.length} points, source to mouth</label>
                <button
                    onClick={() => update(c.id, {points: [...c.points].reverse()})}
                >
                    Reverse flow
                </button>
            </div>
            <div className="field">
                <label>Pinned elevations <em>(optional, per vertex)</em></label>
                <ol className="vertices">
                    {c.points.map((p, i) => (
                        <li key={i}>
                            <span>pt {i + 1}</span>
                            <input
                                type="number"
                                value={p.height ?? ""}
                                placeholder="auto"
                                onChange={(e) =>
                                    setVertexHeight(
                                        i,
                                        e.target.value === "" ? undefined : Number(e.target.value),
                                    )
                                }
                            />
                        </li>
                    ))}
                </ol>
            </div>
        </>
    );
}

export function StatusBar() {
    const s = useEditor();
    const hint = s.draft ? TOOL_HINTS.river : TOOL_HINTS[s.tool];
    return (
        <footer className="statusbar">
            <span className="status-tool">{s.tool}</span>
            <span className="status-hint">{s.status || hint}</span>
            <span className="status-coords">
        {s.cursor
            ? `x ${s.cursor.x.toFixed(0)} \u00b7 y ${s.cursor.y.toFixed(0)}`
            : "\u2014"}
      </span>
        </footer>
    );
}