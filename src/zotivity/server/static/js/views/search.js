// Suchen: Such-Engine ohne Sprachmodell über alle Zotero-Bibliotheken (eigene und Gruppen).
// Einfeld- und Mehrfeldsuche, Filter (Jahr, Eintragsart, Bibliothek, Sammlung, PDF, Index), Volltext der
// indexierten Texte. Treffer zeigen ihren Ort in Zotero und lassen sich in Korpora des Projekts aufnehmen.
// Links der Suchverlauf des aktiven Projekts: ein Klick füllt die Suchfelder (ohne zu suchen).
// Auswahl: bleibt über mehrere Suchen erhalten (je Projekt); die Leiste darüber kopiert Literaturliste und
// Kurzbelege im eingestellten Zitierstil, exportiert (Word, BibTeX, RIS, Markdown), nimmt in Korpora oder eine
// Zotero-Sammlung auf und öffnet „Fragen“ mit genau diesen Einträgen. Shift+Klick: Bereich, Strg+A: alle, Esc: aufheben.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, watchJob, runningJob, loadCorpora, loadProjects, projectCorpora, project, openModal, closeModal, confirmDialog,
  submitIndexRun } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, notice, spinner, field, textInput, numberInput, checkbox, select, multiSelect, badge, emptyState, openMenu, combo, segmented, paneProps, splitter } from '../ui/components.js';
import { fmtInt, fmtAgo, esc, copyToClipboard } from '../core/util.js';
import { itemTypeLabel } from '../core/zotero.js';
import { navigate, viewHeader } from './shell.js';

const EMPTY_QUERY = { q: '', title: '', creator: '', publication: '', abstract: '', tags: '', doi: '', fulltext: '',
  year_from: null, year_to: null, item_types: [], libraries: [], collections: [], has_pdf: false, indexed: false, sort: 'relevance' };
const ADVANCED_KEYS = ['title', 'creator', 'publication', 'abstract', 'tags', 'doi', 'fulltext', 'year_from', 'year_to',
  'item_types', 'libraries', 'collections', 'has_pdf', 'indexed'];

function st() {
  return ui('search', { query: { ...EMPTY_QUERY }, advanced: false, results: null, total: 0, busy: false,
    picked: new Map(), showPicked: false, lastIdx: null,
    status: null, statusLoading: false, offset: 0, autoSynced: false, error: null,
    history: null, historyFor: null, historyBusy: false, historyFilter: '', activeId: null, fromHistory: null });
}

// ------------------------------------------------------------------ Suchverlauf (je Projekt)
async function loadHistory() {
  const s = st();
  const pid = state.projectId;
  if (pid == null || s.historyBusy) return;
  s.historyBusy = true;
  try { s.history = (await api.get(`/api/library/searches?project=${pid}`)).searches; } catch { s.history = s.history || []; }
  s.historyFor = pid;
  s.historyBusy = false;
  update();
}

// Gespeicherte Suche in die Suchfelder übernehmen – gesucht wird erst mit „Suchen“, damit sie sich vorher ändern lässt
function applySearch(entry) {
  const s = st();
  s.query = { ...EMPTY_QUERY, ...entry.query, sort: entry.sort || 'relevance' };
  s.advanced = ADVANCED_KEYS.some(k => k in entry.query);
  s.activeId = entry.id;
  s.fromHistory = entry;
  s.results = null; s.total = 0; s.error = null; s.showPicked = false; s.lastIdx = null;
  update();
  setTimeout(() => document.getElementById('search-q')?.focus(), 0);
}

async function forgetSearch(entry) {
  const s = st();
  const r = await run(() => api.del(`/api/library/searches?project=${state.projectId}&id=${entry.id}`));
  s.history = r.searches;
  if (s.activeId === entry.id) s.activeId = null;
  update();
}

async function clearHistory() {
  const s = st();
  const p = project();
  const ok = await confirmDialog(t('Suchverlauf leeren?'),
    t('Alle {n} gespeicherten Suchen des Projekts „{name}“ werden entfernt.', { n: (s.history || []).length, name: p ? p.name : '' }),
    { ok: t('Leeren'), danger: true });
  if (!ok) return;
  const r = await run(() => api.del(`/api/library/searches?project=${state.projectId}`));
  s.history = r.searches;
  s.activeId = null;
  update();
}

// Kurzbeschreibung einer gespeicherten Suche: Hauptzeile (Suchbegriff) und weitere Felder/Filter
function historyLabel(q, libNames, collNames) {
  const fields = { title: t('Titel'), creator: t('Autor/in'), publication: t('Publikation'), abstract: t('Abstract'),
    tags: t('Schlagwörter'), doi: 'DOI', fulltext: t('Volltext') };
  const terms = Object.keys(fields).filter(k => q[k]).map(k => `${fields[k]}: ${q[k]}`);
  const filters = [];
  if (q.year_from || q.year_to) {
    filters.push(q.year_from && q.year_to ? `${q.year_from}–${q.year_to}` : q.year_from ? t('ab {y}', { y: q.year_from }) : t('bis {y}', { y: q.year_to }));
  }
  if ((q.item_types || []).length) filters.push(q.item_types.map(itemTypeLabel).join(', '));
  if ((q.libraries || []).length) filters.push(q.libraries.map(x => libNames.get(x) || x).join(', '));
  if ((q.collections || []).length) filters.push(q.collections.map(x => collNames.get(x) || x).join(', '));
  if (q.has_pdf) filters.push(t('mit PDF'));
  if (q.indexed) filters.push(t('indexiert'));
  const head = q.q || terms.shift() || filters.shift() || '…';
  return { head, sub: [...terms, ...filters].join(' · ') };
}

