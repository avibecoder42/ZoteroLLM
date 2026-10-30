// Anwendungsrahmen: Navigationsleiste, Kopfzeilen, Statusleiste, Meldungen, Dialoge, Quellen-Vorschau.
import { h } from '../core/vdom.js';
import { state, update, closeModal, dismiss, providerLabel, project, toast } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, renderMenu, spinner, progressRing, openMenu, fitToWindow } from '../ui/components.js';
import { fmtInt, fmtDuration, copyToClipboard } from '../core/util.js';
import { setupView } from './setup.js';
import { startView } from './start.js';
import { askView } from './ask.js';
import { searchView } from './search.js';
import { corporaView } from './corpora.js';
import { indexView } from './indexing.js';
import { reviewView } from './review.js';
import { settingsView } from './settings.js';
import { helpView, openHelp } from './help.js';
import { cslEditorView } from './csleditor.js';
import { projectBadge, switcherItems } from './projects.js';
import { researchBoot, researchView, researchKey, researchStatus } from './research.js';

// Ansichten des aktiven Projekts (Strg+1–5); Recherche (mit eigenen Projekten), CSL-Editor, Index, Hilfe und
// Einstellungen gelten für alle Projekte (unten)
export const VIEWS = [
  { id: 'start', icon: 'home', label: () => t('Projekt') },
  { id: 'search', icon: 'search', label: () => t('Suchen') },
  { id: 'ask', icon: 'chat', label: () => t('Fragen') },
  { id: 'review', icon: 'review', label: () => t('Forschungs­stand') },
  { id: 'corpora', icon: 'corpus', label: () => t('Korpora') },
];
export const GLOBAL_VIEWS = [
  { id: 'research', icon: 'litsearch', label: () => t('Recherche'), key: 'Strg+8' },
  { id: 'csl', icon: 'cslStyle', label: () => t('CSL-Editor'), key: 'Strg+7' },
  { id: 'index', icon: 'index', label: () => t('Index'), key: 'Strg+6' },
  { id: 'help', icon: 'help', label: () => t('Hilfe'), key: 'F1' },
  { id: 'settings', icon: 'settings', label: () => t('Einstellungen'), key: 'Strg+,' },
];

export function openProjectSwitcher(el) {
  const r = (el || document.querySelector('.rail-project')).getBoundingClientRect();
  openMenu(r.right + 6, r.top, switcherItems(), { width: 280, scroll: true, maxHeight: Math.max(240, window.innerHeight - r.top - 16) });
}

export function navigate(view) {
  state.view = view;
  state.popover = null;
  update();
}

export function viewHeader(title, subtitle, actions = [], extra = null) {
  return h('header', { class: 'view-header' },
    h('div', { class: 'view-title' }, h('h1', null, title), subtitle && h('div', { class: 'view-subtitle' }, subtitle)),
    extra,
    h('div', { class: 'view-actions' }, actions));
}

function rail() {
  const setup = state.setup;
  const openSteps = setup ? setup.steps.filter(s => !s.done && !s.optional).length : 0;
  const indexJob = Object.values(state.jobs).find(j => j.kind === 'index' && j.status === 'running');
  const p = project();
  const item = (v, shortcut) => h('button', {
    key: v.id, type: 'button', class: ['rail-item', state.view === v.id && 'active'], title: `${v.label().replace('­', '')} (${shortcut})`,
    onclick: () => navigate(v.id), 'aria-current': state.view === v.id ? 'page' : null,
  }, icon(v.icon, 21), h('span', null, v.label()),
  v.id === 'index' && indexJob ? h('span', { class: 'rail-dot busy', title: t('Indexierung läuft') }) : null);
  return h('nav', { class: 'rail', 'aria-label': t('Navigation') },
    // Ganz oben: Einrichtung (Startfenster) unter dem Programmsymbol
    h('button', { type: 'button', class: ['rail-item', 'rail-home', state.view === 'setup' && 'active'],
      title: t('Einrichtung – Projekte öffnen, anlegen oder importieren'), onclick: () => navigate('setup'),
      'aria-current': state.view === 'setup' ? 'page' : null },
    h('img', { src: '/static/img/icon.svg', alt: '', width: 28, height: 28 }), h('span', null, t('Einrichtung')),
    openSteps ? h('span', { class: 'rail-dot', title: openSteps === 1 ? t('1 Schritt der Einrichtung offen') : t('{n} Schritte der Einrichtung offen', { n: openSteps }) }) : null),
    h('button', { type: 'button', class: 'rail-project', title: p ? t('Projekt: {name} – wechseln (Strg+P)', { name: p.name }) : t('Projekt wählen (Strg+P)'),
      onclick: e => openProjectSwitcher(e.currentTarget) },
    projectBadge(p, 34), h('span', { class: 'rail-project-name' }, p ? p.name : t('Projekt')), icon('chevronDown', 12, 'rail-project-caret')),
    h('div', { class: 'rail-group' }, VIEWS.map((v, i) => item(v, `${t('Strg')}+${i + 1}`))),
    h('div', { class: 'rail-spacer' }),
    h('div', { class: 'rail-group rail-global', title: t('Gilt für alle Projekte') },
      GLOBAL_VIEWS.map(v => item(v, v.key.replace('Strg', t('Strg'))))));
}

