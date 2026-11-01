// Suche & Import: links die Suchstrings je Quelle (versioniert) mit Trefferzahl, Suche ausführen (einzeln, je Quelle oder
// alle); rechts Suchstrings aus Dateien, RIS-Import per Drop-Zone, weitere Quellen und das Protokoll der Läufe. Der Pool folgt der jeweils letzten
// Suche je Suchstring; gelöschte Suchstrings nehmen ihre Treffer mit (schon entschiedene bleiben).
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, openModal, closeModal, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt, fmtDate, debounce, copyToClipboard } from '../../core/util.js';
import { btn, iconBtn, card, field, textInput, textArea, select, checkbox, notice, emptyState, spinner, numberInput } from '../../ui/components.js';
import { icon } from '../../ui/icons.js';
import { R, rs, lazy, busy, isBusy, invalidate, refreshSummary, sourceLabel, isLive, projectSources, catalogEntry, limitsText, dropZone, readFileB64, workspace, serverText } from './common.js';

const OSF_PROVIDERS = [{ value: 'psyarxiv', label: 'PsyArXiv' }, { value: 'socarxiv', label: 'SocArXiv' },
  { value: 'edarxiv', label: 'EdArXiv' }, { value: 'osf', label: 'OSF Preprints' }];
const OA_TYPES = [{ value: 'article', label: t('Artikel') }, { value: 'review', label: t('Review') },
  { value: 'book-chapter', label: t('Buchkapitel') }, { value: 'book', label: t('Buch') }];

const queriesOf = s => lazy('queries', `${R}/projects/${s.pid}/queries`, r => r.queries);
const runsOf = s => lazy('runs', `${R}/projects/${s.pid}/runs`, r => r.runs);

function afterPoolChange() {
  invalidate('queries', 'runs', 'pool', 'queue', 'plan');
  refreshSummary();
}

// ------------------------------------------------------------------ Zählen und Suchen
// Hinweise der Datenbank (z. B. „quotedphrasesnotfound“) je Suchstring – in der Zeile statt als Meldung
const warnings = () => ui('rs-warnings', {});

async function countQuery(q) {
  const r = await busy(`count:${q.id}`, () => api.post(`${R}/queries/${q.id}/count`));
  if (!r) return;
  Object.assign(q, r);
  warnings()[q.id] = r.warnings || [];
  update();
}

async function runQuery(q, { quiet = false } = {}) {
  const r = await busy(`run:${q.id}`, () => api.post(`${R}/queries/${q.id}/run`, {}));
  if (!r) return null;
  warnings()[q.id] = r.warnings || [];
  if (!quiet) {
    toast(t('{n}: {h} Treffer, {f} geholt, {new} neu im Pool, {d} schon da.', { n: q.name, h: fmtInt(r.hits), f: fmtInt(r.fetched), new: fmtInt(r.new), d: fmtInt(r.duplicates) }),
      'success', 6000);
  }
  afterPoolChange();
  return r;
}

async function runAll(source, list, fn, label) {
  const st = ui('rs-search', {});
  st.batch = { source, label, done: 0, total: list.length };
  update();
  const results = [];
  try {
    for (const q of list) {
      if (!st.batch) break;  // abgebrochen
      try { results.push(await fn(q)); } catch { /* Meldung kam schon */ }
      if (st.batch) st.batch.done += 1;
      update();
    }
  } finally {
    st.batch = null;
    update();
  }
  return results.filter(Boolean);
}

async function searchAll(source, list) {
  const res = await runAll(source, list, q => runQuery(q, { quiet: true }), t('Suchen'));
  if (!res.length) return;
  const sum = k => res.reduce((a, r) => a + (r[k] || 0), 0);
  toast(t('{s}: {n} Suchen, {f} Datensätze geholt, {new} neu im Pool, {d} schon da.', { s: source === '*' ? t('Alle Quellen') : sourceLabel(source), n: res.length,
    f: fmtInt(sum('fetched')), new: fmtInt(sum('new')), d: fmtInt(sum('duplicates')) }), 'success', 8000);
}

// Über alle Suchstrings und Quellen hinweg (nur direkt durchsuchbare; RIS-Quellen werden importiert)
const liveQueries = queries => (queries || []).filter(q => isLive(q.source));