function historyPanel() {
  const s = st();
  const items = s.history || [];
  const libNames = new Map(((s.status && s.status.facets.libraries) || []).map(x => [x.lib, x.name]));
  const collNames = new Map(collectionOptions().map(o => [o.value, o.label.split(' › ').pop()]));
  const labeled = items.map(e => ({ e, ...historyLabel(e.query, libNames, collNames) }));
  const f = s.historyFilter.trim().toLowerCase();
  const shown = f ? labeled.filter(x => `${x.head} ${x.sub}`.toLowerCase().includes(f)) : labeled;
  const p = project();
  return h('aside', { class: 'search-side', ...paneProps('search', 250) },
    h('div', { class: 'search-side-head' },
      h('div', { class: 'eyebrow' }, t('Bisherige Suchen')),
      items.length ? h('span', { class: 'muted small' }, fmtInt(items.length)) : null,
      items.length ? iconBtn('trash', t('Suchverlauf dieses Projekts leeren'), clearHistory) : null),
    items.length > 5 ? textInput({ value: s.historyFilter, placeholder: t('Verlauf filtern …'), label: t('Verlauf filtern'),
      onInput: v => { s.historyFilter = v; update(); } }) : null,
    s.history === null ? h('div', { class: 'pad' }, spinner(14))
      : !items.length ? h('p', { class: 'muted small' }, t('Noch keine Suchen in diesem Projekt. Jede ausgeführte Suche erscheint hier; ein Klick übernimmt sie in die Suchfelder.'))
        : h('div', { class: 'recent-searches' },
          shown.map(x => h('div', { key: x.e.id, class: ['recent-search', s.activeId === x.e.id && 'active'], role: 'button', tabindex: 0,
            title: `${x.head}${x.sub ? '\n' + x.sub : ''}\n${t('Klicken: in die Suchfelder übernehmen')}`,
            onclick: () => applySearch(x.e), onkeydown: e => { if (e.key === 'Enter') applySearch(x.e); } },
          h('div', { class: 'recent-search-text' },
            h('div', { class: 'recent-search-q' }, x.head),
            x.sub ? h('div', { class: 'recent-search-sub' }, x.sub) : null,
            h('div', { class: 'recent-search-meta' }, `${t('{n} Treffer', { n: fmtInt(x.e.total) })} · ${fmtAgo(x.e.used_at)}`)),
          iconBtn('x', t('Aus dem Verlauf entfernen'), e => { e.stopPropagation(); forgetSearch(x.e); }))),
          f && !shown.length ? h('p', { class: 'muted small' }, t('Keine passende Suche.')) : null),
    p ? h('p', { class: 'muted small search-side-hint' }, t('Verlauf des Projekts „{name}“', { name: p.name })) : null,
    splitter('search', { def: 250, max: 480 }));
}

async function loadStatus(force = false) {
  const s = st();
  if (s.statusLoading || (s.status && !force)) return;
  s.statusLoading = true;
  try { s.status = await api.get('/api/library/status'); } catch { /* Dienst */ }
  s.statusLoading = false;
  // Beim ersten Öffnen: Katalog anlegen bzw. auffrischen, wenn Zotero läuft
  const z = state.status && state.status.zotero;
  if (!s.autoSynced && z && z.local_api && s.status && !s.status.job &&
      (!s.status.synced_at || Date.now() / 1000 - s.status.synced_at > 1800)) {
    s.autoSynced = true;
    syncCatalog(true);
  }
  update();
}

async function syncCatalog(quiet = false) {
  const s = st();
  let job;
  try { job = await api.post('/api/library/sync', {}); } catch (err) { if (!quiet) toast(err.message, 'error'); return; }
  state.jobs[job.id] = job;
  if (s.status) s.status.job = job;
  update();
  const done = await watchJob(job.id);
  if (done.status === 'done') { if (!quiet) toast(t('Suchkatalog aktualisiert.'), 'success'); }
  else if (done.status === 'error') toast(done.error, 'error', 8000);
  s.status = null;
  await loadStatus(true);
  if (s.results) doSearch(0);
  loadCorpora();
}

function hasQuery(q) {
  return ['q', 'title', 'creator', 'publication', 'abstract', 'tags', 'doi', 'fulltext'].some(k => (q[k] || '').trim())
    || q.year_from || q.year_to || q.item_types.length || q.libraries.length || q.collections.length || q.has_pdf || q.indexed;
}

async function doSearch(offset = 0) {
  const s = st();
  if (!hasQuery(s.query)) { toast(t('Bitte einen Suchbegriff oder Filter angeben.'), 'warning'); return; }
  s.busy = true; s.error = null; update();
  try {
    const r = await api.post('/api/library/search', { query: { ...s.query, offset, limit: 100 }, project_id: state.projectId });
    s.total = r.total;
    s.fulltextDocs = r.fulltext_documents;
    s.results = offset ? [...(s.results || []), ...r.results] : r.results;
    s.offset = offset;
    // Die Auswahl bleibt: Einträge aus mehreren Suchen lassen sich zusammen kopieren oder exportieren
    if (!offset) { s.fromHistory = null; s.showPicked = false; s.lastIdx = null; }
    if (r.searches) { s.history = r.searches; s.historyFor = state.projectId; }
    if (r.search_id) s.activeId = r.search_id;
  } catch (err) { s.error = err.message; }
  s.busy = false; update();
}

// ------------------------------------------------------------------ In Korpus aufnehmen
async function addToCorpus(corpus, items) {
  const r = await run(() => api.post(`/api/corpora/${corpus.id}/items`, { items: items.map(x => ({ lib: x.lib, key: x.key })) }));
  await loadCorpora();
  for (const x of items) if (!(x.corpora || []).includes(corpus.id)) x.corpora = [...(x.corpora || []), corpus.id];
  const pending = r.stats.pending;
  toast(t('{n} Einträge in „{name}“ aufgenommen.', { n: items.length, name: corpus.name }), 'success', 6000,
    pending ? { label: t('Jetzt indexieren'), onClick: () => navigate('index') } : null);
}

