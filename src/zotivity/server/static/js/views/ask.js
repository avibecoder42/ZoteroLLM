// Fragen an die Korpora des Projekts: Antwort mit anklickbaren Belegen, Textstellen eingeklappt darunter.
// Mehrere Korpora gleichzeitig wählbar; Antworten und Textstellen lassen sich kopieren und exportieren.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, confirmDialog, providerLabel, loadStatus, loadProjects, loadPresets, loadSettings, project, projectCorpora, run } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, segmented, notice, spinner, numberInput, toggle, field, emptyState, multiSelect, paneProps, splitter } from '../ui/components.js';
import { markdown } from '../core/markdown.js';
import { fmtAgo, fmtInt, fmtNum, nTexts, nIndexed } from '../core/util.js';
import { navigate, viewHeader, openSourcePopover } from './shell.js';
import { exportMenu, copyTarget } from './exports.js';
import { coverageNotice } from './embedmodels.js';

const examples = () => [
  t('Was schreiben meine Quellen über die Nutzung von Chatbots durch Jugendliche?'),
  t('Wo argumentiert jemand gegen den Einsatz von KI in der Sozialen Arbeit?'),
  t('Welche Methoden werden in den Studien verwendet, und mit welchen Stichproben?'),
];

function st() {
  // corpora: gewählte Korpora des Projekts (leer = alle); scope: Aufruf aus Zotero für Sammlung/Einträge
  return ui('ask', { chatId: null, messages: [], chats: null, chatsFor: null, busy: false, corpora: [], mode: 'answer', showOptions: false,
    overrides: {}, draft: '', stick: true, controller: null, openChat: null, scope: null });
}

async function loadChats() {
  const s = st();
  s.chatsFor = state.projectId;
  try { s.chats = (await api.get(`/api/chats?project=${state.projectId}`)).chats; } catch { s.chats = []; }
  update();
}

function selectedCorpora() {
  const all = projectCorpora().map(c => c.id);
  const chosen = st().corpora.filter(id => all.includes(id));
  return chosen.length ? chosen : all;
}

async function openChat(id) {
  const s = st();
  if (s.busy) return;
  const { messages } = await api.get(`/api/chats/${id}`);
  s.chatId = id;
  s.messages = messages.map(m => m.role === 'user' ? { role: 'user', content: m.content }
    : { id: m.id, role: 'assistant', content: m.content, sources: m.sources || [], queries: (m.meta || {}).queries || [],
      errors: (m.meta || {}).error ? [{ message: m.meta.error }] : [], warnings: [], meta: m.meta || {}, done: true });
  const last = messages.filter(m => m.role === 'user').pop();
  const f = last && last.meta && last.meta.filters;
  if (f && f.corpus_ids) s.corpora = f.corpus_ids;
  else if (f && f.corpus_id) s.corpora = [f.corpus_id];
  s.stick = true;
  update();
}

function newChat() {
  const s = st();
  if (s.busy) return;
  s.chatId = null; s.messages = []; s.draft = '';
  update();
  requestAnimationFrame(() => { const el = document.getElementById('ask-input'); if (el) el.focus(); });
}

async function send() {
  const s = st();
  const question = s.draft.trim();
  if (!question || s.busy) return;
  s.draft = '';
  const input = document.getElementById('ask-input');
  if (input) input.value = '';  // Feld hat den Fokus – direkt leeren
  s.busy = true;
  s.stick = true;
  s.messages.push({ role: 'user', content: question });
  const msg = { role: 'assistant', content: '', sources: [], queries: [], warnings: [], errors: [], status: t('Starte …'), meta: {}, done: false };
  s.messages.push(msg);
  update();
  const filters = s.scope ? s.scope.filters : { corpus_ids: selectedCorpora() };
  s.controller = new AbortController();
  try {
    await api.stream('/api/chat', { question, chat_id: s.chatId, filters, retrieval: s.overrides, search_only: s.mode === 'search',
      project_id: state.projectId }, ev => {
      switch (ev.type) {
        case 'chat': if (s.chatId !== ev.chat_id) loadProjects(); s.chatId = ev.chat_id; break;  // neuer Chat: Projektübersicht nachführen
        case 'status': msg.status = t(ev.text); break;
        case 'queries': msg.queries = ev.queries; msg.missing = ev.missing; break;
        case 'sources': msg.sources = ev.sources; break;
        case 'delta': msg.status = ''; msg.content += ev.text; break;
        case 'warning': msg.warnings.push(ev.text); break;
        case 'error': msg.status = ''; msg.errors.push({ message: ev.message, kind: ev.kind }); break;
        case 'done': msg.status = ''; msg.meta = { model: ev.model, usage: ev.usage }; msg.id = ev.message_id; break;
        default: break;
      }
      update();
    }, s.controller.signal);
  } catch (err) {
    msg.errors.push({ message: err.message });
  }
  msg.status = '';
  msg.done = true;
  s.busy = false;
  s.controller = null;
  update();
  loadChats();
  loadStatus();
  loadProjects();
}

