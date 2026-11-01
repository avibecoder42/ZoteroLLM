// Ansicht „Recherche“: ein Projekt als Arbeitsfluss in Ansichten (Projekt, Datenbanken, Suchstrategie, Suche & Import,
// Pool, Ordner, Screening, Übergabe, Volltexte). Kopfzeile zeigt, wo man steht: „PubMed 503 · OpenAlex 937 · gesichtet 380/1150 · ausgewählt 71“.
// Diese Datei und views/research/ wandern bei der Integration unverändert nach Zotivity (static/js/views).
import { h } from '../core/vdom.js';
import { state, update, ui } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { fmtInt } from '../core/util.js';
import { icon } from '../ui/icons.js';
import { btn } from '../ui/components.js';
import { R, rs, TABS, loadInfo, loadProjects, openProject, closeProject, summaryLine, tokenText, flushSaves, invalidate } from './research/common.js';
import { projectList, projectTab, databasesTab } from './research/project.js';
import { foldersTab } from './research/folders.js';
import { strategyTab } from './research/strategy.js';
import { searchTab } from './research/search.js';
import { poolTab } from './research/pool.js';
import { screeningTab, screeningKey } from './research/screening.js';
import { handoverTab } from './research/handover.js';
import { fulltextTab } from './research/fulltext.js';
import { navigate } from './shell.js';

const VIEWS = { project: projectTab, databases: databasesTab, strategy: strategyTab, search: searchTab, pool: poolTab, folders: foldersTab,
  screening: screeningTab, handover: handoverTab, fulltext: fulltextTab };

function openTab(id) {
  const s = rs();
  flushSaves();
  s.tab = id;
  invalidate('flow', 'fulltext');  // Stand kann sich geändert haben
  update();
}

export async function researchBoot() {
  await Promise.all([loadInfo().catch(() => {}), loadProjects().catch(() => {})]);
  let last = null;
  try { last = Number(localStorage.getItem('litsearch.project')) || null; } catch { /* privat */ }
  const s = rs();
  if (last && (s.projects || []).some(p => p.id === last)) openProject(last);
}

function header() {
  const s = rs();
  const p = s.project;
  return h('header', { class: 'view-header rs-header' },
    btn('', { icon: 'arrowLeft', kind: 'ghost', title: t('Alle Projekte'), onClick: closeProject }),
    h('div', { class: 'view-title grow' }, h('h1', null, p ? p.title : t('Projekt …')),
      h('div', { class: 'view-subtitle' }, p ? summaryLine(p.summary) : '')),
    h('nav', { class: 'rs-tabs', role: 'tablist' }, TABS.map((tab, i) => h('button', {
      key: tab.id, type: 'button', role: 'tab', class: ['rs-tab', s.tab === tab.id && 'active'], 'aria-selected': s.tab === tab.id ? 'true' : 'false',
      title: `${tab.label()} (Alt+${i + 1})`, onclick: () => openTab(tab.id),
    }, icon(tab.icon, 16), h('span', null, tab.label())))));
}

// Zotero wurde geöffnet, während die Recherche offen war: Bibliotheken und Stand neu holen
let zoteroWasUp = null;
function watchZotero() {
  const up = !!(state.status && state.status.zotero && state.status.zotero.local_api);
  if (zoteroWasUp === false && up) {
    const s = rs();
    s.zotero = {};
    ui('rs-handover', {}).status = {};
    invalidate('plan', 'fulltext');
  }
  zoteroWasUp = up;
}

export function researchView() {
  const s = rs();
  watchZotero();
  if (s.projects && s.forProject !== state.projectId) {  // anderes Zotivity-Projekt: dessen Recherchen zeigen
    Object.assign(s, { projects: null, pid: null, project: null, queries: null, runs: null, pool: null, queue: null, plan: null,
      recall: null, flow: null, fulltext: null, stale: {} });
  }
  if (!s.pid) return h('div', { class: 'view-wrap' }, projectList());
  if (!s.project) return h('div', { class: 'view-wrap' }, header(), h('div', { class: 'view-body muted' }, t('Lade Projekt …')));
  return h('div', { class: 'view-wrap' }, header(), (VIEWS[s.tab] || projectTab)());
}

// Kürzel: Alt+1…9 wechselt die Ansicht; im Screening J/K, 1–9 (Ordner), X, ?, G, A, Z
export function researchKey(e) {
  const s = rs();
  if (!s.pid || !s.project) return false;
  if (e.altKey && /^[1-9]$/.test(e.key) && TABS[Number(e.key) - 1]) { openTab(TABS[Number(e.key) - 1].id); e.preventDefault(); return true; }
  if (s.tab === 'screening') return screeningKey(e);
  return false;
}

// Statuszeile: Web-API nur, wenn diese Recherche über zotero.org schreibt (Zotero lokal steht links in der Statuszeile),
// dazu NCBI-Schlüssel und KI-Modell
export function researchStatus() {
  const s = rs();
  const info = s.info;
  const st = ui('rs-status', { zotero: undefined });
  const web = !!(s.project && s.project.zotero_backend === 'web');
  if (web && st.zotero === undefined) {
    st.zotero = null;
    api.get(`${R}/zotero/status?backend=web`).then(r => { st.zotero = r; }).catch(err => { st.zotero = { ok: false, message: err.message }; }).finally(update);
  }
  const z = st.zotero;
  return [
    web ? h('span', { class: 'status-item', key: 'z', title: z ? z.message : '' }, h('span', { class: ['dot', z ? (z.ok ? 'ok' : 'err') : ''] }),
      h('span', null, z ? (z.ok ? t('Zotero-Web-API: {u}', { u: z.username || z.user_id }) : t('Zotero-Web-API nicht bereit')) : t('Zotero …'))) : null,
    info && h('button', { class: 'status-item link', key: 'n', title: t('Mit NCBI-Schlüssel sind 10 statt 3 PubMed-Anfragen pro Sekunde erlaubt.'),
      onclick: () => { ui('settings', {}).tab = 'databases'; navigate('settings'); } },
    icon('key', 13), h('span', null, info.keys.ncbi ? t('NCBI-Schlüssel aktiv') : t('ohne NCBI-Schlüssel'))),
    info && info.ai && h('span', { class: 'status-item', key: 'ai', title: info.ai.available
      ? t('KI-Vorschläge mit {m}, Aufwand {e}; Schlüssel aus {k}. Verbrauch seit Dienststart: {u}', { m: info.ai.model, e: info.ai.effort,
        k: info.ai.key_source || '–', u: tokenText(info.ai.used_total, false) || '–' })
      : info.ai.message }, icon('ai', 13), h('span', null, info.ai.available ? info.ai.label : t('ohne KI')),
    info.ai.used_total && info.ai.used_total.requests ? h('span', { class: 'muted' }, ` · ${t('{i} / {o} Token', { i: fmtInt(info.ai.used_total.input || 0), o: fmtInt(info.ai.used_total.output || 0) })}`) : null),
  ];
}
