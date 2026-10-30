// Zentraler Zustand der Oberfläche. Daten gehören dem Dienst; hier liegen Abbilder und Ansichtszustand.
import * as api from './api.js';
import { t } from './i18n.js';
import { fmtInt, nTexts } from './util.js';

export const state = {
  ready: false,
  bootError: null,
  view: 'setup',       // beim Start: letztes Projekt und Ansicht (main.js), sonst die Einrichtung
  info: null,          // Version, Datenordner
  settings: null,
  catalog: null,       // Anbieter
  status: null,        // /api/status (alle paar Sekunden)
  setup: null,         // Einrichtungs-Checkliste
  corpora: [],
  projects: [],        // alle Projekte in fester Reihenfolge, auch archivierte (archived_at)
  projectId: null,     // aktives Projekt (nie ein archiviertes)
  presets: null,       // /api/presets
  tree: null,          // Abbild der Zotero-Bibliotheken
  keys: null,          // gespeicherte Schlüssel (maskiert)
  jobs: {},            // laufende/zuletzt beobachtete Aufträge nach ID
  toasts: [],
  modal: null,
  menu: null,          // Kontextmenü / Combobox-Liste
  popover: null,       // Quellen-Vorschau bei Belegen
  ui: {},              // Ansichtszustand je Ansicht
};

let scheduled = false;
let renderFn = () => {};
export function setRenderer(fn) { renderFn = fn; }

export function update() {
  if (scheduled) return;
  scheduled = true;
  const flush = () => { if (!scheduled) return; scheduled = false; renderFn(); };
  requestAnimationFrame(flush);
  setTimeout(flush, 150); // verborgene Fenster pausieren requestAnimationFrame
}

// Ansichtszustand. Fehlende Standardwerte werden immer ergänzt – auch wenn eine andere Ansicht den Zustand schon
// angelegt hat (z. B. ui('settings').tab = 'embedding' vor dem ersten Öffnen der Einstellungen). Sonst stürzt die
// Ansicht beim Zeichnen ab und die Oberfläche reagiert nicht mehr auf Klicks.
export function ui(id, defaults = {}) {
  const o = state.ui[id] || (state.ui[id] = {});
  for (const k in defaults) if (!(k in o)) o[k] = defaults[k];
  return o;
}

// ------------------------------------------------------------------ Meldungen & Dialoge
let toastSeq = 0;
export function toast(message, kind = 'info', timeout = 4500, action = null) {
  const id = ++toastSeq;
  state.toasts.push({ id, message, kind, action });
  update();
  if (timeout) setTimeout(() => dismiss(id), timeout);
  return id;
}
export function dismiss(id) { state.toasts = state.toasts.filter(t => t.id !== id); update(); }

export function openModal(modal) { state.modal = modal; update(); }
export function closeModal() { state.modal = null; update(); }

export function confirmDialog(title, text, { ok = t('OK'), danger = false } = {}) {
  return new Promise(resolve => {
    openModal({ title, body: text, onClose: () => resolve(false), actions: [
      { label: t('Abbrechen'), onClick: () => { closeModal(); resolve(false); } },
      { label: ok, kind: danger ? 'danger' : 'primary', onClick: () => { closeModal(); resolve(true); } },
    ] });
  });
}

// Aufruf mit Fehlermeldung als Toast
export async function run(fn, { silent = false } = {}) {
  try {
    return await fn();
  } catch (err) {
    if (!silent) toast(err.message || String(err), 'error', 8000);
    throw err;
  }
}

// ------------------------------------------------------------------ Daten laden
// Indexierläufe, die beim letzten Abruf liefen: endet einer, meldet die Oberfläche das Ergebnis – in jeder Ansicht
const runningIndexJobs = new Set();
const runningCatalogJobs = new Set();  // Abgleich des Suchkatalogs: danach Korpora neu laden
// Von der Oberfläche gestartete Läufe gleich vormerken (ein kurzer Lauf kann zwischen zwei Abrufen enden)
export function trackIndexJob(id) { runningIndexJobs.add(id); }

// Vor einem Lauf von Hand (registriert in duplicates.js): neue Dubletten im Umfang abfragen; false = abgebrochen
let beforeIndexHandler = null;
export function setBeforeIndexHandler(fn) { beforeIndexHandler = fn; }

