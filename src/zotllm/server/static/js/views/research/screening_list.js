// Screening als Liste: alle offenen Treffer auf einmal, mit KI-Vorauswahl (grün = „passend“, angehakt). Du hakst an
// oder ab; fest wird erst mit „Übernehmen“ – als ein Stapel, den „rückgängig“ (Z) ganz zurücknimmt.
// Was nicht angehakt ist: ausgeschlossen, wenn die KI „passend“ oder „nicht passend“ vorschlug. Grenzfälle, Treffer ohne
// Abstract und solche ohne KI-Vorschlag bleiben offen für die Karten (Recall vor Tempo).
import { h } from '../../core/vdom.js';
import { update, ui, toast, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt, debounce } from '../../core/util.js';
import { btn, card, field, select, checkbox, emptyState } from '../../ui/components.js';
import { R, rs, busy, isBusy, invalidate, refreshSummary, folderLabel, authorsShort, aiVisible } from './common.js';

const PAGE = 100;
const summaryLater = debounce(refreshSummary, 600);

function ls() {
  const s = rs();
  const l = ui('rs-list', { pid: null, over: new Map(), open: {}, limit: {}, folder: null, excludeRest: false });
  if (l.pid !== s.pid) Object.assign(l, { pid: s.pid, over: new Map(), open: {}, limit: {}, folder: null, excludeRest: false });
  return l;
}

const slotsOf = p => (p.folder_map || []).map(f => Number(f.slot)).filter(n => n >= 1 && n <= 6);
const isDecided = it => !!(it.decision && it.decision.status !== 'open');
// In der Liste bearbeitbar: offene Treffer; in der Auswahl „unsicher“ auch die als unsicher markierten
const listable = status => it => !isDecided(it) || (status === 'maybe' && it.decision.status === 'maybe');
const ruleBorderline = it => (it.borderline || []).some(b => b.where !== 'ai');

// Zustand einer Zeile: deine Änderung, sonst die KI-Vorauswahl
function rowState(it) {
  const l = ls();
  const p = rs().project;
  const ai = aiVisible() && it.ai && it.ai.label ? it.ai : null;
  const slots = slotsOf(p);
  const fallback = l.folder || slots[0] || 1;
  const def = { on: !!(ai && ai.label === 'include'), folder: ai && slots.includes(ai.folder) ? ai.folder : fallback, keep: false };
  return { ...def, ...(l.over.get(it.id) || {}), ai };
}

// Was „Übernehmen“ mit der Zeile macht
function fate(it, r) {
  if (r.on) return 'include';
  if (r.keep) return 'open';
  const safe = !it.no_abstract && !ruleBorderline(it);
  if (r.ai) return safe && (r.ai.label === 'include' || r.ai.label === 'exclude') ? 'exclude' : 'open';
  return !aiVisible() && ls().excludeRest && safe ? 'exclude' : 'open';
}

function setRow(it, patch) {
  const { ai, ...cur } = rowState(it);
  ls().over.set(it.id, { ...cur, ...patch });
  update();
}

function matchCriterion(ai, queue) {
  const c = String((ai && ai.criterion) || '').toLowerCase();
  return (c && (queue.criteria_out || []).find(x => c.includes(x.toLowerCase()) || x.toLowerCase().includes(c))) || '';
}

const SECTIONS = [
  { id: 'include', label: () => t('KI: passend'), test: it => it.ai && it.ai.label === 'include' },
  { id: 'borderline', label: () => t('KI: Grenzfall'), test: it => it.ai && it.ai.label === 'borderline' },
  { id: 'exclude', label: () => t('KI: nicht passend'), test: it => it.ai && it.ai.label === 'exclude' },
  { id: 'none', label: () => t('ohne KI-Vorschlag'), test: it => !(it.ai && it.ai.label) },
];