// Durchsuchbare Abschnitte mit dem aktiven Modell; deckt es die Korpora erst teilweise ab, „120 von 340“
function coverageItem(s) {
  const cov = s.index.coverage;
  const partial = cov && cov.chunks && cov.embedded < cov.chunks;
  return h('button', { class: ['status-item', 'link', partial && 'warn-text'], onclick: () => navigate('index'),
    title: partial ? t('Mit {m} sind erst {a} von {b} Abschnitten der Korpora eingebettet – die Bedeutungssuche findet den Rest noch nicht.', { m: s.embedding.label || s.embedding.model, a: fmtInt(cov.embedded), b: fmtInt(cov.chunks) })
      : t('Abschnitte, die mit dem aktiven Embedding-Modell durchsuchbar sind (alle Korpora)') },
  icon('corpus', 14),
  h('span', null, partial ? t('{a} von {b} Abschnitten durchsuchbar', { a: fmtInt(cov.embedded), b: fmtInt(cov.chunks) })
    : t('{n} Abschnitte durchsuchbar', { n: fmtInt(cov ? cov.embedded : s.index.embedded || 0) })));
}

function statusbar() {
  const s = state.status;
  if (!s) {
    return h('footer', { class: 'statusbar' }, h('span', { class: 'status-item danger-text' }, icon('alert', 14), h('span', null, t('Dienst nicht erreichbar'))));
  }
  const z = s.zotero;
  const jobs = Object.values(state.jobs).filter(j => ['queued', 'running'].includes(j.status));
  const zText = !z.running ? t('Zotero geschlossen') : !z.local_api ? t('Zotero: lokale API aus') : `Zotero ${z.version || ''}`;
  return h('footer', { class: 'statusbar' },
    h('button', { class: 'status-item link', title: z.message || zText, onclick: () => navigate(z.local_api ? 'corpora' : 'setup') },
      h('span', { class: ['dot', z.local_api ? 'ok' : z.running ? 'warn' : 'err'] }), h('span', null, zText)),
    // In der Recherche: Zotero-Web-API, NCBI-Schlüssel und das Modell der KI-Vorschläge statt Index und Embedding
    state.view === 'research' ? researchStatus() : [
      h('button', { class: 'status-item link', title: t('Sprachmodell (Einstellungen)'), onclick: () => navigate('settings') },
        icon('ai', 14), h('span', { class: s.llm.key ? '' : 'warn-text' }, `${providerLabel(s.llm.provider)} · ${s.llm.model}`)),
      h('div', { class: 'status-item', title: s.embedding.ok ? s.embedding.space : s.embedding.error },
        icon('index', 14), h('span', { class: s.embedding.ok ? '' : 'danger-text' }, s.embedding.ok ? (s.embedding.label || s.embedding.model) : t('Embedding: Fehler'))),
      coverageItem(s)],
    h('div', { class: 'status-spacer' }),
    jobs.map(j => {
      const c = j.counters || {};
      const frac = c.fraction != null ? c.fraction : c.docs_total ? (c.docs_done || 0) / c.docs_total : j.total ? j.done / j.total : null;
      const eta = j.kind === 'index' && c.eta ? ` · ${c.eta_partial ? t('noch mindestens {d}', { d: fmtDuration(c.eta) }) : t('noch ca. {d}', { d: fmtDuration(c.eta) })}` : '';
      return h('div', { class: 'status-job', key: j.id }, progressRing(frac, 13),
        h('button', { class: 'status-item link', onclick: () => navigate(j.kind === 'index' || j.kind === 'catalog' ? 'index' : j.kind === 'review' || j.kind === 'sheets' ? 'review' : 'settings') },
          h('span', null, j.title + (frac != null ? ` · ${Math.round(frac * 100)} %` : '') + eta)),
        h('button', { class: 'status-cancel', title: t('Abbrechen'), onclick: () => api.post(`/api/jobs/${j.id}/cancel`) }, icon('x', 12)));
    }),
    // Wartende Indexierläufe: nur die Zahl, die Liste steht in der Ansicht Index
    s.index_queue && s.index_queue.length ? h('button', { class: 'status-item link', title: s.index_queue.map((e, i) => `${i + 1}. ${e.title}`).join('\n'), onclick: () => navigate('index') },
      icon('queue', 14), h('span', null, s.index_queue.length === 1 ? t('1 Lauf wartet') : t('{n} Läufe warten', { n: s.index_queue.length }))) : null,
    h('span', { class: 'status-item muted' }, `v${s.version}`));
}

