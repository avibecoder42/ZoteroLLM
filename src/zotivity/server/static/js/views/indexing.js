// Indexierung: genauer Fortschritt (Dokument, Abschnitte, Restzeit), Etappen, Schutzfunktionen, Sicherung.
// Rechts: die Texte des gewählten Korpus (indexiert, offen, Probleme), anklickbar nach Zotero.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, saveSettings, loadCorpora, loadSetup, loadStatus, watchJob, runningJob, submitIndexRun,
  moveQueued, removeQueued } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, card, notice, spinner, progress, progressRing, toggle, numberInput, field, badge, emptyState, select, paneProps, splitter } from '../ui/components.js';
import { fmtInt, fmtNum, fmtDuration, fmtBytes, fmtDate, fmtAgo, plural, nTexts, nIndexed, embedHint, refreshHint, openHint } from '../core/util.js';
import { navigate, viewHeader } from './shell.js';
import { indexCorpus } from './corpora.js';
import { startEmbedding } from './embedmodels.js';
import { duplicatesCard, resetDuplicates } from './duplicates.js';

const watched = new Set();
const INDEX_PANE = 'clamp(320px, 24vw, 560px)';  // passt sich dem Fenster an, bis man die Leiste zieht

function st() {
  return ui('index', { errors: null, loadedJobs: false, corpus: null, corpusFor: null, docs: null, docsFor: null, docsFilter: '', backups: undefined,
    overview: undefined, overviewAt: 0, runs: undefined, selectedRun: null, runDetail: null, runDocsFilter: 'all', runDocsOpen: false,
    liveSig: null, liveAt: 0 });
}

// Nach dem Lauf: Übersicht, Verlauf, Korpora und rechte Spalte neu laden (die Meldung zeigt store.js für alle Ansichten)
function follow(job) {
  if (!job || watched.has(job.id) || !['queued', 'running'].includes(job.status)) return;
  watched.add(job.id);
  watchJob(job.id).then(j => {
    watched.delete(j.id);
    const s = st();
    loadSetup();
    Object.assign(s, { errors: null, backups: undefined, runs: undefined, selectedRun: null, runDetail: null, runDocsOpen: false });
    resetDuplicates();  // ein Lauf kann neue Dubletten nach der Regel vermerkt haben
    refreshDocs(); loadOverview(true);
    update();
  });
}

// Zustand und Tabelle der Korpora immer zusammen laden – sonst zeigt die Tabelle nach einem Abgleich im Hintergrund
// noch alte Zahlen, während oben schon die neuen stehen
function loadOverview(force = false) {
  const s = st();
  if (!force && (s.overview === null || Date.now() - s.overviewAt < 15000)) return;
  if (s.overview === undefined) s.overview = null;
  s.overviewAt = Date.now();
  api.get('/api/index/overview').then(o => { s.overview = o; update(); }).catch(() => {});
  loadCorpora();
}

function loadRuns() {
  const s = st();
  if (s.runs !== undefined) return;
  s.runs = null;
  api.get('/api/index/runs').then(r => { s.runs = r.runs; update(); }).catch(() => { s.runs = []; });
}

// Texte des Korpus rechts neu laden, ohne die Liste zwischendurch zu leeren
function refreshDocs() {
  const s = st();
  const id = s.docsFor;
  if (id == null) return;
  api.get(`/api/corpora/${id}/documents`).then(d => { if (st().docsFor === id) { st().docs = d; update(); } }).catch(() => {});
}

// Während der Indexierung: rechte Spalte, Korpora und Übersicht laufend nachführen (höchstens alle 4 Sekunden)
function liveRefresh(running) {
  if (!running) return;
  const s = st();
  const c = running.counters || {};
  const sig = `${running.id}:${c.docs_done || 0}:${c.chunks_embedded || 0}`;
  if (sig === s.liveSig || Date.now() - s.liveAt < 4000) return;
  s.liveSig = sig;
  s.liveAt = Date.now();
  // Statusleiste im selben Takt wie die Übersicht – beide zeigen dieselbe Zählung
  refreshDocs(); loadOverview(true); loadStatus();
}

// Läuft schon eine Indexierung, wartet der neue Lauf in der Warteschlange (Hinweis kommt aus store.js)
async function startAll(body = {}) {
  if (!state.corpora.length) { toast(t('Lege zuerst einen Wissenskorpus an.'), 'warning'); navigate('corpora'); return; }
  const job = await submitIndexRun('/api/index/run', { sync: true, ...body });
  if (job) follow(job);
}

function lastIndexJob() {
  return Object.values(state.jobs).filter(j => j.kind === 'index').sort((a, b) => b.id - a.id)[0] || null;
}

const STATUS_ICON = { indexed: ['check', 'ok'], embedded: ['check', 'ok'], no_text: ['alert', 'warn'], error: ['x', 'err'] };
const statusText = s => ({ indexed: t('indexiert'), embedded: t('eingebettet'), no_text: t('ohne Text'), error: t('Fehler') }[s] || s);

// Restzeit: „noch ca. 5 min“ bzw. „noch mindestens 5 min“, solange ein Teil (z. B. Lesen) noch nicht abschätzbar ist
export function etaText(c) {
  if (c.eta == null) return null;
  if (!c.eta) return null;
  return c.eta_partial ? t('noch mindestens {d}', { d: fmtDuration(c.eta) }) : t('noch ca. {d}', { d: fmtDuration(c.eta) });
}

// Anteil 0–1 eines Indexierlaufs (der laufende Text zählt anteilig)
export function jobFraction(job) {
  const c = (job && job.counters) || {};
  if (c.fraction != null) return c.fraction;
  return c.docs_total ? (c.docs_done || 0) / c.docs_total : null;
}