async function removeFromCorpus(corpus, item) {
  await run(() => api.post(`/api/corpora/${corpus.id}/items`, { items: [{ lib: item.lib, key: item.key }], remove: true }));
  item.corpora = (item.corpora || []).filter(id => id !== corpus.id);
  await loadCorpora();
  toast(t('Aus „{name}“ entfernt.', { name: corpus.name }), 'success');
}

function newCorpusFromItems(items) {
  const v = { name: '' };
  openModal({
    title: t('Neuer Korpus aus {n} Einträgen', { n: items.length }),
    body: () => h('div', { class: 'stack' },
      field(t('Name'), textInput({ value: v.name, id: 'new-corpus-name', onInput: x => { v.name = x; } })),
      h('p', { class: 'muted small' }, t('Der Korpus enthält genau diese Einträge und gehört zum aktiven Projekt. Sammlungen lassen sich später unter „Korpora“ ergänzen.'))),
    actions: [{ label: t('Abbrechen'), onClick: closeModal }, { label: t('Anlegen'), kind: 'primary', onClick: async () => {
      if (!v.name.trim()) { toast(t('Bitte einen Namen eingeben.'), 'warning'); return; }
      const c = await run(() => api.post('/api/corpora', { name: v.name.trim(), project_id: state.projectId,
        sources: items.map(x => `${x.lib}:@${x.key}`) }));
      closeModal();
      await Promise.all([loadCorpora(), loadProjects()]);
      for (const x of items) x.corpora = [...(x.corpora || []), c.id];
      toast(t('Korpus „{name}“ angelegt.', { name: c.name }), 'success', 6000, { label: t('Jetzt indexieren'), onClick: () => navigate('index') });
      update();
    } }],
  });
  requestAnimationFrame(() => document.getElementById('new-corpus-name')?.focus());
}

function corpusMenu(e, items) {
  const r = e.currentTarget.getBoundingClientRect();
  const corpora = projectCorpora();
  const single = items.length === 1 ? items[0] : null;
  openMenu(r.left, r.bottom + 4, [
    { heading: t('In Korpus aufnehmen ({project})', { project: (project() || {}).name || '' }) },
    ...corpora.map(c => {
      const inside = single && (single.corpora || []).includes(c.id);
      return { label: c.name, icon: inside ? 'check' : 'corpus', hint: inside ? t('enthalten – entfernen') : '',
        onClick: () => inside ? removeFromCorpus(c, single) : addToCorpus(c, items) };
    }),
    !corpora.length && { label: t('Dieses Projekt hat noch keinen Korpus'), disabled: true },
    '-',
    { label: t('Neuer Korpus aus Auswahl …'), icon: 'plus', onClick: () => newCorpusFromItems(items) },
  ], { width: 300 });
}

function locationsMenu(e, item) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4, [
    { heading: t('In Zotero zeigen in …') },
    ...item.locations.map(loc => ({ label: loc.path, icon: loc.kind === 'library' ? (item.group ? 'users' : 'library') : 'folder',
      onClick: () => api.openExternal(loc.select) })),
  ], { width: 380, scroll: true, maxHeight: 360 });
}

// ------------------------------------------------------------------ Auswahl (bleibt über mehrere Suchen erhalten)
const rid = x => `${x.lib}:${x.key}`;
const itemsOf = list => list.map(x => ({ lib: x.lib, key: x.key }));
const pickedList = () => [...st().picked.values()];

function pick(x, on) {
  const s = st();
  if (on) s.picked.set(rid(x), x); else s.picked.delete(rid(x));
}

// Häkchen einer Zeile; mit Shift alle Treffer zwischen dem zuletzt angeklickten und diesem gleich setzen
function toggleRow(list, i, on, shift) {
  const s = st();
  if (shift && s.lastIdx != null && s.lastIdx < list.length) {
    for (let j = Math.min(s.lastIdx, i); j <= Math.max(s.lastIdx, i); j++) pick(list[j], on);
  } else {
    pick(list[i], on);
  }
  s.lastIdx = i;
  update();
}

function clearPicked() {
  const s = st();
  s.picked = new Map(); s.showPicked = false; s.lastIdx = null;
  update();
}

// Strg+A: alle angezeigten Treffer wählen; Esc: Auswahl aufheben – nur ausserhalb von Eingabefeldern
document.addEventListener('keydown', e => {
  if (state.view !== 'search' || state.modal || state.menu) return;
  const el = e.target;
  if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
  const s = st();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    const list = s.showPicked ? pickedList() : s.results || [];
    if (!list.length) return;
    e.preventDefault();
    list.forEach(x => pick(x, true));
    update();
  } else if (e.key === 'Escape' && s.picked.size) {
    clearPicked();
  }
});

// ------------------------------------------------------------------ Literaturnachweise, Export
const toSettings = () => { ui('settings', {}).tab = 'zotero'; navigate('settings'); };

function citeToast(r, what) {
  const how = r.from_zotero ? '' : ` ${t('(vereinfacht – Zotero nicht erreichbar)')}`;
  toast(`${what} · ${t('Stil: {s}', { s: r.style_title })}${how}`, 'success', 5000, { label: t('Stil ändern'), onClick: toSettings });
}

// Die Zwischenablage kann verweigern (z. B. Fenster ohne Fokus) – dann melden statt still nichts zu tun
const copyFailed = () => toast(t('Kopieren nicht möglich – bitte ins Fenster klicken und erneut versuchen.'), 'error', 6000);

async function copyReferences(items) {
  const r = await run(() => api.post('/api/library/cite', { items: itemsOf(items) }));
  if (!(await copyToClipboard(r.bibliography.text, r.bibliography.html))) { copyFailed(); return; }
  citeToast(r, r.count === 1 ? t('Literaturnachweis kopiert') : t('Literaturliste mit {n} Einträgen kopiert', { n: fmtInt(r.count) }));
}

async function copyShorts(items) {
  const r = await run(() => api.post('/api/library/cite', { items: itemsOf(items) }));
  if (!(await copyToClipboard(r.short))) { copyFailed(); return; }
  citeToast(r, r.count === 1 ? t('Kurzbeleg kopiert') : t('{n} Kurzbelege kopiert', { n: fmtInt(r.count) }));
}

async function copyPlain(text, message) {
  if (await copyToClipboard(text)) toast(message, 'success', 2500); else copyFailed();
}

const EXPORT_FORMATS = () => [
  { format: 'docx', label: t('Word (.docx) – Belege und Literaturverzeichnis als Zotero-Felder') },
  { format: 'bib', label: t('BibTeX (.bib) – für LaTeX') },
  { format: 'ris', label: t('RIS (.ris) – für andere Literaturprogramme') },
  { format: 'md', label: t('Markdown (.md)') },
];

function exportMenu(e, items) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4, [
    { heading: items.length === 1 ? t('1 Eintrag speichern als') : t('{n} Einträge speichern als', { n: fmtInt(items.length) }) },
    ...EXPORT_FORMATS().map(x => ({ label: x.label, icon: 'download', onClick: () => saveSelection(items, x.format) })),
  ], { width: 380 });
}

async function saveSelection(items, format) {
  const r = await run(() => api.post('/api/library/export', { items: itemsOf(items), format }));
  const saved = await run(() => api.saveUrl(r.filename, `/api/library/export/${r.token}`));
  if (saved) toast(typeof saved === 'string' ? t('Gespeichert: {path}', { path: saved }) : t('Gespeichert.'), 'success', 4000);
}

// ------------------------------------------------------------------ Fragen zur Auswahl
// Fragen finden nur in indexierten Texten etwas: Nicht indexierte (mit lesbarer Datei) vorher in die Warteschlange
function askAbout(items) {
  const ready = items.filter(x => x.index_status === 'indexed');
  const pending = items.filter(x => x.index_status === 'pending');
  const open = () => {
    ui('ask', {}).scope = { label: items.length === 1 ? t('1 Eintrag aus der Suche') : t('{n} Einträge aus der Suche', { n: fmtInt(items.length) }),
      filters: { item_keys: items.map(rid) } };
    navigate('ask');
  };
  if (!pending.length) {
    if (ready.length) open();
    else toast(t('Keiner der gewählten Einträge hat einen lesbaren Text – Fragen fänden darin nichts.'), 'warning', 6000);
    return;
  }
  openModal({
    title: t('Nicht alle Einträge sind indexiert'),
    body: h('p', null, t('{a} von {n} Einträgen sind indexiert, {p} noch nicht. Fragen finden nur in indexierten Texten etwas.',
      { a: fmtInt(ready.length), n: fmtInt(items.length), p: fmtInt(pending.length) })),
    actions: [
      { label: t('Abbrechen'), onClick: closeModal },
      ready.length ? { label: t('Nur mit den indexierten fragen'), onClick: () => { closeModal(); open(); } } : null,
      { label: t('Zuerst indexieren'), kind: 'primary', icon: 'play', onClick: async () => {
        closeModal();
        const job = await submitIndexRun('/api/index/run', { sync: true, items: pending.map(rid) });
        if (job === false) return;
        toast(t('Die Einträge werden indexiert – Fragen stellen, sobald der Lauf fertig ist (Statusleiste).'), 'info', 8000);
        open();
      } },
    ].filter(Boolean),
  });
}