// ------------------------------------------------------------------ Suchstring bearbeiten / neu
function editQuery(q, source) {
  const s = rs();
  const isNew = !q;
  const d = { name: q ? q.name : '', source: q ? q.source : source || 'pubmed', string: q ? q.string : '',
    limits: { ...(q ? q.limits : {}) }, preview: null, seq: 0 };
  const preview = debounce(async () => {
    if (!isLive(d.source) || !d.string.trim()) { d.preview = null; update(); return; }
    const seq = ++d.seq;
    d.preview = { loading: true };
    update();
    try {
      const r = await api.post(`${R}/count`, { source: d.source, string: d.string, limits: d.limits });
      if (seq === d.seq) d.preview = r;
    } catch (err) { if (seq === d.seq) d.preview = { error: err.message }; }
    update();
  }, 700);
  const setLimit = (k, v) => { if (v === '' || v == null || (Array.isArray(v) && !v.length)) delete d.limits[k]; else d.limits[k] = v; preview(); update(); };
  const save = async () => {
    const body = { name: d.name.trim(), string: d.string.trim(), limits: d.limits };
    if (isNew) await busy('save-query', () => api.post(`${R}/projects/${s.pid}/queries`, { ...body, source: d.source }));
    else await busy('save-query', () => api.put(`${R}/queries/${q.id}`, body));
    closeModal();
    afterPoolChange();  // neuer Name: der Pool folgt dem Suchstring
    update();
  };
  preview();
  openModal({
    title: isNew ? t('Neuer Suchstring') : t('Suchstring „{n}“ (v{v})', { n: q.name, v: q.version }), cls: 'modal-wide',
    body: () => h('div', { class: 'stack' },
      h('div', { class: 'field-row' },
        field(t('Name'), textInput({ value: d.name, placeholder: 'K1_Konflikt', onInput: v => { d.name = v; update(); } })),
        field(t('Quelle'), isNew ? select({ value: d.source, options: sourceChoices().map(v => ({ value: v, label: sourceLabel(v) })),
          onChange: v => { d.source = v; preview(); update(); } }) : h('div', { class: 'rs-static' }, sourceLabel(d.source)))),
      field(t('Suchstring'), textArea({ value: d.string, rows: 8, class: 'rs-mono', onInput: v => { d.string = v; preview(); update(); } }),
        { hint: !isNew ? t('Ein geänderter String wird als neue Version gespeichert; frühere Läufe behalten ihre Version.') : null }),
      (d.notes || []).length ? notice('info', h('div', null, d.notes.map((n, i) => h('div', { key: i }, serverText(n))))) : null,
      h('div', { class: 'row wrap' },
        field(t('Jahr ab'), numberInput({ value: d.limits.year_from ?? '', nullable: true, int: true, min: 1800, max: 2100, onChange: v => setLimit('year_from', v) })),
        field(t('Jahr bis'), numberInput({ value: d.limits.year_to ?? '', nullable: true, int: true, min: 1800, max: 2100, onChange: v => setLimit('year_to', v) })),
        isLive(d.source) && field(t('Höchstens holen'), numberInput({ value: d.limits.max ?? '', nullable: true, int: true, min: 1, max: 10000, step: 100,
          placeholder: d.source === 'pubmed' ? '10000' : d.source === 'openalex' ? '200' : '', onChange: v => setLimit('max', v) })),
        d.source === 'osf' && field(t('Server (OSF)'), h('div', { class: 'chips' }, OSF_PROVIDERS.map(o => {
          const on = (d.limits.providers || []).includes(o.value);
          return h('button', { type: 'button', key: o.value, class: ['chip', on && 'chip-accent'], onclick: () => {
            const set = new Set(d.limits.providers || []); on ? set.delete(o.value) : set.add(o.value); setLimit('providers', [...set]);
          } }, h('span', null, o.label));
        }))),
        d.source === 'eric' && field(t('ERIC'), checkbox({ checked: !!d.limits.peer_reviewed, label: t('nur begutachtet (peer reviewed)'),
          onChange: v => setLimit('peer_reviewed', v || null) })),
        d.source === 'openalex' && field(t('Typen (OpenAlex)'), h('div', { class: 'chips' }, OA_TYPES.map(o => {
          const on = (d.limits.types || []).includes(o.value);
          return h('button', { type: 'button', key: o.value, class: ['chip', on && 'chip-accent'], onclick: () => {
            const set = new Set(d.limits.types || []); on ? set.delete(o.value) : set.add(o.value); setLimit('types', [...set]);
          } }, h('span', null, o.label));
        })))),
      catalogEntry(d.source) && h('div', { class: 'muted small' }, catalogEntry(d.source).note),
      isLive(d.source) && h('div', { class: 'row' }, h('span', { class: 'muted' }, t('Vorschau:')),
        !d.preview ? h('span', { class: 'muted' }, '–') : d.preview.loading ? spinner(13)
          : d.preview.error ? h('span', { class: 'danger-text small' }, d.preview.error)
            : h('b', null, d.preview.upper_bound ? t('bis zu {n} Treffer', { n: fmtInt(d.preview.count) }) : t('{n} Treffer', { n: fmtInt(d.preview.count) })),
        d.preview && (d.preview.warnings || []).length ? h('span', { class: 'warn-text small' }, d.preview.warnings.map(serverText).join(' ')) : null),
      d.preview && d.preview.translation ? h('details', { class: 'small' }, h('summary', null, t('So versteht PubMed den String')),
        h('pre', { class: 'rs-string' }, d.preview.translation)) : null),
    actions: () => [
      { label: t('Abbrechen'), onClick: closeModal },
      { label: t('Speichern'), kind: 'primary', disabled: !d.name.trim() || !d.string.trim(), busy: isBusy('save-query'), onClick: save }],
  });
}

