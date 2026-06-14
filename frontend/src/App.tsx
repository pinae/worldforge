// App.tsx -- layout: toolbar | map | (outliner over inspector), status bar
// across the bottom. Keyboard: V/P/R/F tools, Enter/Esc for river capture,
// Del removes selection, ctrl+z / ctrl+shift+z (or ctrl+y) undo/redo.

import {useEffect} from "react";
import MapView from "./MapView";
import {Inspector, Outliner, StatusBar, Toolbar} from "./panels";
import {useEditor} from "./store";

export default function App() {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const s = useEditor.getState();
            const tag = (e.target as HTMLElement)?.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA") return;

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
                e.preventDefault();
                e.shiftKey ? s.redo() : s.undo();
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
                e.preventDefault();
                s.redo();
                return;
            }
            switch (e.key) {
                case "v":
                case "V":
                    s.setTool("select");
                    break;
                case "p":
                case "P":
                    s.setTool("peak");
                    break;
                case "r":
                case "R":
                    s.setTool("river");
                    break;
                case "f":
                case "F":
                    s.setTool("fixed");
                    break;
                case "Enter":
                    if (s.draft) s.draftFinish();
                    break;
                case "Escape":
                    if (s.draft) s.draftCancel();
                    else if (s.pendingFixed) s.cancelFixed();
                    else s.setTool("select");
                    break;
                case "Delete":
                case "Backspace":
                    if (s.selection) s.remove(s.selection);
                    break;
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    return (
        <div className="app">
            <Toolbar/>
            <main className="map-area">
                <MapView/>
            </main>
            <aside className="side">
                <Outliner/>
                <Inspector/>
            </aside>
            <StatusBar/>
        </div>
    );
}