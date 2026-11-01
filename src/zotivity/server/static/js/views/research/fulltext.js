// Volltexte: nach der Übergabe die eingeschlossenen Texte beschaffen und prüfen (PRISMA 2020, Item 16a). Fehlende PDFs sind
// der Normalfall und halten nichts auf: Der Stand wird bei jedem Öffnen aus Zotero nachgeführt, der Schritt lässt sich
// jederzeit verlassen oder ganz weglassen. Beim Volltext Ausgeschlossene bleiben in Zotero – auf Wunsch nur aus den
// Sammlungen genommen und mit einem Schlagwort versehen.
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, openModal, closeModal, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt } from '../../core/util.js';
import { btn, iconBtn, card, textInput, notice, badge, emptyState, spinner } from '../../ui/components.js';
import { icon } from '../../ui/icons.js';
import { R, rs, lazy, busy, isBusy, invalidate, refreshSummary, authorsShort, folderLabel, workspace, zoteroSelect } from './common.js';

const STATES = {
  missing: { label: () => t('fehlt noch'), kind: 'neutral' },
  available: { label: () => t('vorhanden'), kind: 'info' },
  not_retrieved: { label: () => t('nicht beschaffbar'), kind: 'warning' },
  include: { label: () => t('eingeschlossen'), kind: 'success' },
  exclude: { label: () => t('ausgeschlossen'), kind: 'danger' },
};
const ORDER = ['missing', 'available', 'include', 'exclude', 'not_retrieved'];
const fst = () => ui('rs-fulltext', { filter: '' });
const load = (s, refresh = 'open') => lazy('fulltext', `${R}/projects/${s.pid}/fulltext?refresh=${refresh}`);

function apply(r) {
  rs().fulltext = r;
  invalidate('flow');
  refreshSummary();
  update();
}

async function setStatus(ids, status, reason = '') {
  const s = rs();
  const r = await run(() => api.post(`${R}/projects/${s.pid}/fulltext`, { record_ids: ids, status, reason }));
  apply(r);
}

// Grund: die Ausschlusskriterien des Projekts zur Wahl oder frei; bei „nicht beschaffbar“ frei
function reasonDialog(it, status, reasons) {
  const d = { reason: it.reason || '' };
  const go = async () => { closeModal(); await setStatus([it.id], status, d.reason); };
  openModal({
    title: status === 'exclude' ? t('Beim Volltext ausschliessen') : t('Nicht beschaffbar'),
    body: () => h('div', { class: 'stack' },
      h('p', { class: 'small' }, it.title || t('(ohne Titel)')),
      reasons.length && status === 'exclude' ? h('div', { class: 'chips' }, reasons.map(r => h('button', { type: 'button', key: r, class: ['chip', d.reason === r && 'chip-accent'],
        onclick: () => { d.reason = r; update(); } }, h('span', null, r)))) : null,
      textInput({ value: d.reason, placeholder: status === 'exclude' ? t('Grund, z. B. falsche Population') : t('z. B. Fernleihe abgelehnt'),
        onInput: v => { d.reason = v; update(); }, onKeyDown: e => { if (e.key === 'Enter') go(); } })),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal }, { label: t('Übernehmen'), kind: 'primary', onClick: go }],
  });
}

function row(it, data, project) {
  const state = STATES[it.state];
  const decided = ['include', 'exclude', 'not_retrieved'].includes(it.state);
  return h('tr', { key: it.id },
    h('td', { class: 'num muted' }, it.year || ''),
    h('td', null, h('div', { class: 'rs-title' }, it.title || t('(ohne Titel)')),
      h('div', { class: 'muted small' }, [authorsShort(it.authors), it.journal, folderLabel(project, it.folder)].filter(Boolean).join(' · '))),
    h('td', null, badge(state.label(), state.kind),
      it.reason ? h('div', { class: 'muted small' }, it.reason) : null,
      it.by ? h('div', { class: 'muted small' }, it.by) : null,
      !it.zotero_key ? h('div', { class: 'muted small' }, t('noch nicht übergeben')) : null,
      it.set_aside ? h('div', { class: 'muted small', title: t('In Zotero aus den Sammlungen dieser Recherche genommen; der Eintrag besteht weiter.') }, t('aus Sammlung genommen')) : null),
    h('td', { class: 'nowrap rs-q-actions' },
      it.zotero_key ? iconBtn('zotero', t('In Zotero zeigen'), () => api.openExternal(zoteroSelect(it.zotero_lib, it.zotero_key))) : null,
      it.doi ? iconBtn('external', t('DOI öffnen'), () => api.openExternal(`https://doi.org/${it.doi}`)) : null,
      decided ? btn(t('Zurücksetzen'), { size: 'sm', kind: 'ghost', onClick: () => setStatus([it.id], '') }) : [
        btn(t('Einschliessen'), { size: 'sm', kind: 'primary', icon: 'check', onClick: () => setStatus([it.id], 'include') }),
        btn(t('Ausschliessen …'), { size: 'sm', icon: 'x', onClick: () => reasonDialog(it, 'exclude', data.reasons) }),
        it.state === 'missing' ? btn(t('Nicht beschaffbar …'), { size: 'sm', kind: 'ghost', onClick: () => reasonDialog(it, 'not_retrieved', []) }) : null]));
}