// Quellen, für die man Suchstrings anlegen kann: die gewählten Datenbanken des Projekts, PubMed und OpenAlex immer
function sourceChoices() {
  const chosen = projectSources().filter(x => x !== 'ris');
  return [...new Set(['pubmed', 'openalex', ...chosen, 'psycinfo', 'wos'])];
}

// RIS-Import: Datenbanken ohne offene API (Export von Hand), die gewählten zuerst
function risChoices() {
  const s = rs();
  const known = ((s.info && s.info.sources) || []).map(x => x.id);
  const exportish = ((s.info && s.info.catalog) || []).filter(c => ['export', 'license'].includes(c.access) && known.includes(c.id)).map(c => c.id);
  const chosen = projectSources().filter(x => exportish.includes(x));
  return [...new Set([...chosen, ...exportish])];
}

// PubMed-String in die gewählten Datenbanken übersetzen (je Datenbank eine neue Version mit gleichem Namen)
function translateQuery(q) {
  const s = rs();
  const translatable = (s.info && s.info.translatable) || ['openalex'];
  const targets = projectSources().filter(x => translatable.includes(x));
  const d = { sel: new Set(targets.length ? targets : ['openalex']), result: null };
  const all = [...new Set([...targets, ...translatable])];
  const go = async () => {
    const r = await busy('translate', () => api.post(`${R}/queries/${q.id}/translate`, { targets: [...d.sel] }));
    if (!r) return;
    d.result = r.queries;
    invalidate('queries');
    update();
  };
  openModal({
    title: t('„{n}“ übersetzen', { n: q.name }), cls: 'modal-wide',
    body: () => h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Aus dem PubMed-String (v{v}) entsteht je Datenbank ein eigener Suchstring mit gleichem Namen. Danach prüfen und zählen – die Übersetzung ist ein Vorschlag.', { v: q.version })),
      h('div', { class: 'chips' }, all.map(x => {
        const on = d.sel.has(x);
        return h('button', { type: 'button', key: x, class: ['chip', on && 'chip-accent'], onclick: () => { on ? d.sel.delete(x) : d.sel.add(x); update(); } },
          h('span', null, sourceLabel(x) + (targets.includes(x) ? '' : ` (${t('nicht gewählt')})`)));
      })),
      d.result && h('div', { class: 'stack-sm' }, d.result.map(x => h('div', { key: x.id, class: 'rs-built' },
        h('div', { class: 'row' }, h('b', null, sourceLabel(x.source)), h('span', { class: 'muted small' }, `v${x.version}`)),
        h('pre', { class: 'rs-string' }, x.string),
        (x.notes || []).map((n, i) => h('div', { class: 'muted small', key: i }, '· ', serverText(n))))))),
    actions: () => d.result ? [{ label: t('Schliessen'), kind: 'primary', onClick: closeModal }] : [
      { label: t('Abbrechen'), onClick: closeModal },
      { label: t('Übersetzen'), kind: 'primary', icon: 'globe', disabled: !d.sel.size, busy: isBusy('translate'), onClick: go }],
  });
}