// ------------------------------------------------------------------ In eine Zotero-Sammlung ablegen
function collectionDialog(items) {
  const byLib = new Map();
  for (const x of items) byLib.set(x.lib, (byLib.get(x.lib) || 0) + 1);
  const libs = [...byLib.entries()].sort((a, b) => b[1] - a[1]).map(([lib]) => lib);
  const treeLib = lib => ((state.tree && state.tree.libraries) || []).find(l => l.lib === lib) || {};
  const libName = lib => treeLib(lib).name || lib;
  const collections = lib => {
    const out = [];
    const walk = (nodes, path) => {
      for (const n of nodes) { const p = [...path, n.name]; out.push({ value: n.key, label: p.join(' › ') }); walk(n.children || [], p); }
    };
    walk(treeLib(lib).collections || [], []);
    return out;
  };
  const v = { lib: libs[0], mode: 'existing', collection: '', name: '', parent: '', busy: false };
  const submit = async () => {
    if (v.mode === 'existing' && !v.collection) { toast(t('Bitte eine Sammlung wählen.'), 'warning'); return; }
    if (v.mode === 'new' && !v.name.trim()) { toast(t('Bitte einen Namen eingeben.'), 'warning'); return; }
    v.busy = true; update();
    let r;
    try {
      r = await run(() => api.post('/api/library/to-collection', { items: itemsOf(items), lib: v.lib,
        collection: v.mode === 'existing' ? v.collection : '', new_name: v.mode === 'new' ? v.name.trim() : '', parent: v.mode === 'new' ? v.parent : '' }));
    } catch { v.busy = false; update(); return; }
    closeModal();
    const name = v.mode === 'new' ? v.name.trim() : (collections(v.lib).find(c => c.value === v.collection) || {}).label || '';
    const parts = [r.added === 1 ? t('1 Eintrag in „{name}“ abgelegt.', { name }) : t('{n} Einträge in „{name}“ abgelegt.', { n: fmtInt(r.added), name }),
      r.already ? t('{n} waren schon darin.', { n: fmtInt(r.already) }) : null,
      r.skipped ? t('{n} aus anderen Bibliotheken übersprungen.', { n: fmtInt(r.skipped) }) : null];
    toast(parts.filter(Boolean).join(' '), 'success', 8000, { label: t('In Zotero zeigen'), onClick: () => api.openExternal(r.select) });
    if (v.mode === 'new') { state.tree = null; st().treeRequested = false; update(); }  // neue Sammlung im Baum
  };
  const z = state.status && state.status.zotero;
  openModal({
    title: t('In Zotero-Sammlung ablegen'),
    body: () => {
      const list = collections(v.lib);
      const n = byLib.get(v.lib) || 0;
      const other = items.length - n;
      return h('div', { class: 'stack' },
        z && !z.write_access ? notice('warning', t('Dafür braucht Zotivity den Schreibzugriff auf Zotero.'),
          h('div', { class: 'notice-actions' }, btn(t('Zu den Einstellungen'), { size: 'sm', onClick: () => { closeModal(); toSettings(); } }))) : null,
        libs.length > 1 ? field(t('Bibliothek'), select({ value: v.lib, label: t('Bibliothek'),
          options: libs.map(lib => ({ value: lib, label: `${libName(lib)} (${fmtInt(byLib.get(lib))})` })),
          onChange: x => { v.lib = x; v.collection = ''; v.parent = ''; update(); } })) : null,
        segmented({ value: v.mode, onChange: m => { v.mode = m; update(); },
          options: [{ value: 'existing', label: t('Bestehende Sammlung') }, { value: 'new', label: t('Neue Sammlung') }] }),
        v.mode === 'existing'
          ? field(t('Sammlung in {lib}', { lib: libName(v.lib) }), select({ value: v.collection, label: t('Sammlung'),
            options: [{ value: '', label: list.length ? t('Sammlung wählen …') : t('Keine Sammlungen') }, ...list], onChange: x => { v.collection = x; update(); } }))
          : h('div', { class: 'stack-sm' },
            field(t('Name der neuen Sammlung'), textInput({ value: v.name, onInput: x => { v.name = x; } })),
            field(t('Innerhalb von (optional)'), select({ value: v.parent, label: t('Übergeordnete Sammlung'),
              options: [{ value: '', label: t('oberste Ebene von {lib}', { lib: libName(v.lib) }) }, ...list], onChange: x => { v.parent = x; } }))),
        h('p', { class: 'muted small' }, other
          ? t('{n} Einträge kommen in die Sammlung, {o} aus anderen Bibliotheken nicht – eine Zotero-Sammlung gehört zu einer Bibliothek.', { n: fmtInt(n), o: fmtInt(other) })
          : t('{n} Einträge kommen in die Sammlung. Bestehende Zuordnungen in Zotero bleiben erhalten.', { n: fmtInt(n) })));
    },
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal }, { label: t('Ablegen'), kind: 'primary', icon: 'folder', disabled: v.busy, onClick: submit }],
  });
}

// ------------------------------------------------------------------ Menüs
function rowMenu(e, x) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.right - 270, r.bottom + 4, [
    { label: t('Kurzbeleg kopieren'), icon: 'quote', onClick: () => copyShorts([x]) },
    x.doi ? { label: t('DOI-Link kopieren'), icon: 'link', onClick: () => copyPlain(`https://doi.org/${x.doi}`, t('DOI-Link kopiert.')) } : null,
    { label: t('Zotero-Link kopieren'), icon: 'zotero', onClick: () => copyPlain(x.select, t('Zotero-Link kopiert.')) },
    { label: t('Speichern als …'), icon: 'download', onClick: () => exportMenu(e, [x]) },
    '-',
    { label: t('Fragen zu diesem Eintrag'), icon: 'chat', onClick: () => askAbout([x]) },
    { label: t('In Zotero-Sammlung ablegen …'), icon: 'folder', onClick: () => collectionDialog([x]) },
  ].filter(Boolean), { width: 270 });
}

function selectionMenu(e, items) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4, [
    { label: t('In Zotero-Sammlung ablegen …'), icon: 'folder', onClick: () => collectionDialog(items) },
    { label: t('Neuer Korpus aus Auswahl …'), icon: 'plus', onClick: () => newCorpusFromItems(items) },
  ], { width: 280 });
}

// Leiste über den Treffern, sobald etwas ausgewählt ist (bleibt beim Scrollen oben)
function selectionBar() {
  const s = st();
  const sel = pickedList();
  if (!sel.length) return null;
  const current = new Set((s.results || []).map(rid));
  const earlier = sel.filter(x => !current.has(rid(x))).length;
  return h('div', { class: 'selection-bar' },
    h('div', { class: 'selection-count' },
      h('b', null, sel.length === 1 ? t('1 ausgewählt') : t('{n} ausgewählt', { n: fmtInt(sel.length) })),
      earlier ? h('span', { class: 'muted small' }, ` ${t('(davon {n} aus früheren Suchen)', { n: fmtInt(earlier) })}`) : null),
    h('div', { class: 'selection-actions' },
      btn(sel.length === 1 ? t('Literaturnachweis kopieren') : t('Literaturliste kopieren'), { size: 'sm', kind: 'primary', icon: 'quote', onClick: () => copyReferences(sel) }),
      btn(t('Kurzbelege kopieren'), { size: 'sm', icon: 'copy', onClick: () => copyShorts(sel) }),
      btn(t('Exportieren'), { size: 'sm', icon: 'download', onClick: e => exportMenu(e, sel) }),
      btn(t('In Korpus'), { size: 'sm', icon: 'corpus', onClick: e => corpusMenu(e, sel) }),
      btn(t('Fragen stellen'), { size: 'sm', icon: 'chat', onClick: () => askAbout(sel) }),
      iconBtn('more', t('Weitere Aktionen'), e => selectionMenu(e, sel))),
    h('div', { class: 'selection-right' },
      btn(s.showPicked ? t('Alle Treffer zeigen') : t('Nur Auswahl zeigen'), { size: 'sm', kind: 'ghost', icon: s.showPicked ? 'search' : 'filter',
        onClick: () => { s.showPicked = !s.showPicked; s.lastIdx = null; update(); } }),
      btn(t('Aufheben'), { size: 'sm', kind: 'ghost', icon: 'x', title: t('Auswahl aufheben (Esc)'), onClick: clearPicked })));
}

// ------------------------------------------------------------------ Darstellung
function catalogBar() {
  const s = st();
  const c = s.status;
  // Laufender Abgleich: aktueller Stand aus der Beobachtung (state.jobs), nicht der Schnappschuss beim Öffnen
  const snap = c && c.job && ['queued', 'running'].includes(c.job.status) ? c.job : null;
  const live = snap && state.jobs[snap.id];
  if (live && !['queued', 'running'].includes(live.status)) {
    // Abgleich (auch von anderswo gestartet) ist fertig: Stand des Katalogs neu laden
    c.job = null;
    setTimeout(() => loadStatus(true), 0);
  }
  const job = runningJob('catalog') || (live && ['queued', 'running'].includes(live.status) ? live : null) || (live ? null : snap);
  // Stand aus der laufend abgefragten Statusmeldung: Der Dienst vergleicht jede Minute die Versionsnummern mit
  // Zotero und gleicht Änderungen selbst ab – danach den Katalog (Zahlen, Filter) hier neu laden
  const cat = state.status && state.status.catalog;
  if (!job && c && cat && cat.synced_at && (!c.synced_at || cat.synced_at > c.synced_at + 1)) setTimeout(() => loadStatus(true), 0);
  const changed = !job && c && c.synced_at && cat && cat.zotero_changed;
  const libs = c ? c.facets.libraries : [];
  const items = libs.reduce((a, l) => a + l.items, 0);
  return h('div', { class: ['catalog-bar', changed && 'catalog-changed'] },
    icon('library', 15),
    job ? h('span', { class: 'row nowrap catalog-progress' }, spinner(12),
      h('span', null, t('Suchkatalog wird abgeglichen: {msg}', { msg: job.message || job.phase || '…' })),
      job.total ? h('span', { class: 'muted' }, t('Bibliothek {a} von {b}', { a: Math.min(job.done + 1, job.total), b: job.total })) : null)
      : c && c.synced_at ? h('span', null, t(libs.length === 1 ? '{items} Einträge in 1 Bibliothek · Stand {ago}' : '{items} Einträge in {libs} Bibliotheken · Stand {ago}', { items: fmtInt(items), libs: libs.length, ago: fmtAgo(c.synced_at) }),
        changed ? h('span', { class: 'warn-text' }, ' · ', icon('alert', 13), ' ', runningJob('index')
          ? t('Zotero wurde seither geändert – der Abgleich folgt nach der Indexierung.')
          : t('Zotero wurde seither geändert – der Abgleich folgt gleich.')) : null)
        : h('span', { class: 'muted' }, t('Suchkatalog noch nicht angelegt.')),
    h('span', { class: 'spacer' }),
    btn(c && c.synced_at ? (changed ? t('Jetzt abgleichen') : t('Katalog aktualisieren')) : t('Suchkatalog anlegen'),
      { size: 'sm', kind: !(c && c.synced_at) || changed ? 'primary' : 'ghost', icon: 'refresh',
        disabled: !!job, why: t('Abgleich läuft bereits.'), onClick: () => syncCatalog(false) }));
}

function collectionOptions() {
  const out = [];
  const walk = (lib, libName, nodes, path) => {
    for (const n of nodes) {
      const p = [...path, n.name];
      out.push({ value: n.id, label: `${libName} › ${p.join(' › ')}` });
      walk(lib, libName, n.children || [], p);
    }
  };
  for (const l of (state.tree && state.tree.libraries) || []) {
    out.push({ value: l.id, label: `${l.name} (${t('ganze Bibliothek')})` });
    walk(l.lib, l.name, l.collections, []);
  }
  return out;
}

function searchForm() {
  const s = st();
  const q = s.query;
  const c = s.status;
  const facets = c ? c.facets : { libraries: [], item_types: [], years: [null, null] };
  const set = (k, v) => { q[k] = v; };
  const onEnter = e => { if (e.key === 'Enter') { set(e.target.dataset.k, e.target.value); doSearch(0); } };
  const input = (k, ph) => textInput({ value: q[k], placeholder: ph, onInput: v => set(k, v), onKeyDown: onEnter, ref: el => { el.dataset.k = k; } });
  const collOpts = collectionOptions();
  return h('div', { class: 'search-form card' },
    h('div', { class: 'search-main' },
      h('div', { class: 'search-input' }, icon('search', 18),
        h('input', { class: 'input input-lg', id: 'search-q', value: q.q, placeholder: t('Titel, Autor/in, Jahr, Schlagwort, Abstract, DOI …'), 'aria-label': t('Suchbegriff'),
          oninput: e => set('q', e.target.value), onkeydown: e => { if (e.key === 'Enter') { set('q', e.target.value); doSearch(0); } } })),
      btn(t('Suchen'), { kind: 'primary', icon: 'search', busy: s.busy, onClick: () => doSearch(0) }),
      btn(s.advanced ? t('Einfache Suche') : t('Erweiterte Suche'), { kind: 'ghost', icon: 'sliders', onClick: () => { s.advanced = !s.advanced; update(); } })),
    h('div', { class: 'search-hint muted small' }, t('Wörter werden UND-verknüpft und als Wortanfang gesucht (digit → digital). "genaue Phrase", -ausschliessen, ODER für Alternativen.')),
    s.advanced && h('div', { class: 'search-advanced' },
      h('div', { class: 'adv-grid' },
        field(t('Titel'), input('title', '')),
        field(t('Autor/in, Herausgeber/in'), input('creator', '')),
        field(t('Publikation / Zeitschrift / Verlag'), input('publication', '')),
        field(t('Schlagwörter'), input('tags', '')),
        field(t('Abstract'), input('abstract', '')),
        field(t('DOI'), input('doi', '')),
        field(t('Volltext (indexierte Texte)'), input('fulltext', ''), { help: t('Sucht im Text der indexierten PDFs und zeigt die Fundstelle.') }),
        field(t('Jahr'), h('div', { class: 'row nowrap' },
          numberInput({ value: q.year_from, min: 1000, max: 2100, int: true, nullable: true, placeholder: facets.years[0] ? String(facets.years[0]) : t('von'), onChange: v => { q.year_from = v; update(); } }),
          h('span', { class: 'muted' }, '–'),
          numberInput({ value: q.year_to, min: 1000, max: 2100, int: true, nullable: true, placeholder: facets.years[1] ? String(facets.years[1]) : t('bis'), onChange: v => { q.year_to = v; update(); } }))),
        field(t('Eintragsart'), multiSelect({ values: q.item_types, placeholder: t('alle'), label: t('Eintragsart'), onChange: v => { q.item_types = v; update(); },
          options: facets.item_types.map(x => ({ value: x.type, label: itemTypeLabel(x.type), hint: fmtInt(x.items) })) })),
        field(t('Bibliotheken'), multiSelect({ values: q.libraries, placeholder: t('alle (eigene und Gruppen)'), label: t('Bibliotheken'), onChange: v => { q.libraries = v; update(); },
          options: facets.libraries.map(x => ({ value: x.lib, label: x.name, hint: fmtInt(x.items) })) })),
        field(t('In Sammlung (inkl. Untersammlungen)'), h('div', { class: 'stack-sm' },
          combo({ value: '', options: collOpts.map(o => o.label), openOnFocus: true, clearOnSelect: true, placeholder: collOpts.length ? t('Sammlung wählen …') : t('Sammlungen werden geladen …'),
            label: t('Sammlung'), onChange: label => { const o = collOpts.find(x => x.label === label); if (o && !q.collections.includes(o.value)) { q.collections = [...q.collections, o.value]; update(); } } }),
          q.collections.length ? h('div', { class: 'chips' }, q.collections.map(id => h('span', { key: id, class: 'chip chip-accent' },
            h('span', null, (collOpts.find(o => o.value === id) || { label: id }).label),
            h('button', { class: 'chip-x', title: t('Entfernen'), onclick: () => { q.collections = q.collections.filter(x => x !== id); update(); } }, icon('x', 11))))) : null))),
      h('div', { class: 'row wrap' },
        checkbox({ checked: q.has_pdf, label: t('nur mit PDF'), onChange: v => { q.has_pdf = v; update(); } }),
        checkbox({ checked: q.indexed, label: t('nur indexierte Texte'), onChange: v => { q.indexed = v; update(); } }),
        h('span', { class: 'spacer' }),
        btn(t('Felder leeren'), { size: 'sm', kind: 'ghost', icon: 'x', onClick: () => { s.query = { ...EMPTY_QUERY }; s.results = null; s.activeId = null; s.fromHistory = null; update(); } }))));
}

const STATUS = {
  indexed: () => [t('indexiert'), 'success'], pending: () => [t('noch nicht indexiert'), 'warning'],
  problem: () => [t('ohne Text / Fehler'), 'danger'], none: () => [t('ohne PDF'), 'neutral'],
};

function snippetHtml(snip) {
  return esc(snip).replace(/\u0001/g, '<mark>').replace(/\u0002/g, '</mark>');
}

function resultRow(x, i, list) {
  const s = st();
  const id = rid(x);
  const [label, kind] = STATUS[x.index_status]();
  const corpora = projectCorpora();
  const inCorpora = (x.corpora || []).map(cid => corpora.find(c => c.id === cid)).filter(Boolean);
  const on = s.picked.has(id);
  return h('div', { key: id, class: ['result', on && 'selected'] },
    // Eigenes Häkchen statt checkbox(): der Klick braucht die Shift-Taste (Bereich auswählen)
    h('label', { class: 'checkbox', title: t('Auswählen (Shift+Klick: Bereich, Strg+A: alle)'), onclick: e => e.stopPropagation() },
      h('input', { type: 'checkbox', checked: on, onclick: e => toggleRow(list, i, e.target.checked, e.shiftKey) }),
      h('span', { class: 'checkbox-box' }, icon('check', 12))),
    h('div', { class: 'result-body' },
      h('div', { class: 'result-title' }, h('a', { href: x.select, title: t('In Zotero zeigen') }, x.title || t('(ohne Titel)'))),
      h('div', { class: 'result-meta' }, [x.creators, x.year, itemTypeLabel(x.item_type), x.publication].filter(Boolean).join(' · ')),
      x.snippet && h('div', { class: 'result-snippet', html: snippetHtml(x.snippet) }),
      h('div', { class: 'result-locations' },
        x.locations.map((loc, i) => h('button', { key: i, type: 'button', class: ['loc', loc.kind === 'library' && 'loc-lib', x.group && 'loc-group'],
          title: t('In Zotero zeigen: {path}', { path: loc.path }), onclick: () => api.openExternal(loc.select) },
        icon(loc.kind === 'library' ? (x.group ? 'users' : 'library') : 'folder', 12), h('span', null, loc.kind === 'library' ? loc.label : loc.path.split(' › ').slice(1).join(' › ')))))),
    h('div', { class: 'result-side' },
      badge(label, kind),
      inCorpora.length ? h('div', { class: 'result-corpora' }, inCorpora.map(c => h('span', { key: c.id, class: 'chip chip-accent', title: t('Im Korpus „{name}“', { name: c.name }) },
        icon('corpus', 11), h('span', null, c.name)))) : null,
      h('div', { class: 'row nowrap' },
        x.locations.length > 1 ? btn(t('In Zotero zeigen'), { size: 'sm', kind: 'ghost', icon: 'zotero', onClick: e => locationsMenu(e, x) })
          : btn(t('In Zotero zeigen'), { size: 'sm', kind: 'ghost', icon: 'zotero', onClick: () => api.openExternal(x.select) }),
        x.pdf && iconBtn('pdf', t('PDF in Zotero öffnen'), () => api.openExternal(x.pdf)),
        iconBtn('quote', t('Literaturnachweis kopieren (im Zitierstil der Einstellungen)'), () => copyReferences([x])),
        iconBtn('corpus', t('In Korpus aufnehmen …'), e => corpusMenu(e, [x])),
        iconBtn('more', t('Weitere Aktionen'), e => rowMenu(e, x)))));
}