function stop() {
  const s = st();
  if (s.controller) s.controller.abort();
}

// ------------------------------------------------------------------ Darstellung
function sourcesBlock(m) {
  if (!m.sources.length) return null;
  const docs = new Set(m.sources.map(x => x.item_key)).size;
  return h('details', { class: 'sources', key: 'src' },
    h('summary', null, icon('quote', 14), docs === 1 ? t('{n} Textstellen aus einem Dokument', { n: m.sources.length })
      : t('{n} Textstellen aus {d} Dokumenten', { n: m.sources.length, d: docs }),
      m.id ? h('span', { class: 'summary-actions', onclick: e => e.preventDefault() },
        iconBtn('copy', t('Textstellen kopieren'), e => { e.stopPropagation(); copyTarget({ kind: 'sources', id: m.id }); }),
        iconBtn('download', t('Textstellen exportieren …'), e => { e.stopPropagation(); exportMenu(e, { kind: 'sources', id: m.id }, t('Textstellen')); })) : null),
    h('div', { class: 'source-list' }, m.sources.map(x => h('div', { class: 'source', key: x.chunk_id, id: `src-${x.chunk_id}` },
      h('div', { class: 'source-head' }, h('span', { class: 'cite static' }, x.n),
        h('div', { class: 'source-title' }, h('b', null, x.citation), ' · ', x.title),
        h('span', { class: 'muted small' }, x.kind === 'abstract' ? 'Abstract' : x.page_label ? `${t('S.')} ${x.page_label}` : '')),
      h('div', { class: 'source-text' }, x.text),
      h('div', { class: 'source-links' },
        x.zotero_pdf && h('a', { href: x.zotero_pdf }, icon('pdf', 13), ' ', x.page_label ? t('PDF öffnen (S. {p})', { p: x.page_label }) : t('PDF öffnen')),
        h('a', { href: x.zotero_select }, icon('zotero', 13), ' ', t('In Zotero zeigen')),
        h('span', { class: 'spacer' }),
        relevanceMeter(x.relevance))))));
}

// Relevanz einer Textstelle: fünf Stufen, gemessen am besten Treffer der Frage (keine Wahrscheinlichkeit)
function relevanceMeter(r) {
  if (!r) return null;
  const num = v => fmtNum(v, 3);
  const label = t(r.label);
  const lines = [t('Relevanz: {l}', { l: label }), t('Rang {r} von {n}', { r: r.rank, n: r.of })];
  if (r.basis === 'rerank') lines.push(t('Bewertung der Neusortierung: {p} %', { p: Math.round(r.rerank * 100) }));
  if (r.vector != null) lines.push(t('Bedeutungsähnlichkeit {v}', { v: num(r.vector) }) + (r.best_vector != null ? ` (${t('bester Treffer {v}', { v: num(r.best_vector) })})` : ''));
  lines.push(r.keyword ? t('Stichworttreffer: ja') : t('Stichworttreffer: nein'));
  if (r.basis !== 'rerank') lines.push(t('Gemessen am besten Treffer dieser Frage – keine Wahrscheinlichkeit.'));
  return h('span', { class: ['relevance', `rel-${r.level}`], title: lines.join('\n') },
    h('span', { class: 'rel-bars', 'aria-hidden': 'true' }, [1, 2, 3, 4, 5].map(i => h('i', { key: i, class: i <= r.level ? 'on' : null }))),
    h('span', null, r.basis === 'rerank' ? `${Math.round(r.rerank * 100)} %` : label));
}

