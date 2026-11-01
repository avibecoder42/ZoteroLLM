// Forschungsstand in fünf Schritten: Stichworte (Suchstrategie) → Literatur auswählen (Suche, Auswahl bestätigen) →
// auswerten → schreiben → prüfen. Alles im aktiven Projekt; durchsucht werden die gewählten Korpora des Projekts.
// Jeder Schritt sieht gleich aus: oben die Schritte, darunter links der eingeklappte Prompt und rechts die Knöpfe zum
// Weitermachen, darunter der Inhalt des Schritts.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, confirmDialog, watchJob, runningJob, loadStatus, loadProjects, project, projectCorpora } from '../core/store.js';
import * as api from '../core/api.js';
import { t, OUTPUT_LANGUAGES, languageName } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, card, foldCard, notice, spinner, progress, field, textInput, textArea, select, segmented, numberInput, checkbox, badge, emptyState, multiSelect, paneProps, splitter } from '../ui/components.js';
import { fmtInt, fmtAgo, fmtDate, fmtDuration, fmtNum, plural, nTexts, nIndexed } from '../core/util.js';
import { markdown } from '../core/markdown.js';
import { navigate, viewHeader, openCitePopover } from './shell.js';
import { exportMenu, copyTarget } from './exports.js';
import { coverageNotice } from './embedmodels.js';

const STEPS = () => [
  { n: 1, title: t('Stichworte'), sub: t('Suchanfragen prüfen und ergänzen') },
  { n: 2, title: t('Literatur auswählen'), sub: t('Suche und Auswahl') },
  { n: 3, title: t('Auswerten'), sub: t('Auswertungsblatt je Text') },
  { n: 4, title: t('Schreiben'), sub: t('Gliederung und Abschnitte') },
  { n: 5, title: t('Prüfen'), sub: t('Belege, Zitate, Text, Ausgabe') },
];
// Fortschritt laut Dienst → letzter erreichbarer Schritt
const STEP_OF = { created: 1, strategy: 1, candidates: 2, confirmed: 3, extracted: 4, outlined: 4, written: 5 };
const reachedOf = r => STEP_OF[r.state.step] || 1;
const DECISIONS = () => ({
  include: [t('vorgeschlagen'), 'success'], maybe: [t('vielleicht'), 'warning'], exclude: [t('ausgeschlossen'), 'neutral'], manual: [t('in Zotero ergänzt'), 'info'],
});

function st() {
  return ui('review', { list: null, openId: null, review: null, loading: false, tab: null, filter: 'all', estimate: null,
    outline: null, outlineDirty: false, form: null, presetCorpus: null, jobId: null,
    queries: null, queriesDirty: false, editTitle: null, text: null, promptOpen: false, sheets: {}, sheetOpen: {} });
}

async function loadList() {
  const s = st();
  try { s.list = (await api.get(`/api/reviews?project=${state.projectId}`)).reviews; } catch { s.list = []; }
  update();
}

async function openReview(id, { keepTab = false } = {}) {
  const s = st();
  s.openId = id;
  if (id === 'new') { s.review = null; s.form = newForm(); update(); return; }
  s.loading = true; update();
  try {
    const r = await api.get(`/api/reviews/${id}`);
    if (s.openId !== id) return;
    s.review = r;
    if (!keepTab) { s.tab = null; s.sheetOpen = {}; }
    s.estimate = null;
    s.outline = null; s.outlineDirty = false;
    s.queries = null; s.queriesDirty = false; s.editTitle = null;
    s.text = null; s.sheets = {};
  } catch (err) { toast(err.message, 'error'); s.openId = null; s.review = null; }
  s.loading = false;
  update();
}

// Sprache neuer Forschungsstände: Einstellung „Sprache der KI-Ausgaben“, sonst die der Oberfläche
function defaultLanguage() {
  const cfg = state.settings || {};
  return cfg.output_language && cfg.output_language !== 'auto' ? cfg.output_language : (cfg.language || 'de');
}

function newForm() {
  const s = st();
  const preset = s.presetCorpus; s.presetCorpus = null;
  const all = projectCorpora().map(c => c.id);
  return { question: '', title: '', corpora: preset != null && all.includes(preset) ? [preset] : all,
    language: defaultLanguage(), words: state.settings ? state.settings.review.target_words : 4000 };
}

function corpusOptions() {
  return projectCorpora().map(c => ({ value: c.id, label: c.name, hint: nTexts(nIndexed(c.stats)) }));
}

function corpusIds(r) {
  const f = (r.state && r.state.filters) || {};
  return f.corpus_ids || (f.corpus_id ? [f.corpus_id] : []);
}

// Hintergrundauftrag des Forschungsstands starten und beobachten; nextTab: danach zu diesem Schritt wechseln
async function startJob(path, okMessage, { nextTab = null, body } = {}) {
  const s = st();
  const rid = s.review.id;
  const job = await run(() => api.post(path, body));
  state.jobs[job.id] = job;
  s.jobId = job.id;
  update();
  const done = await watchJob(job.id);
  if (s.jobId === job.id) s.jobId = null;
  if (done.status === 'done') {
    toast(done.message || okMessage, 'success');
    if (nextTab && s.review && s.review.id === rid) s.tab = nextTab;
  } else if (done.status === 'error') toast(done.error, 'error', 12000);
  if (s.review && s.review.id === rid) await openReview(rid, { keepTab: true });
  loadList();
  loadProjects();
}

// Nur einen Abschnitt neu schreiben (z. B. einen abgeschnittenen) – die übrigen bleiben unverändert
async function rewriteSection(r, i) {
  const sec = (r.state.sections || [])[i];
  if (!sec) return;
  if (!await confirmDialog(t('Abschnitt neu schreiben?'), t('„{h}“ wird anhand der Auswertungsblätter neu geschrieben; die übrigen Abschnitte bleiben unverändert.', { h: sec.heading }), { ok: t('Neu schreiben') })) return;
  startJob(`/api/reviews/${r.id}/sections/${i}/rewrite`, t('Abschnitt neu geschrieben'));
}

// Zu lange Abschnitte auf die geplante Länge kürzen lassen (einer oder alle)
async function shortenSections(r, list) {
  const one = list.length === 1;
  const text = one
    ? t('„{h}“ wird vom Sprachmodell auf etwa {n} Wörter gekürzt. Belege und wörtliche Zitate bleiben; Neues kommt nicht dazu. Die bisherige Fassung wird ersetzt.', { h: list[0].heading, n: fmtInt(list[0].planned) })
    : t('{n} Abschnitte werden vom Sprachmodell auf ihre geplante Länge gekürzt. Belege und wörtliche Zitate bleiben; Neues kommt nicht dazu. Die bisherigen Fassungen werden ersetzt.', { n: list.length });
  if (!await confirmDialog(one ? t('Abschnitt kürzen?') : t('Abschnitte kürzen?'), text, { ok: t('Kürzen') })) return;
  startJob(`/api/reviews/${r.id}/shorten`, t('Gekürzt'), { body: { sections: list.map(x => x.index) } });
}

