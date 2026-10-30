// Übergabe: Auswahl je Zielordner nach Zotero (Web-API oder lokal, nur nach ausdrücklicher Bestätigung) und
// Protokoll als Markdown/CSV.
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, openModal, closeModal } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt } from '../../core/util.js';
import { btn, card, field, segmented, checkbox, notice, badge, emptyState, spinner } from '../../ui/components.js';
import { R, rs, enc, busy, isBusy, invalidate, refreshSummary, loadProject } from './common.js';

const hst = () => ui('rs-handover', { backend: null, crossref: true, status: {}, preview: null });

function backendOf() {
  const st = hst();
  return st.backend || (rs().project && rs().project.zotero_backend) || 'web';
}

function loadStatus(backend) {
  const st = hst();
  if (st.status[backend] !== undefined) return st.status[backend];
  st.status[backend] = null;
  api.get(`${R}/zotero/status?backend=${enc(backend)}`).then(r => { st.status[backend] = r; })
    .catch(err => { st.status[backend] = { ok: false, message: err.message }; }).finally(update);
  return null;
}

function loadPlan() {
  const s = rs();
  const backend = backendOf();
  const key = `plan:${backend}`;
  if ((s.plan && s.plan.backend === backend && !s.stale.plan) || s.busy[key]) return s.plan && s.plan.backend === backend ? s.plan : null;
  s.busy[key] = true;
  api.get(`${R}/projects/${s.pid}/export/zotero?backend=${enc(backend)}`).then(r => { s.plan = r; delete s.stale.plan; })
    .catch(err => { s.plan = { backend, error: err.message }; }).finally(() => { delete s.busy[key]; update(); });
  return null;
}

async function authorize() {
  const st = hst();
  toast(t('Zotero fragt jetzt nach der Freigabe – bitte in Zotero „Erlauben“ wählen.'), 'info', 8000);
  const r = await busy('authorize', () => api.post(`${R}/zotero/authorize`, { backend: 'local' }));
  if (r && r.ok) toast(t('Schreiben in Zotero freigegeben.'), 'success');
  else if (r) toast(t('Freigabe abgelehnt.'), 'warning');
  delete st.status.local;
  invalidate('plan');
  update();
}

function confirmExport(plan) {
  const s = rs();
  const st = hst();
  const tot = plan.totals;
  const libName = plan.library_name || plan.library;
  const doIt = async () => {
    const r = await busy('export', () => api.post(`${R}/projects/${s.pid}/export/zotero`, { backend: plan.backend, confirm: true, crossref: st.crossref }));
    closeModal();
    if (!r) return;
    toast(t('Zotero: {c} neu angelegt, {l} zugeordnet{f}.', { c: fmtInt(r.created), l: fmtInt(r.linked), f: r.failed.length ? t(', {n} Fehler', { n: r.failed.length }) : '' }),
      r.failed.length ? 'warning' : 'success', 9000);
    if (r.failed.length) toast(r.failed.slice(0, 3).map(x => x.error).join(' · '), 'error', 12000);
    invalidate('plan', 'pool', 'queue');
    refreshSummary(); loadProject();
  };
  openModal({
    title: t('Nach Zotero schreiben?'),
    body: () => h('div', { class: 'stack' },
      h('p', null, t('In „{lib}“ über {via}:', { lib: libName, via: plan.backend === 'local' ? t('die lokale Zotero-API') : t('die Zotero-Web-API') })),
      h('ul', null,
        h('li', null, tot.new === 1 ? t('1 Eintrag neu anlegen (Schlagwort „litsearch“)') : t('{n} Einträge neu anlegen (Schlagwort „litsearch“)', { n: fmtInt(tot.new) })),
        h('li', null, tot.link === 1 ? t('1 vorhandenen Eintrag dem Ordner zuordnen') : t('{n} vorhandene Einträge den Ordnern zuordnen', { n: fmtInt(tot.link) })),
        plan.create_collections.length ? h('li', null, t('Sammlungen anlegen: {c}', { c: plan.create_collections.join(', ') })) : null),
      checkbox({ checked: st.crossref, label: t('Angaben vorher über Crossref vervollständigen (Band, Heft, Seiten, Vornamen)'), onChange: v => { st.crossref = v; update(); } }),
      notice('warning', t('Das schreibt in deine Zotero-Bibliothek. Rückgängig nur in Zotero selbst.'))),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      { label: t('Jetzt nach Zotero schreiben'), kind: 'primary', icon: 'send', busy: isBusy('export'), onClick: doIt }],
  });
}

function folderTable(plan) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
    h('thead', null, h('tr', null, h('th', null, t('Ordner')), h('th', null, t('Sammlung')), h('th', { class: 'num' }, t('neu')),
      h('th', { class: 'num' }, t('zuordnen')), h('th', { class: 'num' }, t('schon übergeben')))),
    h('tbody', null, plan.folders.map(f => h('tr', { key: f.slot },
      h('td', null, h('kbd', { class: 'rs-kbd' }, String(f.slot)), ' ', f.label),
      h('td', null, f.path, ' ', f.collection_key ? badge(t('vorhanden'), 'success') : badge(t('wird angelegt'), 'warning')),
      h('td', { class: 'num' }, fmtInt(f.new.length)), h('td', { class: 'num' }, fmtInt(f.link.length)), h('td', { class: 'num' }, fmtInt(f.done.length)))))));
}