async function removeQuery(q) {
  if (!(await confirmDialog(t('Suchstring löschen?'), t('„{n}“ ({s}) mit allen Versionen löschen? Seine Treffer verschwinden aus dem Pool, ausser sie stammen auch aus einem anderen Suchstring oder sind schon entschieden. Das Protokoll der Läufe bleibt.', { n: q.name, s: sourceLabel(q.source) }), { ok: t('Löschen'), danger: true }))) return;
  await run(() => api.del(`${R}/queries/${q.id}`));
  afterPoolChange();
  update();
}

// ------------------------------------------------------------------ Tabellen
function queryRow(q) {
  const live = isLive(q.source);
  const last = q.last_run;
  const st = ui('rs-q-open', {});
  const open = !!st[q.id];
  return [
    h('tr', { key: `q${q.id}` },
      h('td', null, h('button', { type: 'button', class: 'rs-link', onclick: () => { st[q.id] = !open; update(); } }, h('b', null, q.name)),
        ' ', h('span', { class: 'muted small', title: q.note || '' }, `v${q.version}`),
        limitsText(q.limits) && h('div', { class: 'muted small' }, limitsText(q.limits))),
      h('td', { class: 'rs-string-cell' }, h('div', { class: 'rs-clamp rs-mono small', title: q.string, onclick: () => { st[q.id] = !open; update(); } }, q.string),
        (warnings()[q.id] || []).length ? h('div', { class: 'warn-text small rs-clamp1', title: warnings()[q.id].map(serverText).join('\n') },
          icon('alert', 12), warnings()[q.id].map(serverText).join(' · ')) : null),
      h('td', { class: 'num' }, live ? (isBusy(`count:${q.id}`) ? spinner(13) : q.last_count != null
        ? h('b', { title: q.upper_bound ? t('Obergrenze – die übrigen Blöcke prüft die App nach dem Abruf') : undefined }, (q.upper_bound ? '≤ ' : '') + fmtInt(q.last_count))
        : h('span', { class: 'muted' }, '–')) : h('span', { class: 'muted small' }, t('in der Datenbank'))),
      h('td', { class: 'small' }, last ? h('div', { title: fmtDate(last.run_at) },
        h('div', null, t('{f} geholt · {n} neu', { f: fmtInt(last.fetched), n: fmtInt(last.new_records) })),
        !q.current_run ? h('div', { class: 'warn-text small rs-old-version', title: t('Die letzte Suche lief mit einer früheren Version dieses Suchstrings. Erst „Suchen“ führt die aktuelle Version aus; das Kreissymbol holt nur die Trefferzahl.') },
          t('mit v{v} gesucht – neu suchen', { v: last.version })) : null)
        : h('span', { class: 'muted' }, t('noch nicht gesucht'))),
      h('td', { class: 'nowrap rs-q-actions' },
        live && iconBtn('refresh', t('Trefferzahl holen'), () => countQuery(q), { disabled: isBusy(`count:${q.id}`) }),
        live && btn(t('Suchen'), { size: 'sm', icon: 'play', kind: q.current_run ? 'secondary' : 'primary', busy: isBusy(`run:${q.id}`), onClick: () => runQuery(q) }),
        iconBtn('edit', t('Bearbeiten'), () => editQuery(q)),
        q.source === 'pubmed' && iconBtn('globe', t('In die gewählten Datenbanken übersetzen'), () => translateQuery(q)),
        iconBtn('copy', t('Kopieren'), async () => { await copyToClipboard(q.string); toast(t('Kopiert.'), 'success', 1500); }),
        iconBtn('trash', t('Löschen'), () => removeQuery(q)))),
    open && h('tr', { key: `qd${q.id}`, class: 'rs-detail-row' }, h('td', { colspan: 5 },
      h('pre', { class: 'rs-string' }, q.string),
      q.translation && h('details', { class: 'small' }, h('summary', null, t('So versteht PubMed den String')), h('pre', { class: 'rs-string' }, q.translation)),
      q.note && h('div', { class: 'muted small' }, q.note))),
  ];
}