// Abschnitte, die mehr als 20 % über ihrer geplanten Länge liegen, mit „Kürzen“ je Abschnitt bzw. für alle
function longCard(r, job) {
  const list = (r.state.check && r.state.check.long_sections) || [];
  if (!list.length) return null;
  const busy = { disabled: !!job, why: t('Es läuft bereits ein Auftrag.') };
  return card(t('Zu lange Abschnitte'), 'alert', h('div', { class: 'stack-sm' },
    list.map(x => h('div', { key: x.index, class: 'row incomplete-sec' },
      h('div', { class: 'grow' }, h('b', null, x.heading), h('div', { class: 'muted small' },
        t('{a} statt etwa {b} Wörter (+{p} %)', { a: fmtInt(x.words), b: fmtInt(x.planned), p: Math.round(100 * (x.words / x.planned - 1)) }))),
      btn(t('Kürzen'), { size: 'sm', icon: 'scissors', ...busy, onClick: () => shortenSections(r, [x]) }))),
    h('p', { class: 'muted small' }, t('„Kürzen“ lässt das Sprachmodell den Abschnitt auf die Länge aus der Gliederung straffen – ohne die Auswertungsblätter, also ohne neue Inhalte. Danach den Abschnitt lesen.'))),
  { class: 'card-warning', actions: list.length > 1 ? btn(t('Alle kürzen'), { size: 'sm', icon: 'scissors', ...busy, onClick: () => shortenSections(r, list) }) : null });
}

// Abschnitte, die abgebrochen bzw. unvollständig sind (aus der Prüfung), mit „Neu schreiben“ je Abschnitt
function incompleteCard(r, job) {
  const list = (r.state.check && r.state.check.incomplete_sections) || [];
  if (!list.length) return null;
  const reason = x => code => ({
    'stopped:length': t('beim Längenlimit abgebrochen'),
    'stopped:recitation': t('vom Anbieter abgebrochen (längere wörtliche Wiedergabe)'),
    quote: t('Zitat ohne schliessendes Anführungszeichen'),
    sentence: t('endet mitten im Satz'),
    short: x.planned ? t('deutlich kürzer als geplant ({a} statt etwa {b} Wörter)', { a: fmtInt(x.words), b: fmtInt(x.planned) }) : t('deutlich kürzer als geplant'),
  }[code] || code);
  return card(t('Unvollständige Abschnitte'), 'alert', h('div', { class: 'stack-sm' },
    list.map(x => h('div', { key: x.index, class: 'row incomplete-sec' },
      h('div', { class: 'grow' }, h('b', null, x.heading), h('div', { class: 'muted small' }, x.reasons.map(reason(x)).join(' · '))),
      btn(t('Neu schreiben'), { size: 'sm', icon: 'edit', disabled: !!job, why: t('Es läuft bereits ein Auftrag.'), onClick: () => rewriteSection(r, x.index) }))),
    h('p', { class: 'muted small' }, t('Meist hat der Anbieter die Ausgabe abgebrochen – beim Längenlimit oder (bei Gemini) wegen einer längeren wörtlichen Wiedergabe. „Neu schreiben“ ersetzt nur diesen Abschnitt.'))),
  { class: 'card-warning' });
}

function currentJob() {
  const s = st();
  const j = s.jobId && state.jobs[s.jobId];
  if (j && ['queued', 'running'].includes(j.status)) return j;
  return null;
}