function toasts() {
  return h('div', { class: 'toasts', 'aria-live': 'polite' }, state.toasts.map(x => h('div', { key: x.id, class: `toast toast-${x.kind}` },
    icon({ error: 'alert', warning: 'alert', success: 'check' }[x.kind] || 'info', 16),
    h('div', { class: 'toast-text' }, x.message),
    x.action && h('button', { class: 'toast-action', onclick: () => { dismiss(x.id); x.action.onClick(); } }, x.action.label),
    h('button', { class: 'toast-close', onclick: () => dismiss(x.id), 'aria-label': t('Schliessen') }, icon('x', 13)))));
}

function modal() {
  const m = state.modal;
  if (!m) return null;
  const close = () => { closeModal(); if (m.onClose) m.onClose(); };
  return h('div', { class: 'modal-backdrop', onmousedown: e => { if (e.target === e.currentTarget && !m.sticky) close(); } },
    h('div', { class: ['modal', m.wide && 'modal-wide', m.cls], role: 'dialog', 'aria-modal': 'true' },
      h('div', { class: 'modal-head' }, h('h2', null, m.title), !m.sticky && iconBtn('x', t('Schliessen'), close)),
      h('div', { class: 'modal-body' }, typeof m.body === 'function' ? m.body() : m.body),
      m.actions && h('div', { class: 'modal-actions' },
        (typeof m.actions === 'function' ? m.actions() : m.actions).map(a => a.label ? btn(a.label, { kind: a.kind || 'secondary', onClick: a.onClick, icon: a.icon, disabled: a.disabled, busy: a.busy }) : a))));
}

// Vorschau einer Quelle beim Klick auf einen Beleg [n]
export function openSourcePopover(el, source) {
  const r = el.getBoundingClientRect();
  state.popover = { x: r.left, y: r.bottom + 6, source };
  update();
}

// Auswahl beim Klick auf einen Beleg im Forschungsstand: Eintrag in Zotero zeigen oder PDF öffnen
export function openCitePopover(el, cite) {
  const r = el.getBoundingClientRect();
  state.popover = { x: r.left, y: r.bottom + 6, cite };
  update();
}