async function setAside(n) {
  const s = rs();
  const ok = await confirmDialog(t('In Zotero aus den Sammlungen nehmen?'), h('div', { class: 'stack-sm' },
    h('p', null, n === 1 ? t('1 beim Volltext ausgeschlossener Eintrag wird aus den Sammlungen dieser Recherche genommen und bekommt das Schlagwort „litsearch-volltext-ausgeschlossen“.')
      : t('{n} beim Volltext ausgeschlossene Einträge werden aus den Sammlungen dieser Recherche genommen und bekommen das Schlagwort „litsearch-volltext-ausgeschlossen“.', { n: fmtInt(n) })),
    h('p', { class: 'muted small' }, t('Gelöscht wird nichts: Die Einträge bleiben in der Bibliothek, auch in anderen Sammlungen.'))), { ok: t('Aus Sammlungen nehmen') });
  if (!ok) return;
  const r = await busy('set-aside', () => api.post(`${R}/projects/${s.pid}/fulltext/set-aside`, { confirm: true }));
  if (!r) return;
  toast(t('{n} Einträge aus den Sammlungen genommen.', { n: fmtInt(r.done) }), r.failed.length ? 'warning' : 'success', 6000);
  if (r.failed.length) toast(r.failed.slice(0, 3).map(x => x.error).join(' · '), 'error', 12000);
  invalidate('fulltext');
  update();
}

function refreshAll() {
  const s = rs();
  run(() => api.get(`${R}/projects/${s.pid}/fulltext?refresh=all`)).then(r => { s.fulltext = r; toast(t('Stand aus Zotero aktualisiert.'), 'success', 2000); update(); }).catch(() => {});
}

function sideCards(data) {
  const f = fst();
  const counts = data.counts || {};
  const total = data.items.length;
  const assessed = (counts.include || 0) + (counts.exclude || 0);
  return [
    card(t('Stand'), 'check', h('div', { class: 'stack-sm' },
      h('div', { class: 'small' }, t('{a} von {b} Volltexten geprüft', { a: fmtInt(assessed), b: fmtInt(total) })),
      h('div', { class: 'rs-ft-filter' },
        h('button', { type: 'button', class: ['rs-ft-state', !f.filter && 'active'], onclick: () => { f.filter = ''; update(); } }, h('span', { class: 'grow' }, t('alle')), h('b', null, fmtInt(total))),
        ORDER.map(k => h('button', { type: 'button', key: k, class: ['rs-ft-state', f.filter === k && 'active'], onclick: () => { f.filter = k; update(); } },
          h('span', { class: 'grow' }, STATES[k].label()), h('b', null, fmtInt(counts[k] || 0))))))),
    data.to_set_aside ? card(t('In Zotero aufräumen'), 'zotero', h('div', { class: 'stack-sm' },
      h('p', { class: 'muted small' }, data.to_set_aside === 1 ? t('1 ausgeschlossener Eintrag liegt noch in den Sammlungen dieser Recherche.')
        : t('{n} ausgeschlossene Einträge liegen noch in den Sammlungen dieser Recherche.', { n: fmtInt(data.to_set_aside) })),
      btn(t('Aus Sammlungen nehmen …'), { size: 'sm', busy: isBusy('set-aside'), onClick: () => setAside(data.to_set_aside) }))) : null,
    card(t('So geht es'), 'info', h('div', { class: 'stack-sm small' },
      h('p', null, t('Hole die PDFs in Zotero, etwa mit „Volltext finden“ oder über die Bibliothek. Beim nächsten Öffnen steht hier „vorhanden“.')),
      h('p', null, t('Du kannst jederzeit aufhören und später weitermachen. Protokoll und Flussdiagramm nennen den aktuellen Stand; offene Texte zählen dort als noch nicht geprüft.')),
      h('p', { class: 'muted' }, t('Wer diesen Schritt nicht nutzt, bekommt ein Protokoll, das die Auswahl nur bis zum Titel-/Abstract-Screening ausweist.')))),
  ];
}

export function fulltextTab() {
  const s = rs();
  const data = load(s);
  if (!data) return h('div', { class: 'view-body muted' }, spinner(14), ' ', t('Lade …'));
  if (!data.items.length) {
    return h('div', { class: 'view-body scroll' }, h('div', { class: 'rs-narrow' },
      emptyState('pdf', t('Noch keine Texte für die Volltextprüfung'), t('Hier erscheinen die im Screening eingeschlossenen Treffer.'))));
  }
  const f = fst();
  const shown = data.items.filter(it => !f.filter || it.state === f.filter);
  return workspace('fulltext', h('div', { class: 'stack' },
    h('div', { class: 'row wrap' },
      h('div', { class: 'grow' }, h('h2', null, t('Volltexte')), h('div', { class: 'muted' }, t('{n} eingeschlossene Treffer aus dem Screening', { n: fmtInt(data.items.length) }))),
      btn(t('In Zotero nachsehen'), { icon: 'refresh', kind: 'ghost', onClick: refreshAll, title: t('Bei allen Texten prüfen, ob in Zotero ein Volltext liegt (PDF, EPUB, Word, ODT)') })),
    data.zotero_error ? notice('warning', t('Zotero ist gerade nicht erreichbar; es gilt der zuletzt bekannte Stand. Die Prüfung geht trotzdem: {e}', { e: data.zotero_error })) : null,
    data.items.some(it => !it.zotero_key) ? notice('info', t('Noch nicht übergebene Texte haben keinen Eintrag in Zotero; ihr Volltext wird deshalb nicht erkannt. Die Übergabe steht unter „Übergabe“.')) : null,
    shown.length ? h('div', { class: 'table-wrap card rs-table-card' }, h('table', { class: 'grid rs-ft-table' },
      h('thead', null, h('tr', null, h('th', { class: 'num' }, t('Jahr')), h('th', null, t('Titel')), h('th', null, t('Stand')), h('th', null))),
      h('tbody', null, shown.map(it => row(it, data, s.project)))))
      : h('div', { class: 'muted' }, icon('check', 14), ' ', t('Keine Texte in dieser Auswahl.'))),
  sideCards(data));
}