function jobBox(job) {
  const c = job.total ? t('{a} von {b}', { a: job.done, b: job.total }) : '';
  return h('div', { class: 'job-inline' },
    h('div', { class: 'job-line' }, spinner(14), h('b', null, job.phase || job.title), h('span', { class: 'muted' }, c),
      h('span', { class: 'spacer' }), job.eta ? h('span', { class: 'muted small' }, t('noch ca. {d}', { d: fmtDuration(job.eta) })) : null,
      btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', icon: 'stop', onClick: () => api.post(`/api/jobs/${job.id}/cancel`) })),
    progress(job.done, job.total || 0, job.message),
    job.usage && job.usage.input_tokens ? h('div', { class: 'muted small' }, t('{i} Input-Token und {o} Output-Token', { i: fmtInt(job.usage.input_tokens), o: fmtInt(job.usage.output_tokens) })) : null);
}

// ------------------------------------------------------------------ Liste
function reviewList() {
  const s = st();
  if (s.list === null) { loadList(); return h('aside', { class: 'side-list', ...paneProps('review', 270) }, spinner(16)); }
  return h('aside', { class: 'side-list', ...paneProps('review', 270) },
    btn(t('Neuer Forschungsstand'), { kind: 'primary', icon: 'plus', onClick: () => openReview('new') }),
    h('div', { class: 'side-items' }, s.list.length ? s.list.map(r => h('div', {
      key: r.id, class: ['side-item', r.id === s.openId && 'active'], role: 'button', tabindex: 0, onclick: () => openReview(r.id),
    }, h('div', { class: 'side-item-text', title: `${r.title}\n\n${r.question}` }, h('div', { class: 'side-item-title wrap2' }, r.title), h('div', { class: 'side-item-sub' }, fmtAgo(r.updated_at))),
    iconBtn('trash', t('Löschen'), async e => {
      e.stopPropagation();
      if (!await confirmDialog(t('Forschungsstand löschen?'), t('„{title}“ wird gelöscht. Auswertungsblätter und Notizen in Zotero bleiben erhalten.', { title: r.title }), { ok: t('Löschen'), danger: true })) return;
      await api.del(`/api/reviews/${r.id}`);
      if (r.id === s.openId) { s.openId = null; s.review = null; }
      loadList(); loadProjects();
    }))) : h('p', { class: 'muted small pad' }, t('Noch keine Forschungsstände in diesem Projekt.'))),
    splitter('review', { def: 270, max: 520 }));
}

// ------------------------------------------------------------------ Neu anlegen
function newReviewForm() {
  const s = st();
  const f = s.form || (s.form = newForm());
  const options = corpusOptions();
  const create = async () => {
    if (!f.question.trim()) { toast(t('Bitte eine Forschungsfrage eingeben.'), 'warning'); return; }
    if (!f.corpora.length) { toast(t('Bitte mindestens einen Wissenskorpus wählen.'), 'warning'); return; }
    const r = await run(() => api.post('/api/reviews', { question: f.question.trim(), title: f.title.trim(), filters: { corpus_ids: f.corpora },
      language: f.language, target_words: f.words, project_id: state.projectId }));
    s.form = null;
    await loadList();
    await openReview(r.id);
    startJob(`/api/reviews/${r.id}/strategy`, t('Suchstrategie vorgeschlagen'));
  };
  return h('div', { class: 'review-new' },
    h('div', { class: 'review-intro' },
      h('h2', null, t('Neuer Forschungsstand')),
      h('p', { class: 'muted' }, t('Zuerst schlägt Zotivity eine Suchstrategie vor: viele Suchanfragen auf Deutsch und Englisch. Du prüfst und ergänzt sie, dann wird gesucht, eine Auswahl vorgeschlagen und auf deine Bestätigung gewartet. Erst danach werden die Texte einzeln ausgewertet und der Forschungsstand geschrieben.')),
      h('ol', { class: 'review-steps-mini' }, STEPS().map(x => h('li', { key: x.n }, h('b', null, x.title), ' – ', x.sub)))),
    h('div', { class: 'card stack' },
      field(t('Forschungsfrage'), textArea({ value: f.question, rows: 3, placeholder: t('z. B. Wie nutzen Jugendliche generative KI für schulische Aufgaben, und welche Folgen für das Lernen werden berichtet?'),
        onInput: v => { f.question = v; } }), { hint: t('Je genauer die Frage, desto besser die Suchstrategie.') }),
      field(t('Wissenskorpora'), options.length ? multiSelect({ values: f.corpora, options, placeholder: t('Korpora wählen …'), label: t('Wissenskorpora'),
        onChange: v => { f.corpora = v; update(); } }) : notice('warning', t('Diesem Projekt ist noch kein Wissenskorpus zugeordnet.'),
        h('div', { class: 'notice-actions' }, btn(t('Zu den Korpora'), { size: 'sm', onClick: () => navigate('corpora') })),
        { dismiss: `review-nocorpus:${state.projectId}`, session: true }),
      { help: t('Nur Texte aus diesen Korpora des Projekts werden durchsucht.') }),
      h('div', { class: 'grid-2' },
        field(t('Titel (optional)'), textInput({ value: f.title, placeholder: t('sonst schlägt Zotivity einen kurzen Titel vor'), onInput: v => { f.title = v; } })),
        field(t('Sprache des Textes'), select({ value: f.language, options: OUTPUT_LANGUAGES.map(c => ({ value: c, label: languageName(c) })), onChange: v => { f.language = v; update(); } })),
        field(t('Ziel-Länge (Wörter)'), numberInput({ value: f.words, min: 300, max: 40000, step: 500, int: true, onChange: v => { f.words = v; update(); } }), { help: t('Länge des Textes mit Überschriften und Belegen – Literaturverzeichnis und Anhang „Methode der Literatursuche“ kommen dazu.') })),
      h('div', { class: 'row end' },
        btn(t('Anlegen und Suchstrategie vorschlagen'), { kind: 'primary', icon: 'search', disabled: !!runningJob('review') || !options.length,
          why: options.length ? t('Es läuft bereits ein Auftrag.') : t('Zuerst einen Korpus anlegen.'), onClick: create }))));
}

// ------------------------------------------------------------------ Schritte
// Jeder Schritt liefert { actions, body }: die Knöpfe zum Weitermachen (oben rechts, immer an derselben Stelle)
// und den Inhalt darunter.
function stepper(r, active) {
  const s = st();
  const reached = reachedOf(r);
  return h('ol', { class: 'stepper' }, STEPS().map(x => h('li', { key: x.n },
    h('button', { type: 'button', class: ['step', x.n === active && 'active', x.n < reached && 'done'], disabled: x.n > reached,
      onclick: () => { s.tab = x.n; update(); } },
    h('span', { class: 'step-num' }, x.n < reached ? icon('check', 14) : x.n),
    h('span', { class: 'step-text' }, h('span', { class: 'step-title' }, x.title), h('span', { class: 'step-sub' }, x.sub))))));
}

function nextBtn(n, label) {
  return btn(label, { kind: 'primary', icon: 'chevronRight', onClick: () => { st().tab = n; update(); } });
}

function docTitle(d) {
  return h('div', { class: 'doc-text' },
    h('div', { class: 'doc-title' }, h('a', { href: d.zotero_select, title: t('In Zotero zeigen') }, d.title || d.item_key)),
    h('div', { class: 'muted small' }, d.citation));
}

async function saveQueries(r) {
  const s = st();
  const saved = await run(() => api.put(`/api/reviews/${r.id}/strategy`, { queries: s.queries }));
  if (!saved) return;
  s.review = saved; s.queries = [...saved.state.queries]; s.queriesDirty = false; update();
}

// 1. Stichworte: Suchanfragen prüfen, ändern, ergänzen – wie Suchstrings in Literaturdatenbanken
function step1(r, job) {
  const s = st();
  if (s.queries === null) s.queries = [...(r.state.queries || [])];
  const q = s.queries;
  const stats = Object.fromEntries((r.state.query_stats || []).map(x => [x.query, x]));
  const searched = (r.state.query_stats || []).length > 0;
  const confirmed = reachedOf(r) > 2;
  const dirty = () => { s.queriesDirty = true; };
  const ids = corpusIds(r);
  const nQueries = q.filter(x => x.trim()).length;
  const search = async () => {
    if (searched && !await confirmDialog(t('Suche wiederholen?'), t('Die Kandidatenliste wird neu erstellt; deine bisherigen Häkchen gehen verloren.'), { ok: t('Neu suchen') })) return;
    if (s.queriesDirty) await saveQueries(r);
    startJob(`/api/reviews/${r.id}/candidates`, t('Texte gefunden'), { nextTab: 2 });
  };
  const regenerate = async () => {
    if (q.length && !await confirmDialog(t('Neue Vorschläge?'), t('Die aktuellen Suchanfragen werden durch neue Vorschläge ersetzt.'), { ok: t('Ersetzen') })) return;
    s.queries = null;
    startJob(`/api/reviews/${r.id}/strategy`, t('Suchstrategie vorgeschlagen'));
  };
  const searchBtn = btn(searched ? t('Suche wiederholen') : t('Suche starten ({n} Anfragen)', { n: nQueries }), {
    kind: searched ? 'secondary' : 'primary', icon: 'search', disabled: !!job || !nQueries || !ids.length,
    why: !ids.length ? t('Mindestens einen Korpus wählen.') : t('Mindestens eine Suchanfrage.'), onClick: search });
  const actions = confirmed ? [nextBtn(2, t('Weiter: Literatur auswählen'))]
    : searched ? [searchBtn, nextBtn(2, t('Weiter: Literatur auswählen'))] : [searchBtn];
  const body = card(t('Suchstrategie'), 'search', h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Jede Zeile ist eine eigene Suche (Bedeutung + Stichworte) in den gewählten Korpora; AND/OR wirken hier nicht. Gut sind beide Sprachen, Synonyme, Fachbegriffe und Zielgruppen-Bezeichnungen – kurze Stichwortanfragen und ganze Sätze gemischt. Nach der Suche siehst du, wie viele Texte jede Anfrage gefunden hat und wie viele nur durch sie.')),
    field(t('Durchsuchte Korpora'), confirmed ? h('div', { class: 'chips' }, ids.map(id => h('span', { key: id, class: 'chip chip-accent' }, h('span', null, (state.corpora.find(c => c.id === id) || { name: t('Korpus {id}', { id }) }).name))))
      : multiSelect({ values: ids, options: corpusOptions(), label: t('Korpora'), placeholder: t('Korpora wählen …'),
        onChange: async v => { s.review = await run(() => api.put(`/api/reviews/${r.id}`, { filters: { corpus_ids: v } })); update(); } })),
    q.length ? h('div', { class: 'query-list' }, q.map((text, i) => {
      const x = stats[text];
      return h('div', { key: i, class: 'query-row' },
        h('span', { class: 'query-num' }, i + 1),
        textInput({ value: text, label: t('Suchanfrage {n}', { n: i + 1 }), disabled: confirmed, onInput: v => { q[i] = v; dirty(); }, onChange: () => update() }),
        x ? h('span', { class: ['query-stat', x.docs === 0 && 'zero'], title: t('{d} der vorgeschlagenen Texte gefunden, {u} davon nur durch diese Anfrage', { d: x.docs, u: x.unique }) },
          t('{n} Texte', { n: x.docs }), x.unique ? h('b', null, ` · ${t('{n} nur hier', { n: x.unique })}`) : null)
          : searched ? h('span', { class: 'query-stat new', title: t('Noch nicht gesucht') }, t('neu')) : null,
        !confirmed && iconBtn('x', t('Anfrage entfernen'), () => { q.splice(i, 1); dirty(); update(); }));
    })) : job ? null : h('p', { class: 'muted' }, t('Noch keine Suchanfragen.')),
    !confirmed && h('div', { class: 'row wrap' },
      btn(t('Anfrage hinzufügen'), { size: 'sm', kind: 'ghost', icon: 'plus', onClick: () => { q.push(''); dirty(); update();
        requestAnimationFrame(() => { const all = document.querySelectorAll('.query-row input'); all[all.length - 1]?.focus(); }); } }),
      btn(q.length ? t('Neu vorschlagen') : t('Suchstrategie vorschlagen'), { size: 'sm', kind: q.length ? 'ghost' : 'primary', icon: 'ai', disabled: !!job, onClick: regenerate }),
      h('div', { class: 'spacer' }),
      s.queriesDirty && btn(t('Änderungen speichern'), { size: 'sm', icon: 'check', onClick: () => saveQueries(r) }))));
  return { actions, body };
}

