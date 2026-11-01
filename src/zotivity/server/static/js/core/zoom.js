// Zoom der ganzen Oberfläche im Programmfenster: Regler in der Statusleiste, Strg + Mausrad, Pinch auf dem Touchpad (kommt
// als Strg + Mausrad an) und Strg +/−/0. Der Wert bleibt über den Neustart. Im Browser zoomt der Browser selbst.
import { update } from './store.js';

export const ZOOMS = [70, 80, 90, 100, 110, 125, 150, 175, 200];
const KEY = 'zllm.zoom';
let zoom = 100;
try { zoom = Number(localStorage.getItem(KEY)) || 100; } catch { /* privat */ }

const desktop = () => (window.pywebview && window.pywebview.api) || null;
export const canZoom = () => !!(desktop() && desktop().set_zoom);
export const currentZoom = () => zoom;

export function applyZoom() {
  if (canZoom() && zoom !== 100) Promise.resolve(desktop().set_zoom(zoom / 100)).catch(() => {});
}

export function setZoom(value) {
  zoom = value;
  try { localStorage.setItem(KEY, String(zoom)); } catch { /* privat */ }
  if (canZoom()) Promise.resolve(desktop().set_zoom(zoom / 100)).catch(() => {});
  update();
}

export function stepZoom(dir) {
  const next = dir > 0 ? ZOOMS.find(z => z > zoom) : [...ZOOMS].reverse().find(z => z < zoom);
  if (next) setZoom(next);
}

export function installZoom() {
  let sum = 0;
  let last = 0;
  window.addEventListener('wheel', e => {
    if (!e.ctrlKey || !canZoom()) return;
    e.preventDefault();
    // Pinch liefert viele kleine Schritte: erst ab einer spürbaren Bewegung eine Stufe, höchstens alle 120 ms
    sum += e.deltaY;
    const now = performance.now();
    if (Math.abs(sum) < 40 || now - last < 120) return;
    stepZoom(sum < 0 ? 1 : -1);
    sum = 0;
    last = now;
  }, { passive: false });
  window.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || !canZoom()) return;
    if (e.key === '+' || e.key === '=') stepZoom(1);
    else if (e.key === '-') stepZoom(-1);
    else if (e.key === '0') setZoom(100);
    else return;
    e.preventDefault();
  });
}