function jobPanel(job) {
  const c = job.counters || {};
  const running = ['queued', 'running'].includes(job.status);
  const cur = c.current;
  const total = c.docs_total || 0;
  const done = c.docs_done || 0;
  const frac = jobFraction(job);
  // Dieselbe Zählung wie die Karte „Zustand des Index“ und die Statusleiste
  const cov = (st().overview && st().overview.stats) || (state.status && state.status.index.coverage);
  const head = h('div', { class: 'job-head' },
    running ? progressRing(frac, 20, frac != null ? `${Math.round(frac * 100)} %` : null)
      : icon(job.status === 'done' ? 'check' : 'alert', 16, job.status === 'done' ? 'ok-text' : 'danger-text'),
    h('div', { class: 'grow' }, h('div', { class: 'job-title' }, job.title),
      h('div', { class: 'muted small' }, [job.phase, c.model ? t('Modell {m}', { m: c.model }) : null,
        `${running ? t('seit') : t('Dauer')} ${fmtDuration(job.elapsed)}`].filter(Boolean).join(' · '))),
    running && frac != null && h('b', { class: 'job-pct' }, `${Math.round(frac * 100)} %`),
    running && btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', icon: 'stop', onClick: () => api.post(`/api/jobs/${job.id}/cancel`) }));

  // Zwei Zählungen, klar benannt: „in diesem Lauf“ (diese Indexierung) und „insgesamt durchsuchbar“
  // (mit dem aktiven Embedding-Modell, über alle Korpora – wie in der Statusleiste; enthält früher Eingebettetes)
  const counts = h('div', { class: 'muted small' }, [
    t('{n} Abschnitte in diesem Lauf eingebettet', { n: fmtInt(c.chunks_embedded || 0) }),
    cov ? t('{a} von {b} Abschnitten aller Korpora durchsuchbar', { a: fmtInt(cov.embedded), b: fmtInt(cov.chunks) }) : null,
    c.embed_rate ? t('{r} Abschnitte/s', { r: fmtNum(c.embed_rate, 2) }) : null,
  ].filter(Boolean).join(' · '));

  const eta = etaText(c);
  const overall = total ? h('div', { class: 'job-overall' },
    h('div', { class: 'job-line' }, h('b', null, t('Text {a} von {b}', { a: Math.min(done + (cur && cur.index ? 1 : 0), total), b: fmtInt(total) })),
      c.to_embed && c.to_read ? h('span', { class: 'muted small' }, ` · ${t('{r} zu lesen, {e} nur einzubetten', { r: fmtInt(c.to_read), e: fmtInt(c.to_embed) })}`) : null,
      h('span', { class: 'spacer' }),
      eta ? h('span', { class: 'muted' }, eta) : running ? h('span', { class: 'muted small' }, t('Restzeit wird berechnet …')) : null),
    progress(Math.round((frac ?? done / total) * 1000), 1000), counts) : (c.chunks_embedded ? counts : null);

  const current = cur ? h('div', { class: 'job-current' },
    h('div', { class: 'job-current-label' }, !cur.index ? t('Abschluss') : cur.kind === 'embed' ? t('Wird eingebettet') : t('Aktueller Text')),
    h('div', { class: 'job-current-title' }, cur.title),
    cur.citation && h('div', { class: 'muted small' }, cur.citation),
    h('div', { class: 'job-line' },
      h('span', null, t(cur.step)),
      cur.pages ? h('span', { class: 'muted' }, ` · ${plural(cur.pages, t('Seite'), t('Seiten'))}`) : null,
      h('span', { class: 'spacer' }),
      cur.eta ? h('span', { class: 'muted small' }, t('dieser Text noch ca. {d}', { d: fmtDuration(cur.eta) })) : null,
      cur.chunks_total ? h('b', null, ` ${cur.percent} %`) : null),
    cur.chunks_total ? progress(cur.chunks_done, cur.chunks_total, t('{a} von {b} Abschnitten dieses Texts', { a: fmtInt(cur.chunks_done), b: fmtInt(cur.chunks_total) }))
      : h('div', { class: 'progress' }, h('div', { class: 'progress-bar' }, h('div', { class: 'progress-fill', 'data-indeterminate': 'true', style: { width: '30%' } })))) : null;

  const queue = c.queue && c.queue.length ? h('div', { class: 'job-list' }, h('div', { class: 'job-list-label' }, t('Nächste Texte dieses Laufs')),
    c.queue.map((x, i) => h('div', { key: i, class: 'job-list-item muted' }, icon('file', 13), h('span', null, x)))) : null;

  const recent = c.recent && c.recent.length ? h('div', { class: 'job-list' }, h('div', { class: 'job-list-label' }, t('Zuletzt verarbeitet')),
    c.recent.map((r, i) => {
      const [ic, cls] = STATUS_ICON[r.status] || ['dot', ''];
      return h('div', { key: i, class: 'job-list-item', title: r.message || '' },
        icon(ic, 14, `${cls}-text`), h('span', { class: 'grow' }, r.title),
        h('span', { class: 'muted small nowrap' }, ['indexed', 'embedded'].includes(r.status)
          ? `${r.status === 'embedded' ? t('eingebettet') + ' · ' : ''}${r.pages ? `${r.pages} ${t('S.')} · ` : ''}${fmtInt(r.chunks)} ${t('Abschn.')} · ${fmtDuration(r.seconds)}`
          : `${statusText(r.status)}${r.message ? ': ' + r.message : ''}`));
    })) : null;

  return h('div', { class: 'job-panel' }, head,
    job.status === 'error' && notice('error', job.error),
    overall, current,
    h('div', { class: 'job-lists' }, queue, recent),
    job.log && job.log.length ? h('details', { class: 'job-log' }, h('summary', null, t('Protokoll')), h('pre', null, job.log.join('\n'))) : null);
}

// Kleiner Zusatz bei „indexiert“: davon zu aktualisieren (wartet auf erneutes Lesen, bleibt durchsuchbar)
function refreshMark(n) {
  if (!n) return null;
  return h('span', { class: 'refresh-mark', title: `${t('davon {n} zu aktualisieren', { n: fmtInt(n) })}. ${refreshHint()}` },
    icon('refresh', 11), fmtInt(n));
}

function corporaTable() {
  const s = st();
  if (!state.corpora.length) {
    return notice('info', t('Noch kein Wissenskorpus – ohne Korpus wird nichts indexiert.'),
      h('div', { class: 'notice-actions' }, btn(t('Korpus anlegen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => navigate('corpora') })));
  }
  const model = state.status && state.status.embedding.label;
  const anyToEmbed = state.corpora.some(c => c.stats.to_embed);
  // Spalten ergeben zusammen die Texte: indexiert + einzubetten + offen + Probleme. „Zu aktualisieren“ ist ein Teil von
  // „indexiert“ und steht deshalb als Zusatz bei dieser Zahl, nicht als eigene Spalte.
  // Zwei Gruppen: die Korpora des aktiven Projekts oben, darunter die übrigen mit ihrem Projekt (bzw. „in keinem
  // Projekt“). Gehören alle zum Projekt, braucht es keine Überschriften.
  const own = state.corpora.filter(c => (c.project_ids || []).includes(state.projectId));
  const others = state.corpora.filter(c => !(c.project_ids || []).includes(state.projectId));
  const cols = anyToEmbed ? 7 : 6;
  const p = state.projects.find(x => x.id === state.projectId);
  const projectNames = c => (c.project_ids || []).map(id => (state.projects.find(x => x.id === id) || {}).name).filter(Boolean).join(', ');
  const group = (label, key) => h('tr', { key, class: 'group-row' }, h('td', { colspan: cols }, label));
  const row = (c, other) => h('tr', { key: c.id, class: s.corpus === c.id ? 'selected' : null, title: t('Texte dieses Korpus rechts anzeigen'),
    onclick: () => { s.corpus = c.id; update(); } },
  h('td', null, h('b', null, c.name),
    other ? h('div', { class: 'muted small' }, projectNames(c) ? t('in {names}', { names: projectNames(c) }) : t('in keinem Projekt')) : null,
    !c.synced && h('div', { class: 'muted small' }, t('noch nicht abgeglichen'))),
  h('td', { class: 'num' }, fmtInt(c.stats.documents)),
  h('td', { class: 'num' }, fmtInt(nIndexed(c.stats)), refreshMark(c.stats.refresh)),
  anyToEmbed && h('td', { class: 'num' }, c.stats.to_embed ? badge(fmtInt(c.stats.to_embed), 'info') : '0'),
  h('td', { class: 'num' }, c.stats.pending ? badge(fmtInt(c.stats.pending), 'warning') : '0'),
  h('td', { class: 'num' }, c.stats.no_text + c.stats.error ? badge(fmtInt(c.stats.no_text + c.stats.error), 'danger') : '0'),
  h('td', { class: 'num', onclick: e => e.stopPropagation() },
    c.stats.to_embed && !c.stats.pending
      ? btn(t('Einbetten'), { size: 'sm', kind: 'ghost', icon: 'play', title: queueHint(t('Texte dieses Korpus für {m} einbetten', { m: model || '' })), onClick: () => startEmbedding(c.id) })
      : btn(t('Indexieren'), { size: 'sm', kind: 'ghost', icon: 'play', title: queueHint(null), onClick: () => indexCorpus(c) })));
  const body = others.length ? [
    group(p ? t('Dieses Projekt: {name}', { name: p.name }) : t('Dieses Projekt'), 'g-own'),
    own.length ? own.map(c => row(c, false)) : h('tr', { key: 'none', class: 'group-empty' }, h('td', { colspan: cols, class: 'muted small' }, t('Noch kein Korpus in diesem Projekt.'))),
    group(t('Andere Korpora'), 'g-other'),
    others.map(c => row(c, true)),
  ] : own.map(c => row(c, false));
  // Ab zehn Korpora scrollt die Liste in sich (der Kopf bleibt stehen), statt die Karte zu verlängern
  return h('div', { class: ['table-wrap', 'corpora-scroll', state.corpora.length > 10 && 'is-long'] }, h('table', { class: 'grid clickable' },
    h('thead', null, h('tr', null, h('th', null, t('Wissenskorpus')), h('th', { class: 'num' }, t('Texte')),
      h('th', { class: 'num', title: model ? t('mit {m} durchsuchbar', { m: model }) : null }, t('indexiert')),
      anyToEmbed && h('th', { class: 'num', title: `${t('Text gelesen, für {m} noch nicht eingebettet', { m: model || '' })}. ${embedHint()}` }, t('einzubetten')),
      h('th', { class: 'num', title: openHint(model || '') }, t('offen')), h('th', { class: 'num' }, t('Probleme')), h('th', { class: 'num' }))),
    h('tbody', null, body)));
}

// Während eines Laufs starten die Knöpfe nichts sofort, sondern reihen ein – das steht im Tooltip
function queueHint(title) {
  if (!runningJob('index')) return title || undefined;
  return [title, t('Läuft schon eine Indexierung, kommt dieser Lauf in die Warteschlange.')].filter(Boolean).join('\n');
}

// ------------------------------------------------------------------ Rechtes Panel: Texte des Korpus
function docList(title, entries, kind, open, extra = null) {
  const s = st();
  const f = s.docsFilter.trim().toLowerCase();
  const shown = f ? entries.filter(e => `${e.title} ${e.creators} ${e.year || ''}`.toLowerCase().includes(f)) : entries;
  const badgeKind = { indexed: 'success', pending: 'warning', to_embed: 'info', refresh: 'neutral', current: 'accent' }[kind] || 'danger';
  return h('details', { class: ['doc-group', `doc-group-${kind}`], open },
    h('summary', { title: kind === 'refresh' ? refreshHint() : kind === 'to_embed' ? embedHint() : kind === 'pending' ? openHint((s.docs && s.docs.model) || '') : null },
      h('span', { class: 'doc-group-title' }, title), badge(fmtInt(entries.length), badgeKind)),
    shown.length ? h('div', { class: 'doc-items' }, shown.slice(0, 500).map(e => h('div', { key: e.att_key, class: 'doc-item' },
      h('a', { href: e.select, class: 'doc-item-main', title: t('In Zotero zeigen') },
        h('span', { class: 'doc-item-title' }, kind === 'current' && extra ? [progressRing(extra.fraction, 13), ' ', e.title] : e.title),
        h('span', { class: 'doc-item-sub' }, [e.creators, e.year].filter(Boolean).join(' · ') || e.citation,
          ['indexed', 'refresh'].includes(kind) && e.pages ? ` · ${e.pages} ${t('S.')} · ${fmtInt(e.chunks || 0)} ${t('Abschn.')}` : '',
          kind === 'to_embed' && e.missing ? ` · ${t('{n} Abschnitte einzubetten', { n: fmtInt(e.missing) })}` : '',
          kind === 'pending' && e.chunks ? ` · ${t('früher gelesen, wird neu gelesen')}` : '',
          e.copy_from ? ` · ${t('Kopie aus {lib} (Dublette)', { lib: e.copy_from })}` : '',
          kind === 'current' && extra ? ` · ${extra.step}` : '')),
      kind === 'problems' && e.error ? h('div', { class: 'doc-item-error' }, `${statusText(e.status)}: ${e.error}`) : null,
      e.pdf ? iconBtn('pdf', t('PDF in Zotero öffnen'), () => api.openExternal(e.pdf)) : null)),
    shown.length > 500 ? h('p', { class: 'muted small pad-x' }, t('… und {n} weitere – Filter verwenden.', { n: fmtInt(shown.length - 500) })) : null)
      : h('p', { class: 'muted small pad-x' }, f ? t('Keine Treffer für den Filter.') : t('Keine.')));
}

// Vorauswahl rechts: der Korpus des aktiven Projekts, dessen Texte zuletzt gelesen oder eingebettet wurden; sonst
// der erste des Projekts mit Texten, sonst der erste mit Texten überhaupt (nicht ein leerer, nur weil er vorne steht)
function defaultCorpus() {
  const own = state.corpora.filter(c => (c.project_ids || []).includes(state.projectId));
  const recent = own.filter(c => c.last_indexed_at).sort((a, b) => b.last_indexed_at - a.last_indexed_at)[0];
  const pick = recent || own.find(c => c.stats && c.stats.documents) || own[0]
    || state.corpora.find(c => c.stats && c.stats.documents) || state.corpora[0];
  return pick ? pick.id : null;
}

function documentsPanel(running) {
  const s = st();
  // Ein angeklickter Korpus bleibt gewählt, bis das Projekt wechselt
  if (state.corpora.length && (s.corpusFor !== state.projectId || s.corpus == null || !state.corpora.find(c => c.id === s.corpus))) {
    s.corpusFor = state.projectId;
    s.corpus = defaultCorpus();
  }
  const c = state.corpora.find(x => x.id === s.corpus);
  if (!c) return h('aside', { class: 'index-panel', ...paneProps('index', INDEX_PANE) }, h('p', { class: 'muted pad' }, t('Noch kein Korpus.')), splitter('index', { def: INDEX_PANE, min: 260, max: 760, side: 'right' }));
  if (s.docsFor !== c.id) {
    s.docsFor = c.id; s.docs = null;
    api.get(`/api/corpora/${c.id}/documents`).then(d => { if (st().docsFor === c.id) { st().docs = d; update(); } }).catch(() => {});
  }
  const d = s.docs;
  // Der Text, an dem gerade gearbeitet wird, steht oben unter „In Arbeit“ – nicht schon unter „Indexiert“
  const cur = running && running.counters && running.counters.current;
  const isCur = e => cur && cur.att_key && e.att_key === cur.att_key && e.lib === cur.lib;
  const groups = d && {
    current: [...d.indexed, ...(d.to_embed || []), ...(d.refresh || []), ...d.pending, ...d.problems].filter(isCur),
    indexed: d.indexed.filter(e => !isCur(e)), to_embed: (d.to_embed || []).filter(e => !isCur(e)),
    refresh: (d.refresh || []).filter(e => !isCur(e)),
    pending: d.pending.filter(e => !isCur(e)), problems: d.problems.filter(e => !isCur(e)),
  };
  const curInfo = cur && { fraction: cur.chunks_total ? cur.chunks_done / cur.chunks_total : null, step: t(cur.step) };
  return h('aside', { class: 'index-panel', ...paneProps('index', INDEX_PANE) },
    h('div', { class: 'index-panel-head' },
      h('div', { class: 'row' }, h('div', { class: 'eyebrow grow' }, t('Texte im Korpus')),
        running && h('span', { class: 'live-dot', title: t('Wird während der Indexierung laufend aktualisiert') }, t('live'))),
      h('h3', null, c.name),
      h('div', { class: 'row' },
        h('div', { class: 'tree-search grow' }, icon('search', 14), h('input', { class: 'input input-sm', value: s.docsFilter, placeholder: t('Titel, Autor/in, Jahr …'),
          oninput: e => { s.docsFilter = e.target.value; update(); } })),
        iconBtn('refresh', t('Neu laden'), () => { s.docsFor = null; update(); }))),
    h('div', { class: 'index-panel-body' }, d === null ? h('div', { class: 'pad' }, spinner(16)) : [
      groups.current.length ? docList(t('In Arbeit'), groups.current, 'current', true, curInfo) : null,
      docList(d.model ? t('Indexiert (mit {m} durchsuchbar)', { m: d.model }) : t('Indexiert'), groups.indexed, 'indexed', true),
      groups.to_embed.length ? docList(t('Einzubetten (für {m})', { m: d.model || '' }), groups.to_embed, 'to_embed', groups.to_embed.length < 200) : null,
      groups.refresh.length ? docList(t('Zu aktualisieren (durchsuchbar, wird neu gelesen)'), groups.refresh, 'refresh', false) : null,
      docList(t('Offen (wird beim nächsten Lauf gelesen)'), groups.pending, 'pending', groups.pending.length > 0 && groups.pending.length < 200),
      docList(t('Probleme (ohne Text oder Fehler)'), groups.problems, 'problems', groups.problems.length > 0),
    ]),
    splitter('index', { def: INDEX_PANE, min: 260, max: 760, side: 'right' }));
}

// ------------------------------------------------------------------ Karten
function errorsCard() {
  const s = st();
  if (s.errors === null) {
    s.errors = [];
    api.get('/api/index/errors').then(r => { s.errors = r.errors; update(); }).catch(() => {});
  }
  if (!s.errors.length) return null;
  return card(t('Texte ohne Text oder mit Fehler ({n})', { n: s.errors.length }), 'alert', h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('„Ohne Text“ sind meist Scans ohne Textebene. Abhilfe: Texterkennung (OCR) in den Experteneinstellungen aktivieren oder die PDF mit Texterkennung neu speichern.')),
    h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
      h('thead', null, h('tr', null, h('th', null, t('Titel')), h('th', null, t('Status')), h('th', null, t('Meldung')))),
      h('tbody', null, s.errors.map((e, i) => h('tr', { key: i },
        h('td', null, h('a', { href: `zotero://select/${e.lib.startsWith('users') ? 'library' : e.lib}/items/${e.parent}` }, e.title || e.key)),
        h('td', null, badge(statusText(e.status), e.status === 'no_text' ? 'warning' : 'danger')),
        h('td', { class: 'muted small' }, e.error || ''))))))),
  { class: 'span-2', actions: btn(t('Erneut versuchen'), { size: 'sm', icon: 'refresh', title: queueHint(null), onClick: () => startAll({ retry_errors: true, sync: false }) }) });
}

const hours = () => [{ value: '', label: t('jederzeit') }, ...Array.from({ length: 24 }, (_, i) => ({ value: String(i), label: `${String(i).padStart(2, '0')}:00` }))];

// Die drei Einstellungskarten stehen unter Einstellungen → Index (settings.js)
export function autoCard() {
  const cfg = state.settings && state.settings.indexing;
  if (!cfg) return null;
  const windowOn = cfg.background_from_hour != null && cfg.background_to_hour != null;
  const setHour = (key, v) => saveSettings({ indexing: { [key]: v === '' ? null : Number(v) } });
  return card(t('Automatisch und in Etappen'), 'clock', h('div', { class: 'stack' },
    toggle({ checked: cfg.mode === 'background', label: t('Im Hintergrund aktualisieren, solange Zotero geöffnet ist'),
      onChange: v => saveSettings({ indexing: { mode: v ? 'background' : 'manual' } }) }),
    cfg.mode === 'background' && h('div', { class: 'grid-2' },
      field(t('Prüfen alle … Minuten'), numberInput({ value: cfg.interval_minutes, min: 1, max: 1440, int: true,
        onChange: v => saveSettings({ indexing: { interval_minutes: v } }) })),
      field(t('Höchstens … Texte pro Lauf'), numberInput({ value: cfg.background_max_docs || null, min: 1, max: 100000, int: true, nullable: true, placeholder: t('unbegrenzt'),
        onChange: v => saveSettings({ indexing: { background_max_docs: v || 0 } }) }), { help: t('Etappen: Der nächste Lauf macht dort weiter, wo dieser aufgehört hat.') }),
      field(t('Nur zwischen'), h('div', { class: 'row nowrap' },
        select({ value: cfg.background_from_hour == null ? '' : String(cfg.background_from_hour), options: hours(), onChange: v => setHour('background_from_hour', v) }),
        h('span', { class: 'muted' }, t('und')),
        select({ value: cfg.background_to_hour == null ? '' : String(cfg.background_to_hour), options: hours(), onChange: v => setHour('background_to_hour', v) })),
      { help: t('z. B. 22:00 und 07:00 – über Mitternacht möglich. Am Ende des Zeitfensters wird der laufende Text fertig gemacht und angehalten.') })),
    cfg.mode === 'background' && windowOn && h('p', { class: 'muted small' }, t('Hintergrund-Indexierung nur von {a}:00 bis {b}:00.', { a: String(cfg.background_from_hour).padStart(2, '0'), b: String(cfg.background_to_hour).padStart(2, '0') })),
    h('p', { class: 'muted small' }, t('Neue, geänderte und gelöschte Einträge der Korpora werden erkannt. Bereits indexierte Texte werden nicht erneut verarbeitet.'))));
}

export function safetyCard() {
  const cfg = state.settings && state.settings.indexing;
  const e = state.settings && state.settings.embedding;
  if (!cfg) return null;
  return card(t('Für grosse Bibliotheken'), 'layers', h('div', { class: 'stack' },
    toggle({ checked: cfg.isolate_extraction, label: t('Texte in einem eigenen Prozess lesen'),
      onChange: v => saveSettings({ indexing: { isolate_extraction: v } }) }),
    cfg.isolate_extraction && field(t('Zeitlimit pro Datei (Sekunden)'), numberInput({ value: cfg.extract_timeout_seconds, min: 10, max: 7200, step: 30, int: true,
      onChange: v => saveSettings({ indexing: { extract_timeout_seconds: v } }) }), { help: t('Eine defekte PDF, die das Lesen abstürzen lässt oder hängt, wird als Fehler markiert – die Indexierung läuft weiter.') }),
    toggle({ checked: cfg.keep_awake, label: t('Rechner während der Indexierung wach halten'), onChange: v => saveSettings({ indexing: { keep_awake: v } }) }),
    e && field(t('Bei Ausfall des Embedding-Dienstes warten (Minuten)'), numberInput({ value: e.outage_wait_minutes, min: 0, max: 240, int: true,
      onChange: v => saveSettings({ embedding: { outage_wait_minutes: v } }) }), { help: t('Ist z. B. Ollama kurz weg, pausiert der Lauf und macht danach weiter, statt abzubrechen.') }),
    h('p', { class: 'muted small' }, t('Jeder Text wird sofort gespeichert. Ein Absturz oder Abbruch verliert höchstens den laufenden Text; der nächste Lauf macht dort weiter. Vor dem Start wird der Speicherplatz geprüft.'))));
}

export function backupCard() {
  const s = st();
  const cfg = state.settings && state.settings.indexing;
  if (!cfg) return null;
  if (s.backups === undefined) { s.backups = null; api.get('/api/index/backups').then(r => { s.backups = r; update(); }).catch(() => {}); }
  const b = s.backups;
  return card(t('Sicherung des Index'), 'download', h('div', { class: 'stack' },
    toggle({ checked: cfg.backup_after_run, label: t('Nach Indexierläufen sichern (höchstens alle 12 Stunden, die zwei neuesten bleiben)'),
      onChange: v => saveSettings({ indexing: { backup_after_run: v } }) }),
    b && b.backups.length ? h('div', { class: 'stack-sm' }, b.backups.map(x => h('div', { key: x.name, class: 'row small' }, icon('file', 13),
      h('span', { class: 'grow' }, fmtDate(x.created_at)), h('span', { class: 'muted' }, fmtBytes(x.bytes)))))
      : h('p', { class: 'muted small' }, t('Noch keine Sicherung.')),
    h('div', { class: 'row' },
      btn(t('Jetzt sichern'), { size: 'sm', icon: 'download', disabled: !!runningJob('index'), why: t('Während einer Indexierung wird am Ende automatisch gesichert.'),
        onClick: async () => { s.backups = await run(() => api.post('/api/index/backup')); toast(t('Index gesichert.'), 'success'); update(); } }),
      b && api.isDesktop() && btn(t('Ordner öffnen'), { size: 'sm', kind: 'ghost', icon: 'folder', onClick: () => api.revealPath(b.folder) }))));
}

// ------------------------------------------------------------------ Warteschlange
const QUEUE_KIND = () => ({
  index: t('Indexieren'), embed: t('Nur einbetten'), retry: t('Fehlerhafte Texte erneut versuchen'),
  full_sync: t('Vollständig abgleichen und indexieren'), collections: t('Sammlungen indexieren'), items: t('Einträge indexieren'),
});

// Was in diesem Bereich noch zu tun ist (Zahlen von jetzt, nicht vom Zeitpunkt der Aufnahme)
function queueWork(e) {
  const c = e.corpus_id && state.corpora.find(x => x.id === e.corpus_id);
  const o = st().overview;
  const x = c ? c.stats : !e.corpus_id && e.kind !== 'collections' && e.kind !== 'items' && o && o.stats;
  if (!x) return null;
  const parts = e.kind === 'embed' ? [x.to_embed && t('{n} einzubetten', { n: fmtInt(x.to_embed) })]
    : e.kind === 'retry' ? [x.no_text + x.error && t('{n} mit Problemen', { n: fmtInt(x.no_text + x.error) })]
      : [x.pending && t('{n} offen', { n: fmtInt(x.pending) }), x.refresh && t('{n} zu aktualisieren', { n: fmtInt(x.refresh) }),
        x.to_embed && t('{n} einzubetten', { n: fmtInt(x.to_embed) })];
  const shown = parts.filter(Boolean);
  return shown.length ? shown.join(' · ') : t('derzeit nichts offen');
}

function queueCard() {
  const q = (state.status && state.status.index_queue) || [];
  if (!q.length) return null;
  const allProjects = t('alle Projekte');
  return card(t('Warteschlange ({n})', { n: q.length }), 'queue', h('div', { class: 'stack-sm' },
    h('p', { class: 'muted small' }, t('Diese Läufe starten nacheinander, sobald der laufende fertig ist. Abbrechen beendet nur den laufenden Lauf – danach kommt der nächste an die Reihe.')),
    h('div', { class: 'queue-list' }, q.map((e, i) => {
      const where = e.kind === 'collections' ? t('{n} Sammlung(en) aus Zotero', { n: e.collections })
        : e.kind === 'items' ? t('{n} Einträge aus Zotero', { n: e.items })
          : e.corpus_id ? (e.corpus || t('Korpus gelöscht')) : t('Alle Korpora');
      const projects = e.corpus_id ? (e.projects.length ? e.projects.join(', ') : t('in keinem Projekt')) : ['collections', 'items'].includes(e.kind) ? null : allProjects;
      const work = queueWork(e);
      return h('div', { key: e.id, class: 'queue-item' },
        h('span', { class: 'queue-pos' }, String(i + 1)),
        h('div', { class: 'grow' },
          h('div', { class: 'queue-title' }, h('b', null, QUEUE_KIND()[e.kind] || e.title), h('span', null, ` · ${where}`)),
          h('div', { class: 'muted small' }, [projects && t('Projekt: {p}', { p: projects }), work,
            t('eingereiht {ago}', { ago: fmtAgo(e.queued_at) })].filter(Boolean).join(' · '))),
        h('div', { class: 'queue-actions' },
          iconBtn('chevronUp', t('Früher starten'), () => moveQueued(e.id, -1), { disabled: i === 0 }),
          iconBtn('chevronDown', t('Später starten'), () => moveQueued(e.id, 1), { disabled: i === q.length - 1 }),
          iconBtn('trash', t('Aus der Warteschlange entfernen'), () => removeQueued(e.id))));
    }))),
  { class: 'span-2' });
}

// ------------------------------------------------------------------ Zustand, letzter Lauf, Verlauf
const fmtClock = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function nextCheckText(o) {
  if (o.mode !== 'background') return t('Automatische Indexierung aus');
  if (!o.next_check_at) return null;
  const sameDay = new Date(o.next_check_at * 1000).toDateString() === new Date().toDateString();
  const when = o.next_check_at - Date.now() / 1000 < 60 ? t('gleich') : sameDay ? t('um {t}', { t: fmtClock(o.next_check_at) }) : fmtDate(o.next_check_at);
  return t('nächste automatische Prüfung {w}', { w: when }) + (o.zotero_running ? '' : ` (${t('sobald Zotero läuft')})`);
}

function stateCard(running) {
  const s = st();
  const o = s.overview;
  if (!o) return card(t('Zustand des Index (alle Korpora)'), 'index', spinner(16), { class: 'span-2' });
  if (!o.corpora) {
    return card(t('Zustand des Index (alle Korpora)'), 'index', notice('info', t('Noch kein Wissenskorpus – ohne Korpus wird nichts indexiert.'),
      h('div', { class: 'notice-actions' }, btn(t('Korpus anlegen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => navigate('corpora') }))), { class: 'span-2' });
  }
  const x = o.stats;
  const model = (o.model && o.model.label) || '';
  const problems = x.no_text + x.error;
  const item = (v, label, kind, title, sub = null) => h('div', { class: ['stat', kind && `stat-${kind}`], title },
    h('div', { class: 'stat-value' }, v), h('div', { class: 'stat-label' }, label), sub && h('div', { class: 'stat-sub' }, sub));
  const meta = [o.checked_at ? t('zuletzt geprüft {ago}', { ago: fmtAgo(o.checked_at) }) : null, nextCheckText(o)].filter(Boolean).join(' · ');
  const eta = o.embed_estimate != null && x.to_embed ? ` (≈ ${o.embed_estimate < 60 ? t('< 1 min') : fmtDuration(o.embed_estimate)})` : '';
  const frac = running && jobFraction(running);
  const runEta = running && etaText(running.counters || {});
  let action;
  if (running) {
    action = h('span', { class: 'row small' }, progressRing(frac, 16), t('Indexierung läuft …'),
      frac != null ? h('b', null, ` ${Math.round(frac * 100)} %`) : null, runEta ? h('span', { class: 'muted' }, ` · ${runEta}`) : null);
  } else if (x.pending || x.refresh) {
    // Der Knopf sagt, was ein Lauf tut: er liest offene Texte, liest wartende neu ein und bettet fehlende Vektoren ein.
    // Daneben (falls nötig) „Nur einbetten“: schnell, macht gelesene Texte durchsuchbar, ohne etwas neu zu lesen.
    const parts = [x.pending && t('{n} lesen', { n: fmtInt(x.pending) }), x.refresh && t('{n} neu einlesen', { n: fmtInt(x.refresh) }),
      x.to_embed && t('{n} einbetten', { n: fmtInt(x.to_embed) })].filter(Boolean);
    action = h('div', { class: 'row' },
      x.to_embed ? btn(t('Nur einbetten') + eta, { kind: 'secondary', size: 'sm', icon: 'play',
        title: `${t('{t} für {m} einbetten, ohne etwas neu zu lesen.', { t: nTexts(x.to_embed), m: model })} ${embedHint()}`, onClick: () => startEmbedding() }) : null,
      btn(`${t('Indexieren')}: ${parts.join(' · ')}`, { kind: 'primary', size: 'sm', icon: 'play',
        title: t('Ein Lauf erledigt alles: offene Texte lesen, wartende neu einlesen, fehlende Vektoren einbetten.'), onClick: () => startAll() }));
  } else if (x.to_embed) {
    action = btn(t('{t} für {m} einbetten', { t: nTexts(x.to_embed), m: model }) + eta, { kind: 'primary', size: 'sm', icon: 'play', title: embedHint(), onClick: () => startEmbedding() });
  } else {
    action = h('span', { class: 'ok-text small' }, icon('check', 14), ' ', t('Alles aktuell'));
  }
  const notes = [
    x.to_embed && (x.to_embed === 1
      ? t('1 Text ist gelesen, aber für {m} noch nicht eingebettet – die Bedeutungssuche findet ihn noch nicht.', { m: model })
      : t('{t} sind gelesen, aber für {m} noch nicht eingebettet – die Bedeutungssuche findet sie noch nicht.', { t: nTexts(x.to_embed), m: model })),
    x.refresh && (x.refresh === 1 ? t('1 Text wartet auf erneutes Lesen und bleibt bis dahin durchsuchbar.')
      : t('{n} Texte warten auf erneutes Lesen und bleiben bis dahin durchsuchbar.', { n: fmtInt(x.refresh) })),
  ].filter(Boolean);
  return card(t('Zustand des Index (alle Korpora)'), 'index', h('div', { class: 'index-state' },
    model && h('div', { class: 'small' }, t('Embedding-Modell:'), ' ', h('b', null, model),
      notes.length ? h('span', { class: 'muted' }, ` · ${notes.join(' ')}`) : null),
    h('div', { class: 'stats-row' },
      item(fmtInt(x.documents), t('Texte'), null, t('Dateien mit Text in allen Korpora')),
      // Texte = indexiert + einzubetten + offen + Probleme; „zu aktualisieren“ ist ein Teil von „indexiert“
      item(fmtInt(nIndexed(x)), t('indexiert'), 'ok', x.refresh ? `${t('mit {m} durchsuchbar', { m: model })}. ${refreshHint()}` : t('mit {m} durchsuchbar', { m: model }),
        x.refresh ? [icon('refresh', 11), ' ', t('davon {n} zu aktualisieren', { n: fmtInt(x.refresh) })] : null),
      x.to_embed ? item(fmtInt(x.to_embed), t('einzubetten'), 'warn', `${t('Text gelesen, für {m} noch nicht eingebettet', { m: model })}. ${embedHint()}`) : null,
      item(fmtInt(x.pending), t('offen'), x.pending ? 'warn' : null, openHint(model)),
      item(fmtInt(problems), t('Probleme'), problems ? 'err' : null, t('ohne Text oder mit Fehler')),
      item(x.chunks_missing ? `${fmtInt(x.embedded)} / ${fmtInt(x.chunks)}` : fmtInt(x.embedded), t('Abschnitte durchsuchbar'))),
    h('div', { class: 'index-state-foot' }, h('span', { class: 'muted small grow' }, meta), action)),
  { class: 'span-2' });
}

const RUN_STATUS = () => ({
  done: [t('fertig'), 'success', 'check'], problems: [t('fertig mit Problemen'), 'warning', 'alert'], stage: [t('Etappe beendet'), 'info', 'clock'],
  switched: [t('Modell gewechselt'), 'info', 'refresh'], cancelled: [t('abgebrochen'), 'warning', 'stop'], error: [t('Fehler'), 'danger', 'alert'],
});
const runOutcome = r => (r.status === 'done' && r.no_text + r.errors ? 'problems' : r.status);
const runDuration = r => fmtDuration(Math.max(0, (r.finished_at || 0) - (r.started_at || 0)));
const triggerLabel = r => (r.trigger === 'background' ? t('automatisch') : t('von Hand'));

function continueRun(r) {
  const c = r.corpus_id && state.corpora.find(x => x.id === r.corpus_id);
  if (c) indexCorpus(c); else startAll();
}

function reportCard(r) {
  const s = st();
  const out = runOutcome(r);
  const [label, kind, ic] = RUN_STATUS()[out] || RUN_STATUS().done;
  const problems = r.no_text + r.errors;
  const rate = r.chunks && r.finished_at > r.started_at ? r.chunks / (r.finished_at - r.started_at) : 0;
  if (s.runDetail && s.runDetail.id !== r.id) s.runDetail = null;
  const loadDetail = () => { if (!s.runDetail) api.get(`/api/index/runs/${r.id}`).then(d => { s.runDetail = d; update(); }).catch(() => {}); };
  const showProblems = () => { s.runDocsFilter = 'problems'; s.runDocsOpen = true; loadDetail(); update(); };
  const embedded = r.embedded_docs || 0;
  const doneText = embedded && !r.indexed
    ? t('{t} für {m} eingebettet ({c} Abschnitte), ohne sie neu zu lesen.', { t: nTexts(embedded), m: r.model || '', c: fmtInt(r.chunks) })
    : embedded
      ? t('{r} gelesen und eingebettet, {e} nur für {m} eingebettet, zusammen {c} Abschnitte.', { r: nTexts(r.indexed), e: nTexts(embedded), m: r.model || '', c: fmtInt(r.chunks) })
      : t('{t} verarbeitet, {c} Abschnitte eingebettet.', { t: nTexts(r.docs_done), c: fmtInt(r.chunks) });
  const message = {
    done: doneText,
    problems: t('{t} verarbeitet, davon ohne Text oder mit Fehler: {p}.', { t: nTexts(r.docs_done), p: fmtInt(problems) }),
    stage: r.stopped || doneText,
    switched: r.stopped,
    cancelled: t('Abgebrochen nach {n} von {m} Texten. Bereits verarbeitete Texte bleiben im Index.', { n: fmtInt(r.docs_done), m: fmtInt(r.docs_total) }),
    error: r.error || t('Fehler'),
  }[out];
  const action = { problems: btn(t('Probleme ansehen'), { size: 'sm', icon: 'alert', onClick: showProblems }),
    stage: btn(t('Jetzt weitermachen'), { size: 'sm', kind: 'primary', icon: 'play', disabled: !!runningJob('index'), onClick: () => continueRun(r) }),
    switched: btn(t('Mit dem neuen Modell weitermachen'), { size: 'sm', kind: 'primary', icon: 'play', disabled: !!runningJob('index'), onClick: () => continueRun(r) }),
    cancelled: btn(t('Fortsetzen'), { size: 'sm', kind: 'primary', icon: 'play', disabled: !!runningJob('index'), onClick: () => continueRun(r) }),
    error: btn(t('Erneut starten'), { size: 'sm', icon: 'refresh', disabled: !!runningJob('index'), onClick: () => continueRun(r) }) }[out];
  const d = s.runDetail;
  const docs = d ? d.docs.filter(x => s.runDocsFilter !== 'problems' || !['indexed', 'embedded'].includes(x.status)) : [];
  return card(t('Letzter Lauf'), 'history', h('div', { class: 'stack' },
    h('div', { class: 'run-head' },
      h('span', { class: `badge badge-${kind}` }, icon(ic, 12), ' ', label),
      h('span', { class: 'small' }, `${fmtDate(r.started_at)} · ${t('Dauer {d}', { d: runDuration(r) })} · ${triggerLabel(r)}`),
      r.model && h('span', { class: 'small' }, t('Modell {m}', { m: r.model })),
      r.title && h('span', { class: 'muted small' }, r.title)),
    notice(out === 'done' ? 'success' : out === 'error' ? 'error' : ['stage', 'switched'].includes(out) ? 'info' : 'warning', message, action ? h('div', { class: 'notice-actions' }, action) : null),
    h('div', { class: 'stats-row' },
      stat(t('Texte verarbeitet'), fmtInt(r.docs_done)), stat(t('gelesen'), fmtInt(r.indexed)),
      embedded ? stat(t('nur eingebettet'), fmtInt(embedded)) : null, stat(t('ohne Text'), fmtInt(r.no_text)),
      stat(t('Fehler'), fmtInt(r.errors)), stat(t('Abschnitte'), fmtInt(r.chunks)), stat(t('Abschnitte/s'), rate ? fmtNum(rate, 2) : '–')),
    r.docs_done ? h('details', { class: 'run-docs', open: s.runDocsOpen, ontoggle: e => { s.runDocsOpen = e.target.open; if (e.target.open) loadDetail(); } },
      h('summary', null, t('Verarbeitete Texte ({n})', { n: fmtInt(r.docs_done) })),
      !d ? h('div', { class: 'pad' }, spinner(14)) : [
        problems ? h('div', { class: 'row small run-filter' },
          btn(t('Alle'), { size: 'sm', kind: s.runDocsFilter === 'all' ? 'secondary' : 'ghost', onClick: () => { s.runDocsFilter = 'all'; update(); } }),
          btn(t('Nur Probleme ({n})', { n: problems }), { size: 'sm', kind: s.runDocsFilter === 'problems' ? 'secondary' : 'ghost', onClick: () => { s.runDocsFilter = 'problems'; update(); } })) : null,
        h('div', { class: 'job-list' }, docs.slice(0, 1000).map((x, i) => {
          const [dic, cls] = STATUS_ICON[x.status] || ['dot', ''];
          return h('div', { key: i, class: 'job-list-item', title: x.message || '' },
            icon(dic, 14, `${cls}-text`), h('a', { class: 'grow', href: x.select, title: t('In Zotero zeigen') }, x.title),
            h('span', { class: 'muted small nowrap' }, ['indexed', 'embedded'].includes(x.status)
              ? `${x.status === 'embedded' ? t('eingebettet') + ' · ' : ''}${x.pages ? `${x.pages} ${t('S.')} · ` : ''}${fmtInt(x.chunks)} ${t('Abschn.')}`
              : `${statusText(x.status)}${x.message ? ': ' + x.message : ''}`));
        })),
        d.log && d.log.length ? h('details', { class: 'job-log' }, h('summary', null, t('Protokoll')), h('pre', null, d.log.join('\n'))) : null]) : null),
  { class: 'span-2', actions: iconBtn('x', t('Ausblenden – bleibt im Verlauf'), async () => {
    await run(() => api.post(`/api/index/runs/${r.id}/dismiss`));
    s.runs = undefined; s.selectedRun = null; update();
  }) });
}

function stat(label, value) {
  return h('div', { class: 'stat' }, h('div', { class: 'stat-value' }, value ?? '–'), h('div', { class: 'stat-label' }, label));
}

function historyCard() {
  const s = st();
  const runs = s.runs || [];
  if (!runs.length) return null;
  // Höchstens fünf Läufe auf einmal sichtbar, ältere per Scrollen (der Kopf bleibt stehen)
  return card(t('Verlauf der Läufe'), 'clock', h('div', { class: ['table-wrap', 'history-scroll', runs.length > 5 && 'is-long'] }, h('table', { class: 'grid clickable' },
    h('thead', null, h('tr', null, h('th', null, t('Beginn')), h('th', null, t('Auslöser')), h('th', null, t('Modell')), h('th', null, t('Ergebnis')),
      h('th', { class: 'num' }, t('Texte')), h('th', { class: 'num' }, t('Probleme')), h('th', { class: 'num' }, t('Abschnitte')), h('th', { class: 'num' }, t('Dauer')))),
    h('tbody', null, runs.map(r => {
      const [label, kind] = RUN_STATUS()[runOutcome(r)] || RUN_STATUS().done;
      return h('tr', { key: r.id, class: s.selectedRun === r.id ? 'selected' : null, title: t('Bericht dieses Laufs anzeigen'),
        onclick: () => { s.selectedRun = r.id; s.runDetail = null; s.runDocsOpen = false; s.runDocsFilter = 'all'; update();
          document.querySelector('.index-main')?.scrollTo({ top: 0, behavior: 'smooth' }); } },
      h('td', { class: 'nowrap' }, fmtDate(r.started_at)), h('td', { class: 'small' }, triggerLabel(r)), h('td', { class: 'small' }, r.model || '–'),
      h('td', null, badge(label, kind), r.embedded_docs && !r.indexed ? h('span', { class: 'muted small' }, ` ${t('nur eingebettet')}`) : null),
      h('td', { class: 'num' }, fmtInt(r.docs_done)), h('td', { class: 'num' }, r.no_text + r.errors ? badge(fmtInt(r.no_text + r.errors), 'danger') : '0'),
      h('td', { class: 'num' }, fmtInt(r.chunks)), h('td', { class: 'num nowrap' }, runDuration(r)));
    })))),
  { class: 'span-2' });
}

export function indexView() {
  const s = st();
  if (!s.loadedJobs) {
    s.loadedJobs = true;
    api.get('/api/jobs').then(r => { for (const j of r.jobs) state.jobs[j.id] = j; update(); }).catch(() => {});
  }
  const running = runningJob('index');
  follow(running || lastIndexJob());
  loadOverview();
  loadRuns();
  liveRefresh(running);
  // Bericht: der im Verlauf gewählte Lauf, sonst der jüngste, solange er nicht ausgeblendet wurde
  const runs = s.runs || [];
  const report = !running && (runs.find(r => r.id === s.selectedRun) || (runs[0] && !runs[0].dismissed ? runs[0] : null));
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Index'), t('Texte der Wissenskorpora einlesen und durchsuchbar machen'), [
      iconBtn('settings', t('Einstellungen zur Indexierung (automatisch, grosse Bibliotheken, Sicherung)'), () => { ui('settings', {}).tab = 'index'; navigate('settings'); }),
      btn(t('Vollständig abgleichen'), { kind: 'ghost', size: 'sm', icon: 'refresh', title: queueHint(t('Alle Metadaten neu aus Zotero laden (sonst automatisch wöchentlich)')), onClick: () => startAll({ full_sync: true }) }),
      btn(t('Alle Korpora indexieren'), { kind: 'primary', icon: 'play', title: queueHint(null), onClick: () => startAll() }),
    ]),
    h('div', { class: 'index-layout' },
      h('div', { class: 'index-main scroll' }, h('div', { class: 'index-grid' },
        stateCard(running),
        running ? card(t('Laufende Indexierung'), 'refresh', jobPanel(running), { class: 'span-2' }) : report ? reportCard(report) : null,
        queueCard(),
        card(t('Korpora (alle Projekte)'), 'corpus', corporaTable(), { class: 'span-2' }),
        duplicatesCard(),
        historyCard(),
        errorsCard())),
      documentsPanel(running)));
}