// 2. Literatur auswählen: gefundene Texte prüfen, Häkchen setzen, Auswahl bestätigen
function step2(r, job) {
  const s = st();
  const docs = r.docs || [];
  const included = docs.filter(d => d.included).length;
  const confirmed = reachedOf(r) > 2;
  const actions = confirmed ? [nextBtn(3, t('Weiter: Auswerten'))]
    : [btn(t('Auswahl bestätigen ({n} Texte)', { n: included }), { kind: 'primary', icon: 'check', disabled: !included || !!job, why: t('Mindestens einen Text auswählen.'),
      onClick: async () => { await run(() => api.post(`/api/reviews/${r.id}/confirm`)); st().tab = 3; openReview(r.id, { keepTab: true }); } })];
  if (!docs.length) return { actions, body: job ? null : notice('info', t('Noch keine Texte gefunden – in Schritt 1 die Suche starten.')) };
  const counts = { all: docs.length };
  for (const d of docs) counts[d.decision] = (counts[d.decision] || 0) + 1;
  counts.selected = included;
  const shown = docs.filter(d => s.filter === 'all' || (s.filter === 'selected' ? d.included : d.decision === s.filter));
  const decisions = DECISIONS();
  const toggleDoc = async (d, v) => {
    d.included = v; update();
    await run(() => api.post(`/api/reviews/${r.id}/docs`, { lib: d.lib, item_key: d.item_key, included: v }));
  };
  const body = card(t('Gefundene Texte ({n})', { n: docs.length }), 'file', h('div', { class: 'stack' },
    !confirmed && notice('info', h('span', null, h('b', null, t('{a} von {b} Texten ausgewählt.', { a: included, b: docs.length })), ' ',
      t('Prüfe die Auswahl: Häkchen setzen oder entfernen. Du kannst die Auswahl auch als Zotero-Sammlung anlegen, dort ergänzen und wieder übernehmen.'))),
    h('div', { class: 'row wrap' },
      segmented({ size: 'sm', value: s.filter, onChange: v => { s.filter = v; update(); }, options: [
        { value: 'all', label: t('Alle'), badge: counts.all }, { value: 'selected', label: t('Ausgewählt'), badge: counts.selected },
        { value: 'include', label: t('Vorgeschlagen'), badge: counts.include || 0 }, { value: 'maybe', label: t('Vielleicht'), badge: counts.maybe || 0 },
        { value: 'exclude', label: t('Ausgeschlossen'), badge: counts.exclude || 0 }] }),
      h('div', { class: 'spacer' }),
      btn(r.state.collection_key ? t('Sammlung aktualisieren') : t('Als Zotero-Sammlung'), { size: 'sm', icon: 'folder',
        onClick: async () => { const x = await run(() => api.post(`/api/reviews/${r.id}/collection/export`)); toast(t('{n} Texte in der Zotero-Sammlung „Zotivity – {title}“', { n: x.added, title: r.title }), 'success'); openReview(r.id, { keepTab: true }); } }),
      r.state.collection_key && btn(t('Aus Sammlung übernehmen'), { size: 'sm', icon: 'download',
        onClick: async () => { const x = await run(() => api.post(`/api/reviews/${r.id}/collection/import`)); toast(t('{a} Texte ausgewählt, davon {b} in Zotero ergänzt', { a: x.included, b: x.added }), 'success'); openReview(r.id, { keepTab: true }); } })),
    h('div', { class: 'doc-list' }, shown.length ? shown.map(d => {
      const [label, kind] = decisions[d.decision] || [d.decision, 'neutral'];
      return h('div', { key: d.lib + d.item_key, class: ['doc-row', d.included && 'selected'] },
        checkbox({ checked: !!d.included, onChange: v => toggleDoc(d, v), title: t('In den Forschungsstand aufnehmen') }),
        docTitle(d),
        h('div', { class: 'doc-meta' }, badge(label, kind), d.hits ? h('span', { class: 'muted small' }, plural(d.hits, t('Treffer'), t('Treffer'))) : null,
          d.reason && h('div', { class: 'muted small doc-reason' }, d.reason)));
    }) : h('p', { class: 'muted pad' }, t('Keine Texte in dieser Ansicht.')))));
  return { actions, body };
}