function citePopover(p) {
  const c = p.cite;
  const close = () => { state.popover = null; update(); };
  const where = c.no_page
    ? (c.pdf_page ? t('Quelle ohne Seitenzahlen (o. S.) – die PDF öffnet an der Fundstelle (PDF-Seite {n}).', { n: c.pdf_page })
      : t('Quelle ohne Seitenzahlen (o. S.)'))
    : c.page ? t('Seite {p}', { p: c.page })
      : c.located ? t('Ohne Seitenangabe – die PDF öffnet an der passenden Stelle (PDF-Seite {n}).', { n: c.pdf_page }) : '';
  return h('div', { class: 'menu-backdrop', onmousedown: close },
    h('div', { class: 'popover popover-cite', role: 'dialog', onmousedown: e => e.stopPropagation(), style: { left: p.x + 'px', top: p.y + 'px' },
      ref: el => { if (!p.placed) requestAnimationFrame(() => fitToWindow(el, p, { flipAbove: p.y - 28 })); } },
    h('div', { class: 'popover-head' }, icon('quote', 16),
      h('div', null, h('div', { class: 'popover-title' }, c.label), c.title && h('div', { class: 'popover-sub' }, c.title))),
    where && h('div', { class: 'popover-meta' }, where),
    c.removed && h('div', { class: 'popover-meta warn-text' }, t('Dieser Eintrag wurde in Zotero gelöscht (Papierkorb) und hat keine andere Kopie.')),
    h('div', { class: 'popover-actions' },
      c.removed ? null : btn(t('In Zotero anzeigen'), { icon: 'zotero', onClick: () => { api.openExternal(c.select); close(); } }),
      c.pdf ? btn(t('PDF in Zotero öffnen'), { kind: 'primary', icon: 'pdf', onClick: () => { api.openExternal(c.pdf); close(); } })
        : h('span', { class: 'muted small' }, t('Keine PDF am Eintrag')))));
}

// Ganze Textstelle (nicht nur die gekürzte Vorschau) mit Beleg im eingestellten Zitierstil und Literaturangabe
async function copySource(s) {
  let ref = null;
  try {
    ref = await api.get(`/api/cite?lib=${encodeURIComponent(s.lib)}&key=${encodeURIComponent(s.item_key)}`
      + `&page=${encodeURIComponent(s.page_label || '')}&kind=${encodeURIComponent(s.kind || 'text')}`);
  } catch { /* ohne Dienst: einfache Angabe */ }
  const fallback = `(${[s.citation, s.page_label ? t('S. {p}', { p: s.page_label }) : s.kind === 'text' ? t('o. S.') : ''].filter(Boolean).join(', ')})`;
  const text = ref ? `${s.text}\n\n${ref.short}${ref.reference ? `\n${ref.reference}` : ''}`
    : `${s.text}\n\n${fallback}${s.title ? ` – ${s.title}` : ''}`;
  if (await copyToClipboard(text)) toast(t('In die Zwischenablage kopiert.'), 'success', 2500);
}

function popover() {
  const p = state.popover;
  if (!p) return null;
  if (p.cite) return citePopover(p);
  const s = p.source;
  return h('div', { class: 'menu-backdrop', onmousedown: () => { state.popover = null; update(); } },
    h('div', { class: 'popover', onmousedown: e => e.stopPropagation(), style: { left: p.x + 'px', top: p.y + 'px' },
      // einmal ins Fenster schieben und die Lage merken (sonst flackert die Vorschau bei jedem Neuzeichnen)
      ref: el => { if (!p.placed) requestAnimationFrame(() => fitToWindow(el, p, { flipAbove: p.y - 28 })); } },
    h('div', { class: 'popover-head' }, h('span', { class: 'cite static' }, s.n),
      h('div', null, h('div', { class: 'popover-title' }, s.citation), h('div', { class: 'popover-sub' }, s.title))),
    h('div', { class: 'popover-meta' }, s.kind === 'abstract' ? 'Abstract' : s.page_label ? t('Seite {p}', { p: s.page_label })
      : s.kind === 'text' ? t('ohne Seitenzahl (o. S.)') : ''),
    h('div', { class: 'popover-text' }, s.text.length > 700 ? s.text.slice(0, 700) + ' …' : s.text),
    h('div', { class: 'row' },
      s.zotero_pdf && btn(s.page_label ? t('PDF öffnen (S. {p})', { p: s.page_label }) : t('PDF öffnen'), { kind: 'primary', size: 'sm', icon: 'pdf',
        onClick: () => { api.openExternal(s.zotero_pdf); state.popover = null; update(); } }),
      btn(t('In Zotero zeigen'), { size: 'sm', icon: 'zotero', onClick: () => { api.openExternal(s.zotero_select); state.popover = null; update(); } }),
      h('span', { class: 'spacer' }),
      iconBtn('copy', t('Textstelle mit Quellenangabe kopieren'), () => copySource(s)))));
}

