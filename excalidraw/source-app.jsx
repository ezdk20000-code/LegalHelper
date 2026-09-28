import React, { useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw, serializeAsJSON, convertToExcalidrawElements, MainMenu } from "@excalidraw/excalidraw";
import "./node_modules/@excalidraw/excalidraw/dist/prod/index.css";

let api = null, dirty = false, loading = false, lastSig = "";
const BRANCHES = [
  ["Факты и хронология", "#a5d8ff"], ["Позиция доверителя", "#b2f2bb"], ["Позиция оппонента", "#ffc9c9"],
  ["Доказательства", "#ffec99"], ["Риски", "#ffa8a8"], ["Процесс и сроки", "#d0bfff"],
];

function mindmap(title) {
  const cx = 0, cy = 0, R = 360, sk = [];
  sk.push({ type: "ellipse", id: "center", x: cx - 150, y: cy - 60, width: 300, height: 120,
            backgroundColor: "#e7f5ff", strokeWidth: 2, fillStyle: "solid",
            label: { text: title || "Дело", fontSize: 22, fontFamily: 6 } });
  BRANCHES.forEach(([name, color], i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / BRANCHES.length;
    const x = cx + R * 1.35 * Math.cos(a), y = cy + R * Math.sin(a);
    const id = "b" + i;
    sk.push({ type: "rectangle", id, x: x - 110, y: y - 40, width: 220, height: 80, backgroundColor: color,
              fillStyle: "solid", roundness: { type: 3 }, label: { text: name, fontSize: 18, fontFamily: 6 } });
    // стрелка от края эллипса до края блока
    const dx = x - cx, dy = y - cy, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L;
    const t1 = 1 / Math.sqrt((ux / 158) ** 2 + (uy / 68) ** 2);
    const t2 = Math.min(Math.abs(118 / (ux || 1e-9)), Math.abs(48 / (uy || 1e-9)));
    const sx = cx + ux * t1, sy = cy + uy * t1, ex = x - ux * t2, ey = y - uy * t2;
    sk.push({ type: "arrow", x: sx, y: sy, width: ex - sx, height: ey - sy, start: { id: "center" }, end: { id },
              strokeColor: "#868e96", strokeWidth: 2 });
  });
  return convertToExcalidrawElements(sk);
}

function App() {
  const [theme, setTheme] = useState(window.__initTheme || "light");
  useEffect(() => { window.__setThemeReact = setTheme; }, []);
  return (
    <Excalidraw
      excalidrawAPI={(a) => { api = a; }}
      langCode="ru-RU"
      theme={theme}
      UIOptions={{ canvasActions: { loadScene: true, saveToActiveFile: false, toggleTheme: false,
                                     export: { saveFileToDisk: true } } }}
      onChange={(els, st, files) => {
        if (loading) return;
        const sig = els.reduce((s, e) => s + e.version, 0) + ":" + els.length + ":" + Object.keys(files || {}).length;
        if (sig !== lastSig) { lastSig = sig; dirty = true; }
      }}>
      <MainMenu>
        <MainMenu.DefaultItems.LoadScene />
        <MainMenu.DefaultItems.Export />
        <MainMenu.DefaultItems.SaveAsImage />
        <MainMenu.DefaultItems.SearchMenu />
        <MainMenu.DefaultItems.ClearCanvas />
        <MainMenu.Separator />
        <MainMenu.DefaultItems.ChangeCanvasBackground />
      </MainMenu>
    </Excalidraw>);
}

function waitApi() {
  return new Promise((res) => { const t = () => (api ? res(api) : setTimeout(t, 30)); t(); });
}

window.PM = {
  async load(sceneJson, theme, title) {
    await waitApi();
    loading = true;
    let data = null;
    try { data = sceneJson ? JSON.parse(sceneJson) : null; } catch (e) { data = null; }
    if (data && Array.isArray(data.elements)) {
      if (data.files) api.addFiles(Object.values(data.files));
      api.updateScene({ elements: data.elements,
                        appState: { viewBackgroundColor: (data.appState || {}).viewBackgroundColor || undefined } });
    } else {
      api.updateScene({ elements: mindmap(title) });
    }
    api.updateScene({ appState: { currentItemFontFamily: 6 } });
    api.history && api.history.clear && api.history.clear();
    window.PM.setTheme(theme);
    setTimeout(() => { api.scrollToContent(undefined, { fitToViewport: true, viewportZoomFactor: 0.72 }); }, 60);
    setTimeout(() => { loading = false; dirty = !data; lastSig = ""; }, 200);
    return true;
  },
  newMindmap(title) {
    if (!api) return false;
    api.updateScene({ elements: mindmap(title) });
    setTimeout(() => api.scrollToContent(undefined, { fitToViewport: true, viewportZoomFactor: 0.72 }), 60);
    dirty = true;
    return true;
  },
  takeIfDirty() {
    if (!api || !dirty || loading) return null;
    dirty = false;
    return serializeAsJSON(api.getSceneElements(), api.getAppState(), api.getFiles(), "local");
  },
  getScene() {
    if (!api) return null;
    return serializeAsJSON(api.getSceneElements(), api.getAppState(), api.getFiles(), "local");
  },
  setTheme(t) { window.__initTheme = t; if (window.__setThemeReact) window.__setThemeReact(t === "dark" ? "dark" : "light"); },
};

window.EXCALIDRAW_ASSET_PATH = window.EXCALIDRAW_ASSET_PATH || "./";
createRoot(document.getElementById("root")).render(<App />);