function sourceCard(source, list) {
  const st = ui('rs-search', {});
  const live = isLive(source);
  const batch = st.batch && st.batch.source === source ? st.batch : null;
  const total = list.reduce((a, q) => a + (q.last_count || 0), 0);
  return card(`${sourceLabel(source)} (${list.length})`, live ? 'search' : 'file', h('div', { class: 'stack-sm' },
    batch && h('div', { class: 'row' }, spinner(14), h('span', null, `${batch.label}: ${batch.done}/${batch.total}`),
      btn(t('Anhalten'), { size: 'sm', kind: 'ghost', onClick: () => { st.batch = null; update(); } })),
    h('div', { class: 'table-wrap' }, h('table', { class: 'grid rs-queries' },
      h('colgroup', null, h('col', { class: 'rs-qc-name' }), h('col'), h('col', { class: 'rs-qc-hits' }), h('col', { class: 'rs-qc-last' }), h('col', { class: 'rs-qc-actions' })),
      h('thead', null, h('tr', null, h('th', null, t('Name')), h('th', null, t('Suchstring')), h('th', { class: 'num' }, t('Treffer')),
        h('th', null, t('Letzte Suche')), h('th', null))),
      h('tbody', null, list.map(queryRow)))),
    live && list.length > 1 && h('div', { class: 'muted small' }, t('Summe der Trefferzahlen: {n} (vor dem Entfernen von Duplikaten)', { n: fmtInt(total) }))),
  { actions: live ? [
    btn(t('Alle zählen'), { size: 'sm', icon: 'refresh', kind: 'ghost', disabled: !!st.batch, onClick: () => runAll(source, list, countQuery, t('Zählen')) }),
    btn(t('Alle suchen'), { size: 'sm', icon: 'play', disabled: !!st.batch, onClick: () => searchAll(source, list) }),
  ] : null });
}

// Protokoll der Läufe: als Dialog, die Tabelle braucht die Breite
function showRuns(runs) {
  openModal({ title: t('Protokoll der Läufe'), cls: 'modal-xl', body: () => h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
    h('thead', null, h('tr', null, ['Datum', 'Quelle', 'Suchstring', 'Treffer', 'geholt', 'neu', 'Duplikate'].map((x, i) => h('th', { class: i > 2 ? 'num' : '' }, t(x))))),
    h('tbody', null, runs.slice().reverse().map(r => h('tr', { key: r.id },
      h('td', { class: 'nowrap small', title: r.searched_on ? t('Tag der Suche in der Datenbank; importiert am {d}', { d: fmtDate(r.run_at) }) : undefined }, r.searched_on || fmtDate(r.run_at)),
      h('td', null, sourceLabel(r.source), r.kind === 'import' ? h('span', { class: 'muted small' }, ` · ${r.filename}`) : null),
      h('td', null, r.name, r.version ? h('span', { class: 'muted small' }, ` v${r.version}`) : null, r.note ? h('div', { class: 'warn-text small' }, r.note) : null),
      h('td', { class: 'num' }, r.hits != null ? fmtInt(r.hits) : '–'),
      h('td', { class: 'num' }, fmtInt(r.fetched)), h('td', { class: 'num' }, fmtInt(r.new_records)), h('td', { class: 'num' }, fmtInt(r.duplicates))))))),
  actions: [{ label: t('Schliessen'), kind: 'primary', onClick: closeModal }] });
}