function row(it, p, queue) {
  const l = ls();
  const r = rowState(it);
  const f = fate(it, r);
  const slots = slotsOf(p);
  const open = !!l.open[it.id];
  return h('div', { key: it.id, class: ['rs-lrow', r.on && 'on', r.ai && `ai-${r.ai.label}`, f === 'exclude' && 'out'] },
    checkbox({ checked: r.on, onChange: v => setRow(it, { on: v, keep: false }) }),
    h('div', { class: 'rs-lrow-main' },
      h('button', { type: 'button', class: 'rs-link rs-lrow-title', onclick: () => { l.open[it.id] = !open; update(); } }, it.title || t('(ohne Titel)')),
      h('div', { class: 'muted small' }, [it.year, authorsShort(it.authors), it.journal].filter(Boolean).join(' · '),
        it.no_abstract ? [' · ', h('span', { class: 'warn-text' }, t('nur Titel'))] : null,
        ruleBorderline(it) ? [' · ', h('span', { class: 'warn-text' }, t('Grenzfall'))] : null),
      r.ai && r.ai.reason ? h('div', { class: 'small rs-lrow-reason' }, r.ai.reason) : null,
      open ? h('p', { class: 'rs-abstract small' }, it.abstract || t('Kein Abstract.')) : null),
    h('div', { class: 'rs-lrow-side' },
      r.on ? select({ value: String(r.folder), options: slots.map(n => ({ value: String(n), label: `${n} · ${folderLabel(p, n)}` })),
        onChange: v => setRow(it, { on: true, folder: Number(v) }) })
        : f === 'exclude' ? h('button', { type: 'button', class: 'rs-link small', title: t('Klicken: offen lassen für die Karten'), onclick: () => setRow(it, { keep: true }) }, t('wird ausgeschlossen'))
          : r.keep ? h('button', { type: 'button', class: 'rs-link small muted', title: t('Klicken: wieder nach KI-Vorschlag'), onclick: () => setRow(it, { keep: false }) }, t('bleibt offen'))
            : h('span', { class: 'muted small' }, t('bleibt offen'))));
}

function section(sec, items, p, queue) {
  const l = ls();
  if (!items.length) return null;
  const limit = l.limit[sec.id] || PAGE;
  const allOn = items.every(it => rowState(it).on);
  return h('section', { key: sec.id, class: ['rs-lsec', `rs-lsec-${sec.id}`] },
    h('div', { class: 'rs-lsec-head' },
      checkbox({ checked: allOn, indeterminate: !allOn && items.some(it => rowState(it).on), label: `${sec.label()} (${fmtInt(items.length)})`,
        onChange: v => { items.forEach(it => { const { ai, ...cur } = rowState(it); l.over.set(it.id, { ...cur, on: v, keep: false }); }); update(); } })),
    items.slice(0, limit).map(it => row(it, p, queue)),
    items.length > limit ? h('div', { class: 'row center' },
      btn(t('Weitere {n} zeigen', { n: Math.min(PAGE, items.length - limit) }), { size: 'sm', kind: 'ghost', onClick: () => { l.limit[sec.id] = limit + PAGE; update(); } })) : null);
}

export function listView(queue, status = 'open') {
  const p = rs().project;
  const items = queue.items.filter(listable(status));
  if (!items.length) return emptyState('check', status === 'open' ? t('Alles gesichtet') : t('Keine Treffer in dieser Auswahl'),
    status === 'open' ? t('Keine offenen Treffer mehr.') : null);
  const body = aiVisible()
    ? SECTIONS.map(sec => section(sec, items.filter(sec.test), p, queue))
    : section({ id: 'all', label: () => t('Offene Treffer') }, items, p, queue);
  return h('div', { class: 'rs-list card' },
    h('div', { class: 'muted small' }, aiVisible()
      ? t('Grün = von der KI als „passend“ vorausgewählt. Titel anklicken zeigt den Abstract. Fest wird erst mit „Übernehmen“.')
      : t('Schnellsichtung nach Titel: anhaken, was aufgenommen wird. Titel anklicken zeigt den Abstract. Fest wird erst mit „Übernehmen“.')),
    body);
}