function errorBlock(e) {
  const setup = e.kind === 'setup' || e.kind === 'auth' || /API-Schlüssel|API key/.test(e.message);
  return notice('error', e.message, setup ? h('div', { class: 'notice-actions' },
    btn(t('Zu den Sprachmodellen'), { size: 'sm', kind: 'primary', onClick: () => { ui('settings', {}).tab = 'models'; navigate('settings'); } })) : null);
}

function assistantMessage(m, i) {
  const usage = m.meta && m.meta.usage;
  return h('div', { class: 'msg assistant', key: 'm' + i },
    m.queries && m.queries.length > 1 ? h('details', { class: 'queries' },
      h('summary', null, icon('search', 13), t('{n} Suchanfragen', { n: m.queries.length })),
      h('div', { class: 'query-chips' }, m.queries.map((q, j) => h('span', { key: j }, q))),
      m.missing && h('div', { class: 'muted small' }, t('Nachrecherche: '), m.missing)) : null,
    m.status && h('div', { class: 'statusline' }, spinner(13), h('span', null, m.status)),
    m.content && h('div', { class: 'answer-wrap' },
      h('div', { class: 'answer prose', html: markdown(m.content, { cites: true }),
        onclick: e => {
          const b = e.target.closest('.cite');
          if (!b) return;
          const src = m.sources.find(x => x.n === Number(b.dataset.n));
          if (src) openSourcePopover(b, src);
        } }),
      m.done && m.id ? h('div', { class: 'answer-tools' },
        iconBtn('copy', t('Antwort mit Quellen kopieren'), () => copyTarget({ kind: 'answer', id: m.id })),
        iconBtn('download', t('Antwort exportieren (Word, LaTeX, Markdown) …'), e => exportMenu(e, { kind: 'answer', id: m.id }, t('Antwort')))) : null),
    m.warnings.map((w, j) => h('div', { key: 'w' + j }, notice('warning', w, null, { dismiss: `chatwarn:${m.id || 'neu'}:${w}`, session: true }))),
    m.errors.map((e, j) => h('div', { key: 'e' + j }, errorBlock(e))),
    sourcesBlock(m),
    m.done && (m.meta.model || (usage && usage.requests)) ? h('div', { class: 'msg-meta' },
      m.meta.model && h('span', null, icon('ai', 12), ' ', m.meta.model),
      usage && usage.requests ? h('span', null, t('{a} Input-Token · {b} Output-Token', { a: fmtInt(usage.input_tokens), b: fmtInt(usage.output_tokens) })) : null) : null);
}

function chatList() {
  const s = st();
  if (s.chats === null || s.chatsFor !== state.projectId) { if (s.chatsFor !== state.projectId) { s.chats = null; loadChats(); } return h('aside', { class: 'side-list', ...paneProps('ask', 260) }, spinner(16)); }
  return h('aside', { class: 'side-list', ...paneProps('ask', 260) },
    btn(t('Neue Frage'), { kind: 'primary', icon: 'plus', onClick: newChat }),
    h('div', { class: 'side-items' }, s.chats.length ? s.chats.map(c => h('div', {
      key: c.id, class: ['side-item', c.id === s.chatId && 'active'], role: 'button', tabindex: 0, onclick: () => openChat(c.id),
    }, h('div', { class: 'side-item-text', title: c.title }, h('div', { class: 'side-item-title' }, c.title), h('div', { class: 'side-item-sub' }, fmtAgo(c.updated_at))),
    iconBtn('trash', t('Löschen'), async e => {
      e.stopPropagation();
      if (!await confirmDialog(t('Frage löschen?'), t('„{name}“ wird aus dem Verlauf entfernt.', { name: c.title }), { ok: t('Löschen'), danger: true })) return;
      await api.del(`/api/chats/${c.id}`);
      if (c.id === s.chatId) newChat();
      loadChats(); loadProjects();
    }))) : h('p', { class: 'muted small pad' }, t('Noch keine Fragen in diesem Projekt.'))),
    splitter('ask', { def: 260, max: 520 }));
}