// Weitere Quellen ausserhalb der Datenbanken (Websites, Register, Referenzlisten, Anfragen bei Autorinnen): fürs Protokoll
function otherSourcesCard() {
  const s = rs();
  const list = (s.project.settings || {}).other_sources || [];
  const save = async next => {
    const p = await run(() => api.put(`${R}/projects/${s.pid}`, { settings: { other_sources: next } }));
    s.project.settings = p.settings;
    invalidate('flow');
    update();
  };
  const edit = i => {
    const d = i == null ? { name: '', date: '', records: '', note: '' } : { ...list[i] };
    openModal({ title: i == null ? t('Weitere Quelle') : d.name,
      body: () => h('div', { class: 'stack' },
        field(t('Quelle'), textInput({ value: d.name, placeholder: t('z. B. Referenzlisten, Google Scholar, Register'), onInput: v => { d.name = v; update(); } })),
        field(t('Datum'), textInput({ type: 'date', value: d.date, onInput: v => { d.date = v; } })),
        field(t('Datensätze (optional)'), numberInput({ value: d.records ?? '', nullable: true, int: true, min: 0, onChange: v => { d.records = v; } })),
        field(t('Bemerkung (optional)'), textInput({ value: d.note, onInput: v => { d.note = v; } }))),
      actions: () => [
        ...(i == null ? [] : [{ label: t('Entfernen'), kind: 'danger', onClick: () => { closeModal(); save(list.filter((_, j) => j !== i)); } }]),
        { label: t('Abbrechen'), onClick: closeModal },
        { label: t('Übernehmen'), kind: 'primary', disabled: !d.name.trim(), onClick: () => { closeModal(); save(i == null ? [...list, d] : list.map((x, j) => (j === i ? d : x))); } }] });
  };
  return card(t('Weitere Quellen'), 'link', h('div', { class: 'stack-sm' },
    h('p', { class: 'muted small' }, t('Was ausserhalb der Datenbanken durchsucht wurde. Gehört ins Protokoll; Treffer daraus als RIS importieren.')),
    list.length ? h('div', { class: 'stack-sm' }, list.map((x, i) => h('button', { type: 'button', key: i, class: 'rs-other', onclick: () => edit(i) },
      h('b', null, x.name), h('span', { class: 'muted small' }, [x.date, x.records != null && x.records !== '' ? t('{n} Datensätze', { n: fmtInt(x.records) }) : ''].filter(Boolean).join(' · '))))) : null,
    h('div', null, btn(t('Quelle hinzufügen'), { size: 'sm', icon: 'plus', onClick: () => edit(null) }))));
}

// ------------------------------------------------------------------ Dateien
function filesCard() {
  const s = rs();
  const st = ui('rs-import', { qsource: 'pubmed', risSource: 'psycinfo', risName: '', risString: '', risHits: null, risDate: '' });
  const importQueries = files => busy('import-queries', async () => {
    const payload = await Promise.all(files.filter(f => /\.(txt|text)$/i.test(f.name)).map(readFileB64));
    if (!payload.length) { toast(t('Bitte Textdateien (.txt) mit je einem Suchstring wählen.'), 'warning'); return; }
    const r = await api.post(`${R}/projects/${s.pid}/queries/import`, { files: payload, source: st.qsource });
    invalidate('queries');
    toast(t('{n} Suchstrings geladen.', { n: r.queries.length }), 'success');
  });
  const importRis = files => busy('import-ris', async () => {
    let total = { fetched: 0, new: 0, duplicates: 0 };
    for (const f of files) {
      const payload = await readFileB64(f);
      const r = await api.post(`${R}/projects/${s.pid}/import`, { ...payload, source: st.risSource, name: st.risName || '',
        string: st.risString || '', hits: st.risHits ?? null, searched_on: st.risDate || '' });
      total = { fetched: total.fetched + r.fetched, new: total.new + r.new, duplicates: total.duplicates + r.duplicates };
    }
    toast(t('Import: {f} Datensätze, {n} neu im Pool, {d} schon da.', { f: fmtInt(total.fetched), n: fmtInt(total.new), d: fmtInt(total.duplicates) }), 'success', 6000);
    afterPoolChange();
  });
  return [
    card(t('RIS-Import'), 'upload', h('div', { class: 'stack-sm' },
      h('p', { class: 'muted small' }, t('Exporte aus Ovid PsycInfo, Web of Science oder EBSCO. Suchstring, Suchdatum und Trefferzahl stehen im Protokoll.')),
      field(t('Quelle'), select({ value: st.risSource, options: [...risChoices().map(v => ({ value: v, label: sourceLabel(v) })), { value: 'ris', label: t('andere') }],
        onChange: v => { st.risSource = v; update(); } })),
      field(t('Name des Suchstrings'), textInput({ value: st.risName, placeholder: t('wie Datei'), onInput: v => { st.risName = v; update(); } })),
      field(t('Suchstring (optional)'), textInput({ value: st.risString, onInput: v => { st.risString = v; update(); } })),
      field(t('Suchdatum'), textInput({ type: 'date', value: st.risDate, onInput: v => { st.risDate = v; update(); } }),
        { hint: t('Tag der Suche in der Datenbank, nicht des Imports.') }),
      field(t('Trefferzahl laut Datenbank'), numberInput({ value: st.risHits ?? '', nullable: true, int: true, min: 0, onChange: v => { st.risHits = v; update(); } })),
      dropZone({ id: 'ris', label: t('.ris-Dateien hierher ziehen oder klicken'), accept: '.ris,.txt', onFiles: importRis, busyKey: 'import-ris' }))),
    card(t('Suchstrings aus Dateien'), 'file', h('div', { class: 'stack-sm' },
      h('p', { class: 'muted small' }, t('Eine Textdatei je Suchstring. Name = Dateiname.')),
      field(t('Quelle'), select({ value: st.qsource, options: sourceChoices().map(v => ({ value: v, label: sourceLabel(v) })),
        onChange: v => { st.qsource = v; update(); } })),
      dropZone({ id: 'queries', label: t('.txt-Dateien hierher ziehen oder klicken'), accept: '.txt,text/plain', onFiles: importQueries, busyKey: 'import-queries' })))];
}