async function commit(queue, onDone, status) {
  const s = rs();
  const l = ls();
  const p = s.project;
  const rows = queue.items.filter(listable(status)).map(it => { const r = rowState(it); return { it, r, f: fate(it, r) }; });
  const inc = rows.filter(x => x.f === 'include');
  const exc = rows.filter(x => x.f === 'exclude');
  const left = rows.length - inc.length - exc.length;
  const byFolder = {};
  inc.forEach(x => { byFolder[x.r.folder] = (byFolder[x.r.folder] || 0) + 1; });
  const ok = await confirmDialog(t('Entscheide übernehmen?'), h('div', { class: 'stack-sm' },
    h('p', null, t('{i} aufnehmen, {x} ausschliessen; {o} bleiben offen für die Karten.', { i: fmtInt(inc.length), x: fmtInt(exc.length), o: fmtInt(left) })),
    inc.length ? h('ul', null, Object.entries(byFolder).map(([n, c]) => h('li', { key: n }, t('Ordner {n} ({l}): {c}', { n, l: folderLabel(p, n), c: fmtInt(c) })))) : null,
    h('p', { class: 'muted small' }, aiVisible()
      ? t('Im Protokoll steht, dass diese Entscheide per Sammel-Übernahme mit KI-Vorauswahl gefallen sind. Rückgängig machen lässt sich die ganze Übernahme (Z).')
      : t('Im Protokoll steht, dass diese Entscheide per Sammel-Übernahme gefallen sind. Rückgängig machen lässt sich die ganze Übernahme (Z).'))),
  { ok: t('Übernehmen') });
  if (!ok) return;
  const items = [...inc.map(({ it, r }) => ({ record_id: it.id, status: 'include', folder: r.folder })),
    ...exc.map(({ it, r }) => ({ record_id: it.id, status: 'exclude', reason: matchCriterion(r.ai, queue) }))];
  const res = await busy('bulk', () => api.post(`${R}/projects/${s.pid}/decisions/bulk`, { items, ai_shown: aiVisible(), method: 'list' }));
  if (!res) return;
  l.over.clear();
  invalidate('queue', 'plan', 'pool', 'recall');
  summaryLater();
  toast(t('{n} Entscheide übernommen.', { n: fmtInt(res.count) }), 'success', 10000, { label: t('Rückgängig'), onClick: onDone });
  update();
}

export function listSideCard(queue, { onUndo, status = 'open' }) {
  const l = ls();
  const p = rs().project;
  if (!queue) return null;
  const rows = queue.items.filter(listable(status)).map(it => fate(it, rowState(it)));
  const n = k => rows.filter(f => f === k).length;
  const slots = slotsOf(p);
  return card(t('Übernehmen'), 'check', h('div', { class: 'stack-sm' },
    h('div', { class: 'small' }, t('{i} aufnehmen · {x} ausschliessen · {o} bleiben offen', { i: fmtInt(n('include')), x: fmtInt(n('exclude')), o: fmtInt(n('open')) })),
    slots.length ? field(t('Ordner für Angehakte ohne Vorschlag'), select({ value: String(l.folder || slots[0]),
      options: slots.map(x => ({ value: String(x), label: `${x} · ${folderLabel(p, x)}` })), onChange: v => { l.folder = Number(v); update(); } }))
      : h('div', { class: 'warn-text small' }, t('Noch keine Ordner zugeordnet (Tab „Ordner“).')),
    !aiVisible() ? checkbox({ checked: l.excludeRest, label: t('Nicht Angehakte ausschliessen (ausser Grenzfälle und ohne Abstract)'),
      onChange: v => { l.excludeRest = v; update(); } }) : null,
    btn(t('Übernehmen …'), { kind: 'primary', icon: 'check', busy: isBusy('bulk'), disabled: !(n('include') + n('exclude')), onClick: () => commit(queue, onUndo, status) }),
    h('div', { class: 'muted small' }, aiVisible()
      ? t('Nicht angehakt mit KI-Vorschlag „passend“ oder „nicht passend“ wird ausgeschlossen. Grenzfälle, Treffer ohne Abstract und ohne Vorschlag bleiben offen, ausser du hakst sie an. Rückgängig: Z.')
      : t('Ohne KI bleiben nicht angehakte Treffer offen, ausser du wählst oben „ausschliessen“. Rückgängig: Z.'))));
}

