// Start der Oberfläche: Daten laden, Zeichnen, regelmässig den Zustand des Dienstes abfragen.
import { render } from './core/vdom.js';
import { state, update, ui, setRenderer, loadStatus, loadSetup, loadCorpora, loadSettings, loadKeys, loadProjects, loadPresets, projectCorpora, toast, runningJob, openProject } from './core/store.js';
import * as api from './core/api.js';
import { t, setLanguage, language } from './core/i18n.js';
import { shell, handleKey, handleClick, navigate, VIEWS, GLOBAL_VIEWS } from './views/shell.js';
import { checkUpdates, installUpdate } from './views/settings.js';

const VALID_VIEWS = ['setup', ...[...VIEWS, ...GLOBAL_VIEWS].map(v => v.id)];
const root = document.getElementById('app');
const dark = window.matchMedia('(prefers-color-scheme: dark)');

function applyTheme() {
  const pref = state.settings ? state.settings.appearance : null;
  if (!pref) return;
  const mode = pref === 'system' ? (dark.matches ? 'dark' : 'light') : pref;
  if (document.documentElement.dataset.theme !== mode) document.documentElement.dataset.theme = mode;
  try { localStorage.setItem('zllm.appearance', pref); } catch { /* privat */ }
  applyTitleBar(mode);
}

// Programmfenster: die Titelleiste von Windows in den Farben der Oberfläche (Leiste wie die Kopfzeile, Schrift,
// Rahmen); Windows 10 übernimmt nur hell/dunkel. Nur nach einem Wechsel des Farbschemas neu setzen.
let titleBarMode = null;
function applyTitleBar(mode) {
  const d = window.pywebview && window.pywebview.api;
  if (!d || !d.set_title_bar || titleBarMode === mode) return;
  titleBarMode = mode;
  const css = getComputedStyle(document.documentElement);
  const v = name => css.getPropertyValue(name).trim();
  Promise.resolve(d.set_title_bar(mode !== 'light', v('--surface'), v('--ink'), v('--line'))).catch(() => { titleBarMode = null; });
}

function applyLanguage() {
  const lang = state.settings && state.settings.language;
  if (lang && lang !== language()) {
    setLanguage(lang);
    try { localStorage.setItem('zllm.language', lang); } catch { /* privat */ }
    // Meldungen des Dienstes (Einrichtung, Status) kommen in der Sprache der Einstellung
    if (state.ready) { loadSetup(); loadStatus(); }
  }
}

setRenderer(() => {
  applyTheme();
  applyLanguage();
  render(shell(), root);
});
dark.addEventListener('change', update);
window.addEventListener('pywebviewready', update);  // Programmfenster: Desktop-Funktionen sind jetzt da
document.addEventListener('keydown', handleKey);
document.addEventListener('click', handleClick);
// Fehler, die ausserhalb des Zeichnens auftreten, ins Protokoll des Dienstes schreiben
window.addEventListener('error', e => { api.post('/api/client-error', { part: 'window', message: String(e.message), stack: String(e.error && e.error.stack || '') }).catch(() => {}); });
window.addEventListener('unhandledrejection', e => { api.post('/api/client-error', { part: 'promise', message: String(e.reason && e.reason.message || e.reason), stack: String(e.reason && e.reason.stack || '') }).catch(() => {}); });

// Aufruf aus Zotero (Plugin) oder per Adresse: ?view=ask&collection=users/0:KEY | &items=lib:K1,lib:K2 | &corpus=3
export async function openWith(params) {
  const p = params instanceof URLSearchParams ? Object.fromEntries(params) : params || {};
  const view = p.view || p.tab;
  const ask = ui('ask', {});
  if (p.corpus) { ask.corpora = [Number(p.corpus)]; ask.scope = null; }
  if (p.collection) {
    const corpus = projectCorpora().find(c => c.sources.length === 1 && c.sources[0] === p.collection);
    if (corpus) { ask.corpora = [corpus.id]; ask.scope = null; } else {
      ask.scope = { label: t('Sammlung aus Zotero'), filters: { collections: [p.collection] } };
      api.get(`/api/zotero/describe?sources=${encodeURIComponent(p.collection)}`).then(r => {
        const d = r.sources[0];
        if (d && ask.scope && ask.scope.filters.collections) { ask.scope.label = d.path || d.label; update(); }
      }).catch(() => {});
    }
  }
  if (p.items) {
    const items = String(p.items).split(',').filter(Boolean);
    ask.scope = { label: t('{n} Einträge aus Zotero', { n: items.length }), filters: { item_keys: items } };
  }
  if (view && VALID_VIEWS.includes(view)) navigate(view);
  else if (p.collection || p.items) navigate('ask');
  update();
}
window.zllmOpen = openWith;  // vom Programmfenster aus aufrufbar

let pollTimer = null;
function poll() {
  clearTimeout(pollTimer);
  let n = 0;
  const tick = async () => {
    n += 1;
    if (!document.hidden) {
      await loadStatus();
      if (n % 4 === 0) loadSetup();
      if (n % 8 === 0) loadProjects();
      if (runningJob('index') && n % 2 === 0) loadCorpora();
    }
    pollTimer = setTimeout(tick, state.status ? 4000 : 2000);
  };
  pollTimer = setTimeout(tick, 4000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.ready) { loadStatus(); loadSetup(); } });

async function boot() {
  try { const saved = localStorage.getItem('zllm.language'); if (saved) setLanguage(saved); } catch { /* privat */ }
  update();
  try {
    const [info, catalog] = await Promise.all([api.get('/api/app/info'), api.get('/api/catalog')]);
    state.info = info;
    state.catalog = catalog;
    await loadSettings();
  } catch (err) {
    state.bootError = t('Der ZotLLM-Dienst antwortet nicht ({e}). Neuer Versuch …', { e: err.message });
    update();
    setTimeout(boot, 2500);
    return;
  }
  applyLanguage();
  await Promise.all([loadStatus(), loadSetup(), loadCorpora(), loadProjects(), loadPresets(), loadKeys().catch(() => {})]);
  // Weiter, wo zuletzt gearbeitet wurde: im zuletzt offenen Projekt und in dessen letzter Ansicht. Die Einrichtung
  // kommt zuerst, solange dort Schritte offen sind oder es kein offenes Projekt gibt. Ein Aufruf aus Zotero (?view=…)
  // springt danach direkt in die gewünschte Ansicht
  const openSteps = state.setup ? state.setup.steps.filter(s => !s.done && !s.optional).length : 1;
  let lastView = null;
  try { lastView = localStorage.getItem('zllm.view'); } catch { /* privat */ }
  if (state.projectId && !openSteps) {
    await openProject(state.projectId);
    state.view = VIEWS.some(v => v.id === lastView) ? lastView : 'start';
  } else {
    state.view = 'setup';
  }
  state.ready = true;
  state.bootError = null;
  const params = new URLSearchParams(location.search);
  if ([...params.keys()].length) {
    await openWith(params);
    history.replaceState(null, '', location.pathname);
  }
  update();
  poll();
  if (state.settings.check_updates_on_start && state.settings.update_url) {
    setTimeout(async () => {
      const u = await checkUpdates(true);
      if (u && u.available) toast(t('ZotLLM {v} ist verfügbar.', { v: u.latest }), 'info', 0, { label: t('Aktualisieren'), onClick: () => installUpdate(u) });
    }, 5000);
  }
}

boot();