export function searchTab() {
  const s = rs();
  const queries = queriesOf(s);
  const runs = runsOf(s);
  const groups = {};
  for (const q of queries || []) (groups[q.source] || (groups[q.source] = [])).push(q);
  const known = ((s.info && s.info.sources) || []).map(x => x.id);
  const order = [...new Set([...known, ...Object.keys(groups)])].filter(src => groups[src]);
  const st = ui('rs-search', {});
  const everything = st.batch && st.batch.source === '*' ? st.batch : null;
  const live = liveQueries(queries);
  return workspace('search', h('div', { class: 'stack-lg' },
      h('div', { class: 'row wrap' }, h('h2', { class: 'grow' }, t('Suchstrings')),
        live.length > 1 ? btn(t('Alle zählen ({n})', { n: live.length }), { icon: 'refresh', kind: 'ghost', disabled: !!st.batch,
          title: t('Trefferzahl für alle Suchstrings aller Quellen holen'), onClick: () => runAll('*', live, countQuery, t('Zählen')) }) : null,
        live.length > 1 ? btn(t('Alle suchen ({n})', { n: live.length }), { icon: 'play', disabled: !!st.batch,
          title: t('Alle Suchstrings aller direkt durchsuchbaren Quellen nacheinander suchen; der Pool folgt danach der jeweils letzten Suche'),
          onClick: () => searchAll('*', live) }) : null,
        btn(t('Suchstring hinzufügen'), { icon: 'plus', kind: 'primary', onClick: () => editQuery(null) })),
      everything ? h('div', { class: 'row' }, spinner(14), h('span', null, `${everything.label}: ${everything.done}/${everything.total}`),
        btn(t('Anhalten'), { size: 'sm', kind: 'ghost', onClick: () => { st.batch = null; update(); } })) : null,
      queries == null ? h('div', { class: 'muted' }, t('Lade …'))
        : order.length ? order.map(src => h('div', { key: src }, sourceCard(src, groups[src])))
          : emptyState('search', t('Noch keine Suchstrings'), t('Aus der Suchstrategie übernehmen, von Hand einfügen oder als Textdateien laden.'))),
  [filesCard(), otherSourcesCard(),
    runs && runs.length ? h('div', { key: 'runs' }, btn(t('Protokoll der Läufe ({n})', { n: fmtInt(runs.length) }), { icon: 'history', onClick: () => showRuns(runs) })) : null]);
}