// Preset-Umschalter: wendet die Such- und Antwortwerte für alle weiteren Fragen an
function presetSwitch() {
  const p = state.presets;
  if (!p) return null;
  const main = ['schnell', 'ausgewogen', 'gruendlich'];
  const byId = Object.fromEntries(p.presets.map(x => [x.id, x]));
  const ids = main.includes(p.active) || !byId[p.active] ? main : [...main, p.active];
  return h('div', { class: 'preset-switch', title: p.changed.length ? t('Werte gegenüber „{name}“ geändert ({n})', { name: t((byId[p.active] || {}).label || ''), n: p.changed.length }) : t('Such-Preset') },
    segmented({ size: 'sm', value: p.active, onChange: async id => {
      await run(() => api.post('/api/presets/apply', { id }));
      await Promise.all([loadPresets(), loadSettings()]);
      toast(`${t('Preset')} „${t(byId[id].label)}“: ${t(byId[id].description)}`, 'info', 4000);
    }, options: ids.filter(id => byId[id]).map(id => ({ value: id, label: t(byId[id].label), title: t(byId[id].description) })) }),
    p.changed.length ? h('span', { class: 'preset-changed', title: t('Werte weichen vom Preset ab – Einstellungen › Experten') }, '•') : null);
}

function toolbar() {
  const s = st();
  const corpora = projectCorpora();
  const status = state.status;
  const values = s.corpora.filter(id => corpora.some(c => c.id === id));
  return h('div', { class: 'ask-toolbar' },
    s.scope ? h('div', { class: 'ask-scope' }, icon('zotero', 16),
      h('span', { class: 'chip chip-accent', title: t('Aus Zotero gewählt') }, h('span', null, s.scope.label),
        h('button', { class: 'chip-x', title: t('Wieder die Korpora des Projekts'), onclick: () => { s.scope = null; update(); } }, icon('x', 11))))
      : h('div', { class: 'ask-scope' }, icon('corpus', 16),
        corpora.length ? multiSelect({ values, label: t('Wissenskorpora'), class: 'ask-corpora',
          placeholder: t('Alle Korpora des Projekts ({n})', { n: corpora.length }),
          options: corpora.map(c => ({ value: c.id, label: c.name, hint: nTexts(nIndexed(c.stats)) })),
          onChange: v => { s.corpora = v.length === corpora.length ? [] : v; update(); } })
          : h('span', { class: 'muted small' }, t('Projekt ohne Korpus'))),
    segmented({ size: 'sm', value: s.mode, onChange: v => { s.mode = v; update(); }, options: [
      { value: 'answer', label: t('Antwort'), icon: 'ai' }, { value: 'search', label: t('Nur Textstellen'), icon: 'quote' }] }),
    presetSwitch(),
    btn('', { icon: 'sliders', kind: s.showOptions ? 'secondary' : 'ghost', size: 'sm', title: t('Suchoptionen'), onClick: () => { s.showOptions = !s.showOptions; update(); } }),
    h('div', { class: 'spacer' }),
    status && h('button', { class: ['model-chip', !status.llm.key && 'warn'], title: t('Sprachmodell ändern'), onclick: () => { ui('settings', {}).tab = 'models'; navigate('settings'); } },
      icon(status.llm.key ? 'ai' : 'alert', 14), `${providerLabel(status.llm.provider)} · ${status.llm.model}`));
}

function optionsRow() {
  const s = st();
  if (!s.showOptions || !state.settings) return null;
  const r = state.settings.retrieval;
  const val = k => (s.overrides[k] ?? r[k]);
  const set = (k, v) => { if (v === r[k]) delete s.overrides[k]; else s.overrides[k] = v; update(); };
  return h('div', { class: 'ask-options' },
    field(t('Textstellen'), numberInput({ value: val('top_k'), min: 1, max: 100, int: true, onChange: v => set('top_k', v) }), { help: t('Wie viele Textstellen an das Sprachmodell gehen.') }),
    field(t('Max. pro Text'), numberInput({ value: val('max_chunks_per_doc'), min: 1, max: 20, int: true, onChange: v => set('max_chunks_per_doc', v) }), { help: t('Verhindert, dass ein einzelnes Werk alles dominiert.') }),
    field(t('Recherche-Runden'), numberInput({ value: val('research_rounds'), min: 0, max: 5, int: true, onChange: v => set('research_rounds', v) }), { help: t('Das Modell prüft die Treffer auf Lücken und sucht gezielt nach.') }),
    field(t('Mehrfachsuche'), toggle({ checked: val('multi_query'), label: val('multi_query') ? t('an') : t('aus'), onChange: v => set('multi_query', v) }), { help: t('Mehrere Suchanfragen auf Deutsch und Englisch mit Synonymen.') }),
    h('p', { class: 'muted small' }, t('Gilt nur für diese Sitzung und geht dem Preset vor. Dauerhafte Werte und eigene Presets: Einstellungen → Experten.')));
}