// Indexierlauf starten. Läuft schon einer, reiht der Dienst den neuen in die Warteschlange ein (Antwort „queued“):
// dann Hinweis statt Fehlermeldung. Ergebnis: der gestartete Auftrag, null (wartet) oder false (abgebrochen).
// Die Rückfrage zu Dubletten kommt beim Klick – ein wartender Lauf unterbricht später nie.
export async function submitIndexRun(path, body = {}) {
  if (beforeIndexHandler && !(await beforeIndexHandler(path, body))) return false;
  const r = await run(() => api.post(path, body));
  if (r.queued) {
    const show = state.view === 'index' ? null : { label: t('Anzeigen'), onClick: () => { state.view = 'index'; update(); } };
    toast(r.duplicate ? t('Dieser Auftrag wartet schon in der Warteschlange (Platz {n}).', { n: r.position })
      : t('Es läuft bereits eine Indexierung – der Auftrag wartet in der Warteschlange (Platz {n}).', { n: r.position }), 'info', 6000, show);
    // Neu aufgenommen: hinten anhängen (ein schon wartender Auftrag behält seinen Platz)
    const q = state.status && (state.status.index_queue || []);
    if (q && !q.some(e => e.id === r.entry.id)) state.status.index_queue = [...q, r.entry];
    update();
    return null;
  }
  state.jobs[r.id] = r;
  trackIndexJob(r.id);
  update();
  return r;
}

// Warteschlange ändern: Platz tauschen (delta −1/+1) oder Eintrag entfernen
export async function moveQueued(id, delta) {
  const r = await run(() => api.post(`/api/index/queue/${id}/move`, { delta }));
  if (state.status) state.status.index_queue = r.queue;
  update();
}

export async function removeQueued(id) {
  const r = await run(() => api.del(`/api/index/queue/${id}`));
  if (state.status) state.status.index_queue = r.queue;
  update();
}

function notifyIndexDone(j) {
  const c = j.counters || {};
  const n = c.docs_done || 0;
  const chunks = c.chunks_embedded || 0;
  const show = { label: t('Anzeigen'), onClick: () => { state.view = 'index'; update(); } };
  if (j.status === 'error') { toast(t('Indexierung abgebrochen: {e}', { e: j.error }), 'error', 12000, show); return; }
  if (j.status === 'cancelled') { toast(t('Indexierung abgebrochen. Bereits verarbeitete Texte bleiben im Index.'), 'warning', 6000, show); return; }
  if (j.status !== 'done') return;
  if (!n && !chunks) {
    if (c.trigger !== 'background') toast(t('Alle Texte sind aktuell.'), 'success', 4000);
    return;
  }
  const p = c.problems || 0;
  const embedOnly = c.embedded_docs && !c.read_docs;
  const text = c.stopped ? c.stopped
    : embedOnly ? t('Einbetten fertig: {t} für {m} eingebettet ({c} Abschnitte).', { t: nTexts(c.embedded_docs), m: c.model || '', c: fmtInt(chunks) })
      : t('Indexierung fertig: {t} verarbeitet, {c} Abschnitte eingebettet.', { t: nTexts(n), c: fmtInt(chunks) })
        + (p ? ' ' + t('Davon ohne Text oder mit Fehler: {p}.', { p }) : '');
  toast(text, p ? 'warning' : 'success', 9000, state.view === 'index' ? null : show);
}

export async function loadStatus() {
  try {
    state.status = await api.get('/api/status');
    const running = new Set(state.status.jobs.map(j => j.id));
    for (const j of state.status.jobs) state.jobs[j.id] = j;
    let ended = false;  // Indexierung oder Abgleich beendet (auch im Hintergrund): Zahlen der Korpora sind veraltet
    for (const id of [...runningIndexJobs]) {
      if (running.has(id)) continue;
      runningIndexJobs.delete(id);
      ended = true;
      api.get(`/api/jobs/${id}`).then(x => { state.jobs[x.id] = x; notifyIndexDone(x); update(); }).catch(() => {});
    }
    for (const id of [...runningCatalogJobs]) {
      if (!running.has(id)) { runningCatalogJobs.delete(id); ended = true; }
    }
    for (const j of state.status.jobs) {
      if (j.kind === 'index') runningIndexJobs.add(j.id);
      if (j.kind === 'catalog') runningCatalogJobs.add(j.id);
    }
    if (ended) loadCorpora();
    // Aufträge, die inzwischen beendet sind, aber von niemandem beobachtet wurden: Endstand nachladen
    for (const j of Object.values(state.jobs)) {
      if (['queued', 'running'].includes(j.status) && !running.has(j.id)) {
        api.get(`/api/jobs/${j.id}`).then(x => { state.jobs[x.id] = x; update(); }).catch(() => { delete state.jobs[j.id]; update(); });
      }
    }
  } catch (err) {
    state.status = null;
  }
  update();
}

export async function loadSetup() {
  try { state.setup = await api.get('/api/setup'); } catch { /* Dienst nicht erreichbar */ }
  update();
}

export async function loadCorpora() {
  try { state.corpora = (await api.get('/api/corpora')).corpora; } catch { /* s. o. */ }
  update();
}