export function shell() {
  if (!state.ready) {
    return h('div', { class: 'splash', role: 'status' },
      h('img', { src: '/static/img/icon.svg', width: 56, height: 56, alt: '' }), h('h1', null, 'ZotLLM'),
      state.bootError ? h('p', { class: 'splash-msg danger-text' }, state.bootError) : h('div', { class: 'splash-progress' }, h('i')));
  }
  return h('div', { class: 'app' },
    safe('rail', rail),
    h('div', { class: 'main' }, h('main', { class: 'view', key: state.view, 'data-view': state.view }, safe(state.view, currentView)), safe('statusbar', statusbar)),
    safe('toasts', toasts), safe('modal', modal), safe('menu', renderMenu), safe('popover', popover));
}

function currentView() {
  const views = { setup: setupView, start: startView, search: searchView, ask: askView, corpora: corporaView, index: indexView,
    review: reviewView, settings: settingsView, help: helpView, csl: cslEditorView, research: researchStart };
  return (views[state.view] || setupView)();
}

// Recherche: Angaben des Moduls und das zuletzt geöffnete Projekt erst beim ersten Öffnen laden
let researchBooted = false;
function researchStart() {
  if (!researchBooted) {
    researchBooted = true;
    researchBoot().then(update, () => { researchBooted = false; });
  }
  return researchView();
}

// Ein Fehler beim Zeichnen eines Teils darf die Oberfläche nicht lahmlegen: Meldung statt Stillstand
const reported = new Set();
function safe(part, fn) {
  try {
    return fn();
  } catch (err) {
    const msg = `${part}: ${err && err.message ? err.message : err}`;
    console.error('render', part, err);
    if (!reported.has(msg)) {
      reported.add(msg);
      api.post('/api/client-error', { part, message: String((err && err.message) || err), stack: String((err && err.stack) || '') }).catch(() => {});
    }
    if (['toasts', 'modal', 'menu', 'popover'].includes(part)) return null;
    if (part === 'rail' || part === 'statusbar') return h('div', { class: 'render-error small' }, t('Anzeigefehler'));
    return h('div', { class: 'render-error' }, icon('alert', 20),
      h('div', { class: 'stack-sm' }, h('b', null, t('Diese Ansicht konnte nicht angezeigt werden.')),
        h('div', { class: 'muted small' }, msg),
        h('div', { class: 'row' }, btn(t('Neu laden'), { size: 'sm', icon: 'refresh', onClick: () => location.reload() }),
          btn(t('Zur Einrichtung'), { size: 'sm', kind: 'ghost', onClick: () => navigate('setup') }))));
  }
}

export function handleKey(e) {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && /^[1-5]$/.test(e.key)) { e.preventDefault(); navigate(VIEWS[Number(e.key) - 1].id); return; }
  if (mod && e.key === '6') { e.preventDefault(); navigate('index'); return; }
  if (mod && e.key === '7') { e.preventDefault(); navigate('csl'); return; }
  if (mod && e.key === '8') { e.preventDefault(); navigate('research'); return; }
  if (mod && e.key === ',') { e.preventDefault(); navigate('settings'); return; }
  if (mod && (e.key === 'p' || e.key === 'P')) { e.preventDefault(); openProjectSwitcher(); return; }
  if (e.key === 'F1') { e.preventDefault(); openHelp(); return; }
  if (e.key === 'Escape') {
    if (state.menu) { state.menu = null; update(); }
    else if (state.popover) { state.popover = null; update(); }
    else if (state.modal && !state.modal.sticky) { closeModal(); }
    return;
  }
  // Recherche: Alt+1…8 wechselt den Reiter, im Screening J/K, Ordner 1–9, X, ?, G, A, Z
  if (state.view === 'research' && !state.modal && !state.menu && !state.popover) researchKey(e);
}

// Links nach aussen (zotero://, https://) über das Betriebssystem öffnen statt im Programmfenster
export function handleClick(e) {
  const a = e.target.closest && e.target.closest('a[href]');
  if (!a) return;
  const href = a.getAttribute('href');
  if (/^(zotero|https?):/.test(href) && !href.startsWith(location.origin)) {
    e.preventDefault();
    api.openExternal(href);
  }
}