function composer() {
  const s = st();
  return h('div', { class: 'composer' },
    h('div', { class: 'composer-box' },
      h('textarea', { id: 'ask-input', class: 'composer-input', rows: 2, value: s.draft, placeholder: t('Frage stellen … (Enter sendet, Umschalt+Enter für neue Zeile)'),
        oninput: e => { s.draft = e.target.value; },
        onkeydown: e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); s.draft = e.target.value; send(); } } }),
      s.busy ? btn(t('Stopp'), { icon: 'stop', onClick: stop }) : btn(t('Senden'), { kind: 'primary', icon: 'send', onClick: () => { const el = document.getElementById('ask-input'); s.draft = el ? el.value : s.draft; send(); } })));
}

function conversation() {
  const s = st();
  const corpora = projectCorpora();
  const indexed = corpora.reduce((a, c) => a + (c.stats.embedded || 0), 0);
  // Deckt das aktive Embedding-Modell die Korpora nur teilweise ab (z. B. nach einem Modellwechsel)?
  const coverage = coverageNotice(corpora);
  const body = s.messages.length ? s.messages.map((m, i) => m.role === 'user'
    ? h('div', { class: 'msg user', key: 'm' + i }, h('div', { class: 'bubble' }, m.content))
    : assistantMessage(m, i))
    : h('div', { class: 'ask-empty' },
      emptyState('chat', t('Was möchtest du in deiner Bibliothek nachschlagen?'),
        t('Die Antwort stützt sich nur auf die indexierten Texte der gewählten Korpora dieses Projekts. Jeder Beleg führt zur Textstelle und öffnet auf Wunsch die PDF an der richtigen Seite.')),
      !corpora.length ? notice('info', t('Diesem Projekt ist noch kein Wissenskorpus zugeordnet. Lege fest, welche Sammlungen durchsucht werden sollen.'),
        h('div', { class: 'notice-actions' }, btn(t('Korpus anlegen oder hinzufügen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => navigate('corpora') })))
        : coverage && !indexed ? null
          : !indexed ? notice('warning', t('Die Korpora dieses Projekts sind noch nicht indexiert.'), h('div', { class: 'notice-actions' }, btn(t('Zur Indexierung'), { size: 'sm', onClick: () => navigate('index') })),
            { dismiss: `notindexed:${state.projectId}`, session: true })
            : h('div', { class: 'examples' }, examples().map(q => h('button', { key: q, class: 'example', onclick: () => { s.draft = q; update(); requestAnimationFrame(() => { const el = document.getElementById('ask-input'); if (el) el.focus(); }); } }, q))));
  return h('div', { class: 'conversation' },
    toolbar(), optionsRow(),
    coverage && h('div', { class: 'coverage-banner' }, coverage),
    h('div', { class: 'messages', onscroll: e => { const el = e.currentTarget; s.stick = el.scrollHeight - el.scrollTop - el.clientHeight < 60; },
      ref: el => { if (s.stick) el.scrollTop = el.scrollHeight; } }, h('div', { class: 'messages-inner' }, body)),
    composer());
}

export function askView() {
  const s = st();
  if (s.openChat) { const id = s.openChat; s.openChat = null; openChat(id); }
  const p = project();
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Fragen'), p ? t('Projekt „{name}“ – Antworten aus deinen Texten, mit Belegen bis auf die Seite', { name: p.name }) : t('Antworten aus deinen Texten – mit Belegen bis auf die Seite')),
    h('div', { class: 'ask' }, chatList(), conversation()));
}

export { toast };