function tokenRange([lo, hi]) {
  const k = n => n >= 10000 ? `${fmtInt(Math.round(n / 1000))}k` : fmtInt(n);
  return lo === hi ? k(lo) : `${k(lo)}–${k(hi)}`;
}

// 3. Auswerten: ein Auswertungsblatt je Text
function step3(r, job) {
  const s = st();
  const docs = (r.docs || []).filter(d => d.included);
  const withSheet = docs.filter(d => d.has_sheet).length;
  if (s.estimate === null) {
    s.estimate = false;
    api.get(`/api/reviews/${r.id}/estimate`).then(e => { s.estimate = e; update(); }).catch(() => {});
  }
  const e = s.estimate;
  const cfg = state.settings && state.settings.review;
  const extracted = reachedOf(r) > 3;
  const money = v => fmtNum(v, 2);
  const extract = label => btn(label, { kind: extracted ? 'secondary' : 'primary', icon: 'play', disabled: !docs.length || !!job,
    onClick: () => startJob(`/api/reviews/${r.id}/extract`, t('Auswertungsblätter erstellt')) });
  const actions = !extracted ? [extract(t('Auswertungsblätter erstellen'))]
    : [withSheet < docs.length ? extract(t('Fehlende Blätter erstellen')) : null, nextBtn(4, t('Weiter: Schreiben'))];
  const body = h('div', { class: 'stack' },
    h('p', { class: 'muted' }, t('Jeder Text wird einzeln gelesen (bis zu einer bestimmten Länge ganz, sonst die zur Frage passenden Teile) und in einem Auswertungsblatt festgehalten: Fragestellung, Methode, Stichprobe, Befunde, Grenzen und wörtliche Kernzitate mit Seite.')),
    job ? null : h('div', { class: 'stats-row' },
      stat(t('Texte'), fmtInt(docs.length)), stat(t('mit Blatt'), fmtInt(withSheet)),
      e ? stat(t('neu zu erstellen'), fmtInt(e.missing_sheets)) : null,
      e && e.missing_sheets ? stat(t('Input-Token (gezählt)'), tokenRange([e.input_tokens, e.input_tokens])) : null,
      e && e.missing_sheets ? stat(t('Output-Token (geschätzt)'), tokenRange(e.output_tokens)) : null,
      e && e.missing_sheets && e.thinking_tokens[1] ? stat(t('Denk-Token (geschätzt)'), tokenRange(e.thinking_tokens)) : null,
      e && e.cost ? stat(t('Kosten (geschätzt)'), `${money(e.cost[0])}–${money(e.cost[1])} ${e.currency}`) : null),
    e && e.missing_sheets && !e.cost ? h('p', { class: 'muted small' }, t('Für eine Kostenschätzung den Preis von {m} unter Einstellungen › Sprachmodelle eintragen (pro 1 Mio. Tokens).', { m: e.model })) : null,
    e && e.missing_sheets ? h('p', { class: 'muted small' }, t('Output-Token: erfahrungsgemäss 800–1500 pro Blatt. Denk-Token hängen von der Denktiefe ab ({e}) und werden vom Anbieter wie Output-Token berechnet.', { e: e.effort || t('Modellstandard') })) : null,
    cfg && h('p', { class: 'muted small' }, t('Modell für die Blätter: {m} ({role}).', { m: e ? e.model : '', role: cfg.sheet_model === 'main' ? t('Hauptmodell') : t('Hilfsmodell') }), ' ',
      cfg.write_notes_to_zotero ? t('Jedes Blatt wird zusätzlich als Notiz (Schlagwort „{tag}“) am Zotero-Eintrag gespeichert – dafür braucht es den Schreibzugriff.', { tag: cfg.note_tag }) : t('Blätter werden nur in Zotivity gespeichert.')),
    withSheet ? h('p', { class: 'muted small' }, t('Ein Klick auf einen Text mit Häkchen zeigt sein Auswertungsblatt.')) : null,
    h('div', { class: 'doc-list' }, docs.map(d => sheetRow(r, d, job))));
  return { actions, body };
}

// Ein Text in „Auswerten“: mit Blatt aufklappbar
function sheetRow(r, d, job) {
  const s = st();
  const k = `${d.lib}:${d.item_key}`;
  const mark = h('span', { class: ['sheet-mark', d.has_sheet && 'ok'], title: d.has_sheet ? t('Auswertungsblatt vorhanden') : t('noch kein Blatt') }, icon(d.has_sheet ? 'check' : 'dot', 14));
  if (!d.has_sheet) return h('div', { key: k, class: 'doc-row' }, mark, docTitle(d));
  const open = !!s.sheetOpen[k];
  return h('div', { key: k, class: ['doc-row', 'sheet-row', open && 'open'] }, mark,
    h('div', { class: 'doc-text' },
      h('button', { type: 'button', class: 'sheet-toggle', 'aria-expanded': open ? 'true' : 'false', onclick: () => { s.sheetOpen[k] = !open; update(); } },
        icon(open ? 'chevronDown' : 'chevronRight', 14), h('span', { class: 'doc-title' }, d.title || d.item_key)),
      h('div', { class: 'muted small sheet-cite' }, d.citation),
      open && sheetView(r, d, job)));
}

const SHEET_FIELDS = () => [['textsorte', t('Textsorte')], ['fragestellung', t('Fragestellung')], ['theorie', t('Theorie')],
  ['methode', t('Methode')], ['stichprobe', t('Stichprobe')], ['land_kontext', t('Land/Kontext')], ['zeitraum', t('Zeitraum')],
  ['grenzen', t('Grenzen')]];

