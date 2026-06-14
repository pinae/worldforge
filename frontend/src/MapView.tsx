// MapView.tsx -- the cartographer's sheet.
// Tiles: backend-rendered hillshade at /api/tiles/{z}/{x}/{y}.png
//        (sepia comes from CSS, so plain renders read as old paper).
// Overlay: one absolutely-positioned SVG; constraint positions are
//          recomputed from map state on every move/zoom, so markers keep
//          constant screen size and ordinary DOM events work.
// Coordinates: heightmap pixels (x right, y down). CRS.Simple uses
//          lat up, so latlng = [-y, x] throughout.

import {CRS} from "leaflet";
import {useCallback, useEffect, useRef, useState} from "react";
import {MapContainer, TileLayer, useMap, useMapEvents} from "react-leaflet";
import {beginGesture, useEditor} from "./store";
import type {Vec} from "./types";
import {CompassRose} from "./icons";

const toLL = (p: Vec): [number, number] => [-p.y, p.x];

export default function MapView() {
    const size = useEditor((s) => s.size);
    const [tileVersion] = useState(0); // bump after an erosion run completes
    return (
        <div className="map-frame">
            <MapContainer
                crs={CRS.Simple}
                center={[-size / 2, size / 2]}
                zoom={0}
                minZoom={-2}
                maxZoom={4}
                zoomSnap={0.5}
                attributionControl={false}
                className="map-canvas"
            >
                <TileLayer
                    url={`/api/tiles/{z}/{x}/{y}.png?v=${tileVersion}`}
                    tileSize={256}
                    minZoom={-2}
                    maxZoom={4}
                    maxNativeZoom={1}
                    minNativeZoom={-2}
                    noWrap
                />
                <InteractionLayer/>
            </MapContainer>
            <div className="compass">
                <CompassRose/>
            </div>
        </div>
    );
}

function InteractionLayer() {
    const map = useMap();
    const [, setTick] = useState(0);
    const redraw = useCallback(() => setTick((t) => t + 1), []);
    const s = useEditor();
    const drag = useRef<{ id: string; index: number | null } | null>(null);

    useMapEvents({
        move: redraw,
        zoom: redraw,
        mousemove: (e) =>
            s.setCursor({x: e.latlng.lng, y: -e.latlng.lat}),
        mouseout: () => s.setCursor(null),
        click: (e) => {
            const pos: Vec = {
                x: Math.round(e.latlng.lng * 10) / 10,
                y: Math.round(-e.latlng.lat * 10) / 10,
            };
            if (s.tool === "peak") s.placePeak(pos);
            else if (s.tool === "fixed") s.requestFixed(pos);
            else if (s.tool === "river") s.draftAdd(pos);
            else s.select(null);
        },
        dblclick: () => {
            if (s.tool === "river") s.draftFinish();
        },
    });

    useEffect(() => {
        if (s.tool === "river") map.doubleClickZoom.disable();
        else map.doubleClickZoom.enable();
    }, [s.tool, map]);

    const pt = (p: Vec) => map.latLngToContainerPoint(toLL(p));

    const startDrag =
        (id: string, index: number | null) =>
            (e: React.PointerEvent<SVGElement>) => {
                if (s.tool !== "select") return;
                e.stopPropagation();
                e.preventDefault();
                s.select(id);
                beginGesture();
                drag.current = {id, index};
                map.dragging.disable();
                const rect = map.getContainer().getBoundingClientRect();
                const onMove = (ev: PointerEvent) => {
                    if (!drag.current) return;
                    const ll = map.containerPointToLatLng([
                        ev.clientX - rect.left,
                        ev.clientY - rect.top,
                    ]);
                    useEditor
                        .getState()
                        .moveVertex(drag.current.id, drag.current.index, {
                            x: Math.round(ll.lng * 10) / 10,
                            y: Math.round(-ll.lat * 10) / 10,
                        });
                };
                const onUp = () => {
                    drag.current = null;
                    map.dragging.enable();
                    window.removeEventListener("pointermove", onMove);
                    window.removeEventListener("pointerup", onUp);
                };
                window.addEventListener("pointermove", onMove);
                window.addEventListener("pointerup", onUp);
            };

    const visible = s.order
        .map((id) => s.constraints[id])
        .filter((c) => c && !s.hidden[c.id]);

    return (
        <>
            <svg className="overlay" aria-hidden="true">
                {visible.map((c) => {
                    const sel = c.id === s.selection;
                    if (c.type === "river") {
                        const pts = c.points.map(pt);
                        const d = pts.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
                        return (
                            <g key={c.id} className={sel ? "mark sel" : "mark"}>
                                <path d={d} className="river-hit" onPointerDown={(e) => {
                                    if (s.tool !== "select") return;
                                    e.stopPropagation();
                                    s.select(c.id);
                                }}/>
                                <path d={d} className="river-line"/>
                                {pts.map((p, i) => (
                                    <circle
                                        key={i}
                                        cx={p.x}
                                        cy={p.y}
                                        r={sel ? 5 : 3.5}
                                        className={
                                            c.points[i].height != null ? "vertex pinned" : "vertex"
                                        }
                                        onPointerDown={startDrag(c.id, i)}
                                    />
                                ))}
                            </g>
                        );
                    }
                    const p = pt(c.pos);
                    return c.type === "peak" ? (
                        <g
                            key={c.id}
                            className={sel ? "mark sel" : "mark"}
                            transform={`translate(${p.x} ${p.y})`}
                            onPointerDown={startDrag(c.id, null)}
                        >
                            <path d="M0 -9 L8 6 L-8 6 Z" className="peak-mark"/>
                            <path d="M-2.5 0 L0 -4.5 L2.5 0" className="peak-snow"/>
                        </g>
                    ) : (
                        <g
                            key={c.id}
                            className={sel ? "mark sel" : "mark"}
                            transform={`translate(${p.x} ${p.y})`}
                            onPointerDown={startDrag(c.id, null)}
                        >
                            <circle r="5.5" className="fixed-mark"/>
                            <path d="M-3 0 H3 M0 -3 V3" className="fixed-cross"/>
                        </g>
                    );
                })}

                {s.draft && (
                    <g className="mark draft">
                        <path
                            d={s.draft
                                .map(pt)
                                .map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`)
                                .join(" ")}
                            className="river-line draft-line"
                        />
                        {s.draft.map((p, i) => {
                            const q = pt(p);
                            return <circle key={i} cx={q.x} cy={q.y} r="3.5" className="vertex"/>;
                        })}
                    </g>
                )}
            </svg>

            {s.pendingFixed && (
                <FixedPopover at={pt(s.pendingFixed)}/>
            )}
        </>
    );
}

function FixedPopover({at}: { at: { x: number; y: number } }) {
    const confirm = useEditor((st) => st.confirmFixed);
    const cancel = useEditor((st) => st.cancelFixed);
    const ref = useRef<HTMLInputElement>(null);
    useEffect(() => ref.current?.focus(), []);
    return (
        <div
            className="popover"
            style={{left: at.x + 12, top: at.y - 16}}
            onPointerDown={(e) => e.stopPropagation()}
        >
            <label htmlFor="fx-h">Elevation</label>
            <input
                id="fx-h"
                ref={ref}
                type="number"
                placeholder="metres"
                onKeyDown={(e) => {
                    if (e.key === "Enter") {
                        const v = Number((e.target as HTMLInputElement).value);
                        if (Number.isFinite(v)) confirm(v);
                    }
                    if (e.key === "Escape") cancel();
                    e.stopPropagation();
                }}
            />
            <span className="popover-hint">enter to record</span>
        </div>
    );
}