// Gemeinsamer Zustand und Laden für die Ansicht „Recherche“. Alles geht über /api/research/… – in der eigenständigen
// App wie später in Zotivity.
import { h } from '../../core/vdom.js';
import { state, update, ui, run, toast } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt } from '../../core/util.js';
import { badge, paneProps, splitter } from '../../ui/components.js';

export const R = '/api/research';

// Hinweise, Warnungen und Vorfilter-Namen kommen deutsch vom Server (das Paket research kennt keine Sprachen)
const SERVER_TEXTS = [
  [/^Titel enthält (.*)$/, a => t('Titel enthält {a}', { a })],
  [/^Titel\/Abstract enthält (.*)$/, a => t('Titel/Abstract enthält {a}', { a })],
  [/^Zeitschrift enthält (.*)$/, a => t('Zeitschrift enthält {a}', { a })],
  [/^erschienen vor (.*)$/, a => t('erschienen vor {a}', { a })],
  [/^Sprache nicht (.*)$/, a => t('Sprache nicht {a}', { a })],
  [/^andere Art als (.*)$/, a => t('andere Art als {a}', { a })],
  [/^(.+): Platzhalter \(\*\) hier nicht möglich – entfernt; Wortformen ggf\. ausschreiben\.$/, a => t('{a}: Platzhalter (*) hier nicht möglich – entfernt; Wortformen ggf. ausschreiben.', { a })],
  [/^Platzhalter entfernt \((.*)\)\. OpenAlex sucht mit Wortstämmen; Wortformen wie „teenagers“ zu „teen\*“ ggf\. ergänzen\.$/, a => t('Platzhalter entfernt ({a}). OpenAlex sucht mit Wortstämmen; Wortformen wie „teenagers“ zu „teen*“ ggf. ergänzen.', { a })],
  [/^(\S+) Treffer, geholt wurden die (\S+) relevantesten\.$/, (a, b) => t('{a} Treffer, geholt wurden die {b} relevantesten.', { a, b })],
  [/^PubMed liefert über die API höchstens (\S+) Datensätze – Suche eingrenzen\.$/, a => t('PubMed liefert über die API höchstens {a} Datensätze – Suche eingrenzen.', { a })],
  [/^swisscovery wertet mehrere Klammerblöcke nicht richtig aus: abgefragt wird der engste Block \((\S+) Treffer\); die übrigen prüft die App nach dem Abruf\. Die Trefferzahl ist eine Obergrenze\.$/, a => t('swisscovery wertet mehrere Klammerblöcke nicht richtig aus: abgefragt wird der engste Block ({a} Treffer); die übrigen prüft die App nach dem Abruf. Die Trefferzahl ist eine Obergrenze.', { a })],
];

export function serverText(text) {
  if (!text) return text;
  const exceptions = text.endsWith(' (mit Ausnahmen)');
  const s = exceptions ? text.slice(0, -' (mit Ausnahmen)'.length) : text;
  const hit = SERVER_TEXTS.map(([re, fn]) => [re.exec(s), fn]).find(([m]) => m);
  return (hit ? hit[1](...hit[0].slice(1)) : t(s)) + (exceptions ? ` ${t('(mit Ausnahmen)')}` : '');
}

export const TABS = [
  { id: 'project', label: () => t('Projekt'), icon: 'edit' },
  { id: 'databases', label: () => t('Datenbanken'), icon: 'globe' },
  { id: 'strategy', label: () => t('Suchstrategie'), icon: 'layers' },
  { id: 'search', label: () => t('Suche & Import'), icon: 'search' },
  { id: 'pool', label: () => t('Pool'), icon: 'library' },
  { id: 'folders', label: () => t('Ordner'), icon: 'folder' },
  { id: 'screening', label: () => t('Screening'), icon: 'check' },
  { id: 'handover', label: () => t('Übergabe'), icon: 'send' },
  { id: 'fulltext', label: () => t('Volltexte'), icon: 'pdf' },
];

// Namen und Fähigkeiten der Quellen kommen vom Dienst (/info); diese Liste gilt nur, bis er geantwortet hat
const FALLBACK_LABELS = { pubmed: 'PubMed', openalex: 'OpenAlex', psycinfo: 'PsycInfo', wos: 'Web of Science', ris: 'RIS' };
export function sourceLabel(id) {
  const info = rs().info;
  const s = info && info.sources.find(x => x.id === id);
  return s ? s.label : FALLBACK_LABELS[id] || id;
}
// direkt durchsuchbar (Trefferzahl und Suche in der App)
export const liveSources = () => (rs().info ? rs().info.sources.filter(x => x.live).map(x => x.id) : ['pubmed', 'openalex']);
export const isLive = id => liveSources().includes(id);
export const catalogEntry = id => ((rs().info && rs().info.catalog) || []).find(x => x.id === id);
// im Projekt gewählte Datenbanken (Tab „Datenbanken“)
export const projectSources = () => ((rs().project && rs().project.settings && rs().project.settings.sources) || ['pubmed', 'openalex']);

export const rs = () => ui('research', {
  info: null, projects: null, pid: null, project: null, tab: 'project', zotero: {},
  queries: null, runs: null, pool: null, queue: null, plan: null, flow: null, fulltext: null, busy: {}, stale: {},
});

export const enc = encodeURIComponent;

export async function loadInfo() {
  rs().info = await api.get(`${R}/info`);
}

// Jede Recherche gehört zu einem Projekt von Zotivity (settings.zotllm_project); gezeigt werden die des aktiven Projekts.
// Recherchen ohne gültiges Projekt (z. B. gelöscht) stehen unter „Ohne Projekt“ und lassen sich zuordnen.
export const zotivityProject = () => (state.projects || []).find(p => p.id === state.projectId) || null;
const ownerOf = p => (p.settings && p.settings.zotllm_project) || null;

export async function loadProjects() {
  const r = await api.get(`${R}/projects`);
  const s = rs();
  const known = new Set((state.projects || []).map(p => p.id));  // auch archivierte: deren Recherchen ruhen mit
  s.projects = r.projects.filter(p => ownerOf(p) === state.projectId);
  s.unassigned = r.projects.filter(p => !known.has(ownerOf(p)));
  s.forProject = state.projectId;
  update();
}

export async function assignProject(pid) {
  await api.put(`${R}/projects/${pid}`, { settings: { zotllm_project: state.projectId } });
  await loadProjects();
}

export async function loadProject(pid = rs().pid) {
  if (!pid) return;
  const p = await api.get(`${R}/projects/${pid}`);
  const s = rs();
  if (s.pid === pid) { s.project = p; update(); }
  return p;
}

// Nach jeder Änderung am Pool: Kopfzeile neu, abhängige Listen beim nächsten Öffnen neu laden
export async function refreshSummary() {
  const s = rs();
  if (!s.pid) return;
  try {
    const sum = await api.get(`${R}/projects/${s.pid}/summary`);
    if (s.project) s.project.summary = sum;
    update();
  } catch { /* nächstes Mal */ }
}

// Neu laden beim nächsten Zeichnen; bis dahin bleiben die bisherigen Daten stehen (kein Springen, Scrollposition bleibt)
export function invalidate(...keys) {
  const s = rs();
  for (const k of keys) if (s[k] != null) s.stale[k] = true;
}

export function needsLoad(key) {
  const s = rs();
  return s[key] == null || !!s.stale[key];
}

export function openProject(pid, tab) {
  const s = rs();
  if (s.pid !== pid) {
    flushSaves();
    Object.assign(s, { pid, project: null, queries: null, runs: null, pool: null, queue: null, plan: null, recall: null, flow: null, fulltext: null, stale: {} });
    ui('rs-screen', {}).index = 0;
  }
  if (tab) s.tab = tab;
  try { localStorage.setItem('litsearch.project', String(pid || '')); } catch { /* privat */ }
  if (pid) run(() => loadProject(pid)).catch(() => {});
  update();
}

export function closeProject() {
  openProject(null);
  loadProjects().catch(() => {});
}

// Einmal laden, solange nichts invalidiert wurde
export function lazy(key, path, map = x => x) {
  const s = rs();
  const flag = `loading:${key}`;
  if (!needsLoad(key) || s.busy[flag]) return s[key];
  s.busy[flag] = true;
  api.get(path).then(r => { s[key] = map(r); delete s.stale[key]; }).catch(err => { s[key] = undefined; toast(err.message, 'error', 8000); })
    .finally(() => { delete s.busy[flag]; update(); });
  return s[key];
}

// Mit Sperre gegen Doppelklick; Fehler als Meldung
export async function busy(key, fn) {
  const s = rs();
  if (s.busy[key]) return undefined;
  s.busy[key] = true;
  update();
  try {
    return await run(fn);
  } finally {
    delete s.busy[key];
    update();
  }
}

export const isBusy = key => !!rs().busy[key];

// Automatisch speichern: kurz nach der letzten Änderung; beim Wechsel der Ansicht und beim Schliessen des Fensters sofort.
// So geht nichts verloren, und es braucht keinen Speichern-Knopf (Projekt, Ordner, Suchstrategie).
const saves = {};
const saveMark = () => ui('rs-save', { state: '', error: '' });

async function runSave(key, opts) {
  const x = saves[key];
  if (!x || !x.fn) return;
  clearTimeout(x.timer);
  const fn = x.fn;
  x.fn = null;
  const mark = saveMark();
  mark.state = 'saving';
  try {
    await fn(opts);
    if (!Object.values(saves).some(y => y.fn)) { mark.state = 'saved'; mark.error = ''; }
  } catch (err) {
    mark.state = 'error';
    mark.error = err.message;
    toast(t('Nicht gespeichert: {e}', { e: err.message }), 'error', 8000);
  }
  update();
}

export function saveLater(key, fn, delay = 700) {
  const x = saves[key] || (saves[key] = {});
  clearTimeout(x.timer);
  x.fn = fn;
  x.timer = setTimeout(() => runSave(key), delay);
  saveMark().state = 'pending';
}

export const savePending = key => !!(saves[key] && saves[key].fn);
export function flushSaves(opts) { return Promise.all(Object.keys(saves).map(k => runSave(k, opts))); }
window.addEventListener('pagehide', () => flushSaves({ keepalive: true }));

export function saveState() {
  const m = saveMark();
  if (!m.state) return null;
  if (m.state === 'error') return h('span', { class: 'danger-text small', title: m.error }, t('Nicht gespeichert'));
  return h('span', { class: 'muted small' }, m.state === 'saved' ? t('Gespeichert') : t('Wird gespeichert …'));
}

// Arbeitsfläche: die Liste nimmt die ganze Breite, rechts ein Fenster für alles Übrige. Es passt sich dem Fenster an,
// bis man es zieht; die gezogene Breite bleibt je Ansicht.
export function workspace(id, main, side, { def = 'clamp(300px, 24vw, 560px)', min = 260, max = 900 } = {}) {
  return h('div', { class: 'rs-work' },
    h('div', { class: 'rs-work-main' }, main),
    h('aside', { class: 'rs-work-side', ...paneProps(`rs-${id}`, def) },
      h('div', { class: 'rs-work-side-inner' }, side),
      splitter(`rs-${id}`, { def, min, max, side: 'right' })));
}

// zotero://-Adresse eines Eintrags (eigene Bibliothek oder Gruppe)
export function zoteroSelect(lib, key) {
  const m = /^groups\/(\d+)$/.exec(lib || '');
  return `zotero://select/${m ? `groups/${m[1]}` : 'library'}/items/${key}`;
}

// „PubMed 503 · OpenAlex 937 · gesichtet 380/1150 · ausgewählt 71“
export function summaryLine(sum) {
  if (!sum) return '';
  const parts = Object.entries(sum.sources || {}).sort().map(([k, v]) => `${sourceLabel(k)} ${fmtInt(v)}`);
  if (sum.pool) parts.push(t('Pool {n}', { n: fmtInt(sum.pool) }));
  if (sum.visible || sum.screened) parts.push(t('gesichtet {a}/{b}', { a: fmtInt(sum.screened), b: fmtInt(sum.visible) }));
  if (sum.included) parts.push(t('ausgewählt {n}', { n: fmtInt(sum.included) }));
  if (sum.borderline) parts.push(t('Grenzfälle {n}', { n: fmtInt(sum.borderline) }));
  return parts.join(' · ') || t('noch keine Treffer');
}

// Name der Zielbibliothek für die Anzeige
export const targetName = p => (p.target_name && p.target_name !== p.target_library ? p.target_name
  : p.target_library === 'users/0' ? t('Meine Bibliothek') : p.target_library);

export function authorsShort(authors) {
  if (!authors || !authors.length) return '';
  const name = a => (Array.isArray(a) ? (a[0] || a[1]) : a);
  if (authors.length === 1) return name(authors[0]);
  if (authors.length === 2) return `${name(authors[0])} & ${name(authors[1])}`;
  return `${name(authors[0])} et al.`;
}

export function folderLabel(project, slot) {
  const f = ((project && project.folder_map) || []).find(x => String(x.slot) === String(slot));
  return f ? (f.label || f.path) : t('Ordner {n}', { n: slot });
}

export function statusBadge(decision, project) {
  if (!decision) return badge(t('offen'), 'neutral');
  if (decision.status === 'include') return badge(`${decision.folder} · ${folderLabel(project, decision.folder)}`, 'success');
  if (decision.status === 'exclude') return badge(decision.reason ? t('aus: {r}', { r: decision.reason }) : t('ausgeschlossen'), 'danger');
  if (decision.status === 'maybe') return badge(t('unsicher'), 'warning');
  return badge(decision.status, 'neutral');
}

// Kennzeichen „Grenzfall“: aus einer Regel (Ausnahmebegriff), von Hand (Kürzel G) oder als KI-Vorschlag
export function borderlineText(b) {
  if (!b) return '';
  if (b.where === 'human') return b.reason ? t('Grenzfall: {r}', { r: b.reason }) : t('Grenzfall (von Hand)');
  if (b.where === 'ai') return b.reason ? t('Grenzfall laut KI: {r}', { r: b.reason }) : t('Grenzfall laut KI');
  return t('Grenzfall: „{term}“ im {where} – Regel {rule}', { term: b.term, where: b.where === 'title' ? t('Titel') : t('Abstract'), rule: serverText(b.label) });
}

// KI-Vorschlag (Claude oder Gemini): passend / nicht passend / Grenzfall. Schlägt nur vor; entschieden wird von Hand.
export const AI_LABELS = { include: () => t('passend'), exclude: () => t('nicht passend'), borderline: () => t('Grenzfall') };
export const AI_KIND = { include: 'success', exclude: 'danger', borderline: 'warning' };
export const aiInfo = () => (rs().info && rs().info.ai) || { available: false };
// KI-Schalter im Screening: Vorschläge zeigen oder blind sichten; gilt je Projekt, auch für den Pool
export const aiVisible = () => ((rs().project && rs().project.settings) || {}).ai_visible !== false;

export function aiBadge(ai, project) {
  if (!ai || !ai.label) return null;
  const folder = ai.label === 'include' && ai.folder ? ` → ${folderLabel(project, ai.folder)}` : '';
  return badge(t('KI: {l}', { l: AI_LABELS[ai.label]() }) + folder, AI_KIND[ai.label], ai.reason || undefined);
}

export const fmtUsd = x => (x == null ? '–' : `${x < 0.1 ? x.toFixed(3) : x.toFixed(2)} USD`);

// Token: geschätzt vor dem Aufruf („≈ 8'000 Token Input · ≈ 1'800 Token Output“), danach laut Anbieter
export function tokenText(x, approx = true) {
  if (!x) return '';
  const a = approx ? '≈ ' : '';
  return t('{a}{i} Token Input · {a}{o} Token Output', { a, i: fmtInt(x.input || 0), o: fmtInt(x.output || 0) })
    + (x.cost != null ? ` · ${approx ? '≈' : 'ca.'} ${fmtUsd(x.cost)}` : '');
}
export const costOf = (prices, i, o) => (prices ? Math.round(((i * prices[0] + o * prices[1]) / 1e6) * 10000) / 10000 : null);
export const addUsed = (a, b) => (b ? { input: (a.input || 0) + (b.input || 0), output: (a.output || 0) + (b.output || 0),
  cost: a.cost == null && b.cost == null ? null : (a.cost || 0) + (b.cost || 0) } : a);

// Gesamtverbrauch seit Dienststart (Statuszeile, KI-Karte) aus jeder KI-Antwort nachführen
export function noteUsage(r) {
  const info = rs().info;
  if (info && info.ai && r && r.used_total) info.ai.used_total = r.used_total;
}

// Geschätzte Token für einen KI-Vorschlag (sources | blocks | folders); neu geschätzt, wenn sich ``key`` ändert,
// mit kurzer Verzögerung beim Tippen – bis dahin bleibt die letzte Schätzung stehen
const estCache = {};
const estTimer = {};
export function aiEstimate(kind, body = {}, key = '') {
  const s = rs();
  const k = `${s.pid}|${kind}|${key}`;
  const slot = estCache[`${s.pid}|${kind}`] || (estCache[`${s.pid}|${kind}`] = { key: null, value: null });
  if (slot.key !== k && slot.pending !== k) {
    slot.pending = k;
    clearTimeout(estTimer[kind]);
    estTimer[kind] = setTimeout(() => {
      api.post(`${R}/projects/${s.pid}/ai/estimate`, { kind, ...body })
        .then(r => { if (slot.pending === k) { slot.key = k; slot.value = r; } }).catch(() => {}).finally(update);
    }, slot.value ? 600 : 0);
  }
  return slot.value;
}

export const sourceBadges = sources => h('span', { class: 'rs-sources' }, (sources || []).map(s => h('span', { key: s, class: `rs-src rs-src-${s}` }, sourceLabel(s))));

export function limitsText(limits) {
  if (!limits) return '';
  const p = [];
  if (limits.year_from || limits.year_to) p.push(`${limits.year_from || '…'}–${limits.year_to || '…'}`);
  if (limits.types && limits.types.length) p.push(limits.types.join('|'));
  if (limits.max) p.push(t('max. {n}', { n: limits.max }));
  return p.join(' · ');
}

// Datei → { filename, content_b64 } (Rohdaten: die Kodierung erkennt der Dienst)
export function readFileB64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve({ filename: file.name, content_b64: String(fr.result).split(',')[1] || '' });
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

// Ablagefläche für Dateien (Ziehen oder Klicken)
export function dropZone({ id, label, hint, accept, multiple = true, onFiles, busyKey }) {
  const st = ui('drop:' + id, { over: false });
  const take = files => { st.over = false; update(); if (files && files.length) onFiles([...files]); };
  return h('label', {
    class: ['rs-drop', st.over && 'over', busyKey && isBusy(busyKey) && 'busy'],
    ondragover: e => { e.preventDefault(); if (!st.over) { st.over = true; update(); } },
    ondragleave: () => { st.over = false; update(); },
    ondrop: e => { e.preventDefault(); take(e.dataTransfer.files); },
  },
  h('input', { type: 'file', accept, multiple, class: 'rs-drop-input', onchange: e => { take(e.target.files); e.target.value = ''; } }),
  h('b', null, label), hint && h('span', { class: 'muted small' }, hint));
}