// Grundlage laut Dienst: „Volltext“ oder „Auszüge (n von m Abschnitten)“
function sheetBasis(b) {
  const m = /^Auszüge \((\d+) von (\d+)/.exec(b || '');
  return m ? t('Auszüge ({a} von {b} Abschnitten)', { a: m[1], b: m[2] }) : b === 'Volltext' ? t('ganzer Text') : b;
}

// Auswertungsblatt eines Textes; Kernzitate öffnen die PDF in Zotero an der Seite
function sheetView(r, d, job) {
  const s = st();
  const k = `${d.lib}:${d.item_key}`;
  if (!(k in s.sheets)) {
    s.sheets[k] = null;
    api.get(`/api/sheets?lib=${encodeURIComponent(d.lib)}&key=${encodeURIComponent(d.item_key)}`)
      .then(x => { s.sheets[k] = x; update(); }).catch(err => { s.sheets[k] = { error: err.message }; update(); });
  }
  const v = s.sheets[k];
  if (!v) return h('div', { class: 'pad' }, spinner(16));
  if (v.error) return notice('error', v.error);
  const x = v.sheet;
  const list = val => (Array.isArray(val) ? val : val ? [val] : []).map(String);
  const page = p => p === 'o. S.' ? t('o. S.') : t('S. {p}', { p });
  const rebuild = async () => {
    if (!await confirmDialog(t('Blatt neu erstellen?'), t('„{title}“ wird erneut gelesen und ausgewertet; das bisherige Blatt wird ersetzt. Ein bereits geschriebener Text bleibt unverändert.', { title: d.title || d.item_key }), { ok: t('Neu erstellen') })) return;
    startJob(`/api/reviews/${r.id}/sheets/rebuild`, t('Auswertungsblatt neu erstellt'), { body: { lib: d.lib, item_key: d.item_key } });
  };
  const findings = list(x.zentrale_befunde);
  const keywords = list(x.stichworte);
  return h('div', { class: 'sheet' },
    x.kurzbeschreibung ? h('p', { class: 'sheet-lead' }, String(x.kurzbeschreibung)) : null,
    h('dl', { class: 'sheet-fields' }, SHEET_FIELDS().filter(([f]) => list(x[f]).length).flatMap(([f, label]) => [
      h('dt', { key: `${f}-t` }, label), h('dd', { key: f }, list(x[f]).join('; '))])),
    findings.length ? h('div', { class: 'stack-sm' }, h('h4', null, t('Zentrale Befunde')),
      h('ul', { class: 'sheet-list' }, findings.map((b, i) => h('li', { key: i }, b)))) : null,
    v.quotes.length ? h('div', { class: 'stack-sm' }, h('h4', null, t('Kernzitate')),
      v.quotes.map((q, i) => h('blockquote', { key: i, class: 'sheet-quote' }, `„${q.zitat}“`,
        q.seite ? h('span', { class: 'sheet-page' }, q.url ? h('a', { href: q.url, title: t('PDF in Zotero öffnen') }, page(q.seite)) : page(q.seite)) : null))) : null,
    keywords.length ? h('div', { class: 'chips' }, keywords.map((w, i) => h('span', { key: i, class: 'chip sheet-chip' }, h('span', null, w)))) : null,
    h('div', { class: 'sheet-foot' },
      h('span', { class: 'muted small' }, [v.model && t('Erstellt mit {m}', { m: v.model }), fmtDate(v.created_at), v.basis && t('Grundlage: {b}', { b: sheetBasis(v.basis) })].filter(Boolean).join(' · ')),
      h('div', { class: 'sheet-actions' },
        btn(t('In Zotero zeigen'), { size: 'sm', kind: 'ghost', icon: 'zotero', onClick: () => api.openExternal(d.zotero_select) }),
        v.note_select ? btn(t('Notiz in Zotero zeigen'), { size: 'sm', kind: 'ghost', icon: 'file', onClick: () => api.openExternal(v.note_select) }) : null,
        btn(t('Blatt neu erstellen'), { size: 'sm', icon: 'refresh', disabled: !!job, why: t('Es läuft bereits ein Auftrag.'), onClick: rebuild }))));
}

function stat(label, value, title) {
  return h('div', { class: 'stat', title }, h('div', { class: 'stat-value' }, value), h('div', { class: 'stat-label' }, label));
}

function outlineEditor(r) {
  const s = st();
  if (!s.outline) s.outline = JSON.parse(JSON.stringify(r.state.outline));
  const o = s.outline;
  const docs = Object.fromEntries((r.docs || []).map(d => [d.item_key, d]));
  const dirty = () => { s.outlineDirty = true; update(); };
  const move = (i, d) => { const [x] = o.sections.splice(i, 1); o.sections.splice(i + d, 0, x); dirty(); };
  const total = o.sections.reduce((a, x) => a + (Number(x.words) || 0), 0);
  // Geschriebene Wörter je Abschnitt (nur solange die Gliederung nicht umgestellt ist)
  const written = s.outlineDirty ? [] : (r.state.sections || []).map(x => (x.text || '').split(/\s+/).filter(Boolean).length);
  return h('div', { class: 'stack' },
    field(t('Titel'), textInput({ value: o.title || '', onInput: v => { o.title = v; s.outlineDirty = true; }, onChange: () => update() })),
    h('div', { class: 'outline' }, o.sections.map((sec, i) => h('div', { key: i, class: 'outline-sec' },
      h('div', { class: 'outline-num' }, i + 1),
      h('div', { class: 'outline-body stack-sm' },
        textInput({ value: sec.heading, class: 'outline-heading', label: t('Überschrift'), onInput: v => { sec.heading = v; s.outlineDirty = true; }, onChange: () => update() }),
        textArea({ value: sec.focus || '', rows: 2, label: t('Fokus'), onInput: v => { sec.focus = v; s.outlineDirty = true; }, onChange: () => update() }),
        h('div', { class: 'row wrap' },
          h('div', { class: 'outline-words' }, numberInput({ value: sec.words, min: 50, max: 20000, step: 100, int: true, onChange: v => { sec.words = v; dirty(); } }), h('span', { class: 'muted small' }, t('Wörter')),
            written[i] != null && h('span', { class: ['small', written[i] > 1.2 * (Number(sec.words) || 0) ? 'text-warn' : 'muted'] }, t('· geschrieben: {n}', { n: fmtInt(written[i]) }))),
          (sec.keys || []).map(k => h('span', { key: k, class: 'chip', title: docs[k] ? docs[k].title : t('unbekannter Text') }, h('span', null, docs[k] ? docs[k].citation : k),
            h('button', { class: 'chip-x', title: t('Entfernen'), onclick: () => { sec.keys = sec.keys.filter(x => x !== k); dirty(); } }, icon('x', 11)))))),
      h('div', { class: 'outline-tools' },
        i < (r.state.sections || []).length && iconBtn('edit', t('Diesen Abschnitt neu schreiben'), () => rewriteSection(r, i), { disabled: s.outlineDirty || !!currentJob() }),
        iconBtn('chevronUp', t('Nach oben'), () => move(i, -1), { disabled: i === 0 }),
        iconBtn('chevronDown', t('Nach unten'), () => move(i, 1), { disabled: i === o.sections.length - 1 }),
        iconBtn('trash', t('Abschnitt entfernen'), () => { o.sections.splice(i, 1); dirty(); }))))),
    h('div', { class: 'row' },
      btn(t('Abschnitt hinzufügen'), { size: 'sm', kind: 'ghost', icon: 'plus', onClick: () => { o.sections.push({ heading: t('Neuer Abschnitt'), focus: '', keys: [], words: 500 }); dirty(); } }),
      h('span', { class: 'muted small' }, t('insgesamt ca. {n} Wörter', { n: fmtInt(total) })),
      h('div', { class: 'spacer' }),
      s.outlineDirty && btn(t('Verwerfen'), { size: 'sm', kind: 'ghost', onClick: () => { s.outline = null; s.outlineDirty = false; update(); } }),
      s.outlineDirty && btn(t('Gliederung speichern'), { size: 'sm', kind: 'primary', icon: 'check', onClick: async () => {
        await run(() => api.put(`/api/reviews/${r.id}/outline`, { outline: o }));
        s.outlineDirty = false; toast(t('Gliederung gespeichert'), 'success', 2000); openReview(r.id, { keepTab: true });
      } })));
}

// 4. Schreiben: Gliederung, dann die Abschnitte – der fertige Text erscheint unter „Prüfen“
function step4(r, job) {
  const s = st();
  const hasOutline = !!r.state.outline;
  const written = (r.state.sections || []).length;
  const outline = btn(hasOutline ? t('Gliederung neu erstellen') : t('Gliederung erstellen'), { kind: hasOutline ? 'ghost' : 'primary', icon: 'layers', disabled: !!job,
    onClick: async () => { if (hasOutline && !await confirmDialog(t('Gliederung neu erstellen?'), t('Die bisherige Gliederung und bereits geschriebene Abschnitte werden ersetzt.'), { ok: t('Neu erstellen') })) return; s.outline = null; startJob(`/api/reviews/${r.id}/outline`, t('Gliederung erstellt')); } });
  const write = hasOutline && btn(written ? t('Neu schreiben') : t('Abschnitte schreiben'), { kind: written ? 'secondary' : 'primary', icon: 'edit',
    disabled: s.outlineDirty || !!job, why: s.outlineDirty ? t('Zuerst die Gliederung speichern.') : t('Es läuft bereits ein Auftrag.'),
    onClick: () => startJob(`/api/reviews/${r.id}/write`, t('Forschungsstand geschrieben'), { nextTab: 5 }) });
  const actions = [outline, write, written ? nextBtn(5, t('Weiter: Prüfen')) : null];
  const body = h('div', { class: 'stack' },
    h('p', { class: 'muted' }, t('Aus allen Auswertungsblättern entsteht eine thematische Gliederung (nicht Text für Text). Du kannst sie anpassen, bevor die Abschnitte nacheinander geschrieben werden. Jede Aussage wird mit dem Text belegt, aus dem sie stammt. Der fertige Text erscheint unter „Prüfen“.')),
    hasOutline ? card(t('Gliederung'), 'layers', outlineEditor(r)) : null);
  return { actions, body };
}

// Text mit aufgelösten Belegen (Autor Jahr, S. x). Ein Klick auf einen Beleg öffnet eine kleine Auswahl:
// „In Zotero anzeigen“ oder „PDF in Zotero öffnen“ (an der zitierten bzw. automatisch gefundenen Seite).
function reviewText(r) {
  const s = st();
  const sig = `${r.id}:${r.updated_at}`;
  if (!s.text || s.text.sig !== sig) {
    s.text = { sig, markdown: null, citations: [] };
    api.get(`/api/reviews/${r.id}/text`).then(x => {
      if (st().text && st().text.sig === sig) { st().text.markdown = x.markdown; st().text.citations = x.citations || []; update(); }
    }).catch(err => { if (st().text && st().text.sig === sig) { st().text.markdown = ''; st().text.error = err.message; update(); } });
  }
  if (s.text.error) return notice('error', s.text.error);
  if (s.text.markdown === null) return h('div', { class: 'pad' }, spinner(16));
  return h('div', { class: 'prose review-prose', html: markdown(s.text.markdown),
    onclick: e => {
      const a = e.target.closest && e.target.closest('a[data-cite]');
      if (!a) return;
      e.preventDefault();
      const cite = s.text.citations[Number(a.dataset.cite)];
      if (cite) openCitePopover(a, cite);
    } });
}

// Hinweise der Prüfung – eingeklappt; die Zusammenfassung nennt, was es zu prüfen gibt
function checkWarnings(r, c, job) {
  const docs = Object.fromEntries((r.docs || []).map(d => [d.item_key, d]));
  const incomplete = c.incomplete_sections || [];
  const long = c.long_sections || [];
  const removed = c.removed_docs || [];
  const parts = [
    incomplete.length && plural(incomplete.length, t('unvollständiger Abschnitt'), t('unvollständige Abschnitte')),
    long.length && plural(long.length, t('zu langer Abschnitt'), t('zu lange Abschnitte')),
    c.unverified_quotes.length && plural(c.unverified_quotes.length, t('unklares Zitat'), t('unklare Zitate')),
    c.unknown_keys.length && plural(c.unknown_keys.length, t('unbekannter Beleg'), t('unbekannte Belege')),
    removed.length && plural(removed.length, t('Beleg auf gelöschten Text'), t('Belege auf gelöschte Texte')),
    c.uncited_docs.length && plural(c.uncited_docs.length, t('ausgewählter Text nicht zitiert'), t('ausgewählte Texte nicht zitiert')),
  ].filter(Boolean);
  if (!parts.length) return null;
  const body = () => h('div', { class: 'stack' },
    incompleteCard(r, job),
    longCard(r, job),
    c.unknown_keys.length ? notice('error', t('Belege auf Texte, die nicht zur Auswahl gehören: {keys}. Diese Stellen bitte prüfen.', { keys: c.unknown_keys.join(', ') })) : null,
    removed.length ? notice('warning', t('Belege auf Texte, die in Zotero gelöscht wurden und keine andere Kopie haben: {list}. Die Belege bleiben lesbar, verweisen aber auf keinen Eintrag mehr – Text in Zotero wiederherstellen oder die Stellen anpassen.',
      { list: removed.map(d => d.title ? `${d.citation} („${d.title}“)` : d.citation).join('; ') })) : null,
    c.unverified_quotes.length ? h('div', { class: 'stack-sm' }, h('b', null, t('Zitate, die nicht wörtlich im Text gefunden wurden')),
      c.unverified_quotes.map((q, i) => h('blockquote', { key: i, class: 'quote-check' }, `„${q.quote}“`,
        q.keys.length ? h('div', { class: 'muted small' }, q.keys.map(k => docs[k] ? docs[k].citation : k).join('; ')) : null)),
      h('p', { class: 'muted small' }, t('Oft sind es nur Silbentrennungen oder Auslassungen; trotzdem vor der Verwendung mit der PDF vergleichen.'))) : null,
    c.uncited_docs.length ? h('div', { class: 'stack-sm' }, h('b', null, t('{n} ausgewählte Texte werden im Text nicht zitiert', { n: c.uncited_docs.length })),
      h('ul', null, c.uncited_docs.map(u => h('li', { key: u.key }, docs[u.key] ? `${docs[u.key].citation}: ${docs[u.key].title}` : u.key)))) : null);
  return foldCard(`review-warnings-${r.id}`, t('Hinweise der Prüfung'), 'alert', parts.join(' · '), body, { class: 'card-warning' });
}

// 5. Prüfen: Belege und Zitate, der fertige Text, Ausgabe
function step5(r, job) {
  const c = r.state.check;
  const name = r.title || t('Forschungsstand');
  const actions = [
    btn(t('Erneut prüfen'), { kind: 'ghost', icon: 'refresh', disabled: !!job, onClick: async () => { await run(() => api.post(`/api/reviews/${r.id}/check`)); openReview(r.id, { keepTab: true }); } }),
    btn(t('Als Notiz in Zotero'), { icon: 'zotero', onClick: async () => { await run(() => api.post(`/api/reviews/${r.id}/save-to-zotero`)); toast(t('Als eigenständige Notiz in Zotero gespeichert'), 'success'); } }),
    btn(t('Kopieren'), { icon: 'copy', onClick: () => copyTarget({ kind: 'review', id: r.id }) }),
    btn(t('Exportieren …'), { kind: 'primary', icon: 'download', onClick: e => exportMenu(e, { kind: 'review', id: r.id }, name) }),
  ];
  const clean = c && !c.unverified_quotes.length && !c.unknown_keys.length && !(c.incomplete_sections || []).length && !(c.removed_docs || []).length && !(c.long_sections || []).length;
  const body = h('div', { class: 'stack' },
    c ? h('div', { class: 'stats-row' },
      stat(c.planned_words ? t('Wörter (geplant: {n})', { n: fmtInt(c.planned_words) }) : t('Wörter'), fmtInt(c.words),
        t('Text mit Überschriften und Belegen – ohne Literaturverzeichnis und Anhang „Methode der Literatursuche“')),
      stat(t('zitierte Texte'), t('{a} von {b}', { a: c.cited_docs, b: c.cited_docs + c.uncited_docs.length })),
      stat(t('Zitate geprüft'), fmtInt(c.verified_quotes)),
      stat(t('Zitate unklar'), fmtInt(c.unverified_quotes.length)), stat(t('unbekannte Belege'), fmtInt(c.unknown_keys.length)))
      : h('p', { class: 'muted' }, t('Noch nicht geprüft.')),
    clean ? notice('success', t('Alle wörtlichen Zitate wurden im Originaltext gefunden; alle Belege verweisen auf ausgewählte Texte.')) : null,
    c ? checkWarnings(r, c, job) : null,
    card(t('Text'), 'review', reviewText(r)),
    h('p', { class: 'muted small' }, t('Word: Belege und Literaturverzeichnis sind Zotero-Felder – mit dem Zotero-Plugin für Word weiter bearbeitbar. LaTeX: eine übersetzbare Datei mit eingebetteter Literaturdatenbank. Alle Formate enthalten am Ende die „Methode der Literatursuche“: durchsuchte Korpora, Suchanfragen und ihre Treffer.')));
  return { actions, body };
}

function titleEditor(r) {
  const s = st();
  if (s.editTitle === null) {
    return h('div', { class: 'review-title-row' }, h('h2', { title: r.title }, r.title),
      iconBtn('edit', t('Titel ändern'), () => { s.editTitle = r.title; update(); requestAnimationFrame(() => document.getElementById('review-title')?.focus()); }));
  }
  const saveTitle = async () => {
    const title = (s.editTitle || '').trim();
    if (!title) { toast(t('Bitte einen Titel eingeben.'), 'warning'); return; }
    s.review = await run(() => api.put(`/api/reviews/${r.id}`, { title }));
    s.editTitle = null; loadList(); update();
  };
  return h('div', { class: 'review-title-row' },
    textInput({ id: 'review-title', class: 'input-title', value: s.editTitle, onInput: v => { s.editTitle = v; },
      onKeyDown: e => { if (e.key === 'Enter') { s.editTitle = e.target.value; saveTitle(); } if (e.key === 'Escape') { s.editTitle = null; update(); } } }),
    btn(t('Speichern'), { size: 'sm', kind: 'primary', onClick: saveTitle }),
    btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', onClick: () => { s.editTitle = null; update(); } }));
}

function reviewDetail() {
  const s = st();
  const r = s.review;
  if (s.loading && !r) return h('div', { class: 'center-pad' }, spinner(20));
  if (!r) return null;
  const reached = reachedOf(r);
  const active = Math.min(s.tab || reached, reached);
  const job = currentJob() || (runningJob('review') && s.jobId == null ? runningJob('review') : null);
  const names = corpusIds(r).map(id => (state.corpora.find(c => c.id === id) || { name: t('gelöschter Korpus') }).name);
  if (job && !s.jobId) { s.jobId = job.id; watchJob(job.id).then(() => { s.jobId = null; openReview(r.id, { keepTab: true }); }); }
  const { actions, body } = [step1, step2, step3, step4, step5][active - 1](r, job);
  return h('div', { class: 'review-detail' },
    stepper(r, active),
    h('div', { class: 'review-bar' },
      h('button', { type: 'button', class: 'prompt-toggle', 'aria-expanded': s.promptOpen ? 'true' : 'false', title: s.promptOpen ? undefined : r.question,
        onclick: () => { s.promptOpen = !s.promptOpen; if (!s.promptOpen) s.editTitle = null; update(); } },
      icon(s.promptOpen ? 'chevronDown' : 'chevronRight', 14), h('b', null, t('Prompt')), !s.promptOpen && h('span', { class: 'prompt-peek' }, r.question)),
      h('div', { class: 'review-actions' }, actions)),
    s.promptOpen && h('div', { class: 'review-prompt' },
      titleEditor(r),
      h('p', { class: 'review-question' }, r.question),
      h('div', { class: 'row wrap small muted' }, icon('corpus', 14), names.length ? names.join(', ') : t('keine Korpora gewählt'), h('span', null, '·'),
        r.state.language ? languageName(r.state.language) : '', h('span', null, '·'), t('ca. {n} Wörter', { n: fmtInt(r.state.target_words) }))),
    job && jobBox(job),
    h('div', { class: 'review-step', key: active }, body));
}

export function reviewView() {
  const s = st();
  if (s.presetCorpus != null) { s.openId = 'new'; s.form = newForm(); }  // aus „Wissenskorpora“ → Forschungsstand
  if (s.openId === 'new' && !s.form) s.form = newForm();
  else if (s.openId && s.openId !== 'new' && (!s.review || s.review.id !== s.openId) && !s.loading) openReview(s.openId);
  const body = s.openId === 'new' ? newReviewForm()
    : s.openId ? reviewDetail()
      : emptyState('review', t('Forschungsstand erarbeiten'), t('Lege einen neuen Forschungsstand an oder öffne einen bestehenden aus der Liste.'),
        btn(t('Neuer Forschungsstand'), { kind: 'primary', icon: 'plus', onClick: () => openReview('new') }));
  const p = project();
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Forschungsstand'), p ? t('Projekt „{name}“ – Texte finden, einzeln auswerten, Synthese schreiben und prüfen', { name: p.name }) : t('Texte finden, einzeln auswerten, Synthese schreiben und prüfen')),
    h('div', { class: 'two-col' }, reviewList(), h('div', { class: 'col-main scroll' }, h('div', { class: 'col-inner' },
      coverageNotice(projectCorpora()), body))));
}

export { loadStatus };