function resultsList() {
  const s = st();
  if (s.error) return h('div', { class: 'stack' }, selectionBar(), notice('error', s.error));
  if (s.results === null && !s.showPicked) {
    // Noch keine Treffer (z. B. Suche aus dem Verlauf übernommen): eine bestehende Auswahl bleibt bedienbar
    const e = s.fromHistory;
    return h('div', { class: 'stack' }, selectionBar(), e
      ? emptyState('history', t('Suche aus dem Verlauf übernommen'),
        t('Felder nach Bedarf anpassen und mit „Suchen“ oder Enter ausführen. Zuletzt: {n} Treffer, {ago}.', { n: fmtInt(e.total), ago: fmtAgo(e.used_at) }),
        btn(t('Suchen'), { kind: 'primary', icon: 'search', busy: s.busy, onClick: () => doSearch(0) }))
      : emptyState('search', t('Zotero-Bibliothek durchsuchen'),
        t('Durchsucht werden die eigene Bibliothek und alle Gruppen – Titel, Personen, Jahr, Publikation, Schlagwörter, Abstract und DOI, auf Wunsch auch der Volltext der indexierten Texte. Ohne Sprachmodell, daher schnell und kostenlos.')));
  }
  const all = s.results || [];
  // „Nur Auswahl zeigen“: die gewählten Einträge (auch aus früheren Suchen) statt der Treffer
  const list = s.showPicked ? pickedList() : all;
  const on = list.filter(x => s.picked.has(rid(x))).length;
  return h('div', { class: 'stack' },
    selectionBar(),
    h('div', { class: 'results-head' },
      checkbox({ checked: on > 0 && on === list.length, indeterminate: on > 0 && on < list.length, title: t('Alle angezeigten auswählen (Strg+A)'),
        onChange: v => { list.forEach(x => pick(x, v)); s.lastIdx = null; update(); } }),
      s.showPicked ? h('b', null, t('Auswahl: {n} Einträge', { n: fmtInt(list.length) })) : h('b', null, t('{n} Treffer', { n: fmtInt(s.total) })),
      !s.showPicked && s.fulltextDocs != null ? h('span', { class: 'muted small' }, t('Volltext in {n} Texten gefunden', { n: fmtInt(s.fulltextDocs) })) : null,
      h('span', { class: 'spacer' }),
      s.showPicked ? null : h('div', { class: 'sort-select' }, select({ value: s.query.sort, label: t('Sortierung'), onChange: v => { s.query.sort = v; doSearch(0); }, options: [
        { value: 'relevance', label: t('Relevanz') }, { value: 'year_desc', label: t('Jahr, neueste zuerst') }, { value: 'year_asc', label: t('Jahr, älteste zuerst') },
        { value: 'title', label: t('Titel') }, { value: 'creator', label: t('Autor/in') }] }))),
    list.length ? h('div', { class: 'results' }, list.map((x, i) => resultRow(x, i, list)))
      : h('p', { class: 'muted pad' }, s.showPicked ? t('Nichts ausgewählt.') : t('Keine Treffer. Andere Begriffe, weniger Filter oder „ODER“ versuchen.')),
    !s.showPicked && all.length < s.total ? h('div', { class: 'row center' }, btn(t('Weitere {n} laden', { n: Math.min(100, s.total - all.length) }), { icon: 'chevronDown', busy: s.busy, onClick: () => doSearch(all.length) })) : null);
}

export function searchView() {
  const s = st();
  if (!s.status) loadStatus();
  if (!state.tree && !s.treeRequested) { s.treeRequested = true; api.get('/api/zotero/tree').then(tr => { state.tree = tr; update(); }).catch(() => {}); }
  // Anderes Projekt geöffnet: dessen Suchverlauf laden, Felder und Treffer des vorigen Projekts verwerfen
  if (s.historyFor !== state.projectId && !s.historyBusy) {
    if (s.historyFor != null) {
      Object.assign(s, { query: { ...EMPTY_QUERY }, results: null, total: 0, picked: new Map(), showPicked: false, lastIdx: null,
        activeId: null, fromHistory: null, historyFilter: '', history: null, advanced: false });
    }
    loadHistory();
  }
  const z = state.status && state.status.zotero;
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Suchen'), t('Zotero-Bibliothek und Gruppen durchsuchen – ohne Sprachmodell')),
    h('div', { class: 'search-layout' },
      historyPanel(),
      h('div', { class: 'search-main-col' }, h('div', { class: 'search-page stack' },
        catalogBar(),
        s.status && !s.status.synced_at && !(z && z.local_api) ? notice('info', t('Für den Suchkatalog muss Zotero einmal geöffnet sein. Danach funktioniert die Suche auch ohne Zotero.')) : null,
        searchForm(),
        resultsList()))));
}