function zoteroCard() {
  const s = rs();
  const st = hst();
  const backend = backendOf();
  const status = loadStatus(backend);
  const plan = loadPlan();
  const statusLine = status == null ? h('span', { class: 'muted' }, spinner(12), ' ', t('prüfe Zotero …'))
    : h('span', { class: status.ok ? 'ok-text' : 'danger-text' }, status.message || (status.ok ? 'OK' : t('nicht erreichbar')));
  let body;
  if (!plan) body = h('div', { class: 'muted' }, t('Lade Plan …'));
  else if (plan.error) body = notice('error', plan.error);
  else if (!plan.folders.length) body = notice('warning', t('Noch keine Ordner zugeordnet. Unter „Ordner“ Ordner anlegen und Sammlungen festlegen.'));
  else {
    const tot = plan.totals;
    body = h('div', { class: 'stack' },
      folderTable(plan),
      plan.unassigned.length ? notice('warning', t('{n} eingeschlossene Treffer haben keinen zugeordneten Ordner und werden nicht übertragen.', { n: plan.unassigned.length })) : null,
      !plan.can_write ? notice('warning', backend === 'local'
        ? h('div', null, t('Schreiben in Zotero ist noch nicht freigegeben.'), h('div', { class: 'notice-actions' }, btn(t('Freigabe in Zotero anfordern'), { size: 'sm', busy: isBusy('authorize'), onClick: authorize })))
        : t('Der API-Schlüssel darf in diese Bibliothek nicht schreiben.')) : null,
      h('div', { class: 'row' },
        h('span', { class: 'muted small grow' }, tot.new + tot.link ? t('{n} neu, {l} zuordnen, {d} schon übergeben', { n: fmtInt(tot.new), l: fmtInt(tot.link), d: fmtInt(tot.done) })
          : t('Nichts zu übertragen.')),
        btn(t('Neu berechnen'), { size: 'sm', kind: 'ghost', icon: 'refresh', onClick: () => { invalidate('plan'); delete st.status[backend]; update(); } }),
        btn(t('Nach Zotero übertragen …'), { kind: 'primary', icon: 'send', disabled: !plan.can_write || !(tot.new + tot.link), onClick: () => confirmExport(plan) })));
  }
  return card(t('Auswahl nach Zotero'), 'zotero', h('div', { class: 'stack' },
    h('div', { class: 'row wrap' },
      segmented({ size: 'sm', value: backend, options: [{ value: 'web', label: t('Web-API') }, { value: 'local', label: t('Zotero lokal') }],
        onChange: v => { st.backend = v; invalidate('plan'); update(); } }),
      statusLine),
    h('div', { class: 'muted small' }, t('Ziel: {lib}', { lib: s.project.target_name || s.project.target_library })),
    body));
}

async function preview(kind) {
  const s = rs();
  const st = hst();
  st.preview = await run(() => api.get(`${R}/projects/${s.pid}/protocol?kind=${kind}`));
  update();
}

async function download(kind) {
  const s = rs();
  const res = await run(async () => {
    const r = await fetch(`${R}/projects/${s.pid}/protocol?kind=${kind}`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return { text: await r.text(), name: r.headers.get('X-Filename') || `protokoll.${kind === 'md' ? 'md' : 'csv'}` };
  });
  await api.saveText(res.name, res.text, kind === 'md' ? 'text/markdown' : 'text/csv');
}

function protocolCard() {
  const st = hst();
  return card(t('Protokoll'), 'review', h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Quellen, Suchstrings mit Datum und Version, Trefferzahlen, Duplikate, Vorfilter, Ein- und Ausschlüsse je Grund und die ausgewählte Literatur – im Stil von PRISMA-S.')),
    h('div', { class: 'row wrap' },
      btn(t('Markdown speichern'), { icon: 'download', onClick: () => download('md') }),
      btn(t('Suchen als CSV'), { icon: 'download', kind: 'ghost', onClick: () => download('runs') }),
      btn(t('Treffer und Entscheide als CSV'), { icon: 'download', kind: 'ghost', onClick: () => download('records') }),
      h('span', { class: 'spacer' }),
      btn(st.preview ? t('Vorschau aktualisieren') : t('Vorschau'), { size: 'sm', kind: 'ghost', icon: 'review', onClick: () => preview('md') })),
    st.preview && h('pre', { class: 'rs-protocol' }, st.preview)));
}

export function handoverTab() {
  const s = rs();
  const sum = s.project.summary || {};
  return h('div', { class: 'view-body scroll' },
    h('div', { class: 'stack-lg rs-narrow' },
      !sum.included ? emptyState('send', t('Noch nichts ausgewählt'), t('Im Screening Treffer in die Ordner aufnehmen.')) : zoteroCard(),
      protocolCard()));
}