// ------------------------------------------------------------------ Projekte
export async function loadProjects() {
  try { state.projects = (await api.get('/api/projects')).projects; } catch { /* Dienst nicht erreichbar */ }
  const open = openProjects();
  if (!open.find(p => p.id === state.projectId)) {
    let saved = null;
    try { saved = Number(localStorage.getItem('zllm.project')); } catch { /* privat */ }
    const recent = [...open].sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0))[0];
    state.projectId = (open.find(p => p.id === saved) || recent || {}).id ?? null;
  }
  update();
  return state.projects;
}

// Offene (nicht archivierte) bzw. archivierte Projekte
export function openProjects() { return state.projects.filter(p => !p.archived_at); }
export function archivedProjects() { return state.projects.filter(p => p.archived_at); }

export function project() {
  return state.projects.find(p => p.id === state.projectId) || null;
}

// Korpora des aktiven Projekts
export function projectCorpora() {
  const p = project();
  if (!p) return [];
  return state.corpora.filter(c => p.corpus_ids.includes(c.id));
}

export async function openProject(id) {
  state.projectId = id;
  try { localStorage.setItem('zllm.project', String(id)); } catch { /* privat */ }
  for (const k of ['ask', 'review', 'corpora', 'start']) delete state.ui[k];  // Ansichten neu aufbauen
  update();
  const r = await api.post(`/api/projects/${id}/open`).catch(() => null);
  await loadProjects();
  // Projekt mit eigenem Embedding-Modell: der Dienst hat umgestellt – loadSettings meldet den Wechsel
  if (r && r.embedding_switched) {
    toast(t('Embedding-Modell des Projekts aktiviert: {m}', { m: r.embedding_switched.model }), 'info', 6000);
    await loadSettings();
  }
}

export async function loadPresets() {
  try { state.presets = await api.get('/api/presets'); } catch { /* s. o. */ }
  update();
  return state.presets;
}

// ------------------------------------------------------------------ Wechsel des Embedding-Modells
// Jede Anzeige mit Zahlen des alten Modells neu laden und (über den registrierten Dialog) erklären, was zu tun ist
const EMB_KEYS = ['provider', 'model', 'query_prefix', 'document_prefix', 'dimensions'];
let embeddingChangeHandler = null;
export function setEmbeddingChangeHandler(fn) { embeddingChangeHandler = fn; }

// Auch ohne geänderte Einstellung kann der Index wechseln (z. B. neue Präfixe des aktiven Modells)
export function resetEmbeddingViews() {
  for (const id of ['settings', 'embmodels']) if (state.ui[id]) { state.ui[id].spaces = null; }
  if (state.ui.embmodels) { state.ui.embmodels.data = null; state.ui.embmodels.adopt = null; }
  if (state.ui.index) { state.ui.index.overviewAt = 0; state.ui.index.docsFor = null; }
  loadStatus(); loadSetup(); loadCorpora();
}

function embeddingChanged(prev, next) {
  if (!prev || !next || EMB_KEYS.every(k => prev[k] === next[k])) return;
  resetEmbeddingViews();
  if (embeddingChangeHandler) embeddingChangeHandler(prev, next);
}

export async function loadSettings() {
  const prev = state.settings && state.settings.embedding;
  state.settings = await api.get('/api/settings');
  embeddingChanged(prev, state.settings.embedding);
  update();
  return state.settings;
}

export async function saveSettings(patch, { quiet = true } = {}) {
  const prev = state.settings && state.settings.embedding;
  state.settings = await run(() => api.put('/api/settings', patch));
  if (!quiet) toast(t('Gespeichert'), 'success', 2000);
  if (state.presets && (patch.retrieval || (patch.llm && 'effort' in patch.llm))) loadPresets();  // „geändert“ aktualisieren
  embeddingChanged(prev, state.settings.embedding);
  update();
  return state.settings;
}

export async function loadKeys() {
  state.keys = await api.get('/api/keys');
  update();
  return state.keys;
}

// Auftrag beobachten, bis er endet. onUpdate erhält jeden Zwischenstand.
export function watchJob(id, onUpdate) {
  return new Promise(resolve => {
    const tick = async () => {
      let j;
      try { j = await api.get(`/api/jobs/${id}`); } catch { setTimeout(tick, 2500); return; }
      state.jobs[id] = j;
      if (onUpdate) onUpdate(j);
      update();
      if (['done', 'error', 'cancelled'].includes(j.status)) { loadStatus(); resolve(j); }
      else setTimeout(tick, 1000);
    };
    tick();
  });
}

export function runningJob(kind) {
  return Object.values(state.jobs).find(j => j.kind === kind && ['queued', 'running'].includes(j.status)) || null;
}

export function providerLabel(id) {
  const label = (state.catalog && state.catalog.providers.find(p => p.id === id) || {}).label;
  return label ? t(label) : id;
}
