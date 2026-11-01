// Einstellungen: Sprachmodelle und Schlüssel, Embedding, Zotero, Sprache, Darstellung, Experteneinstellungen, Programm & Updates.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, openModal, closeModal, confirmDialog, saveSettings, loadSettings, loadPresets, loadKeys, loadStatus, loadSetup, watchJob, runningJob, providerLabel } from '../core/store.js';
import * as api from '../core/api.js';
import { t, LANGUAGES, OUTPUT_LANGUAGES, languageName } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, card, foldCard, notice, spinner, progress, field, textInput, select, segmented, toggle, numberInput, badge, combo, paneProps, splitter } from '../ui/components.js';
import { fmtInt, fmtAgo, fmtNum, fmtBytes } from '../core/util.js';
import { navigate, viewHeader } from './shell.js';
import { zoteroHelp, setupCard } from './setup.js';
import { loadInfo } from './research/common.js';
import { installedModelsCard, compareButton, builtinOptionsCard, adoptNotice, activateSpace } from './embedmodels.js';
import { autoCard, safetyCard, backupCard } from './indexing.js';
import { duplicatesSettingsCard } from './duplicates.js';

const TABS = [
  { id: 'setup', label: () => t('Einrichtung'), icon: 'check' },
  { id: 'models', label: () => t('Sprachmodelle'), icon: 'ai' },
  { id: 'embedding', label: () => t('Embedding'), icon: 'index' },
  { id: 'index', label: () => t('Index'), icon: 'layers' },
  { id: 'zotero', label: () => t('Zotero und Export'), icon: 'zotero' },
  { id: 'databases', label: () => t('Datenbanken'), icon: 'globe' },
  { id: 'language', label: () => t('Sprache'), icon: 'globe' },
  { id: 'appearance', label: () => t('Darstellung'), icon: 'sun' },
  { id: 'advanced', label: () => t('Experten'), icon: 'sliders' },
  { id: 'about', label: () => t('Programm & Daten'), icon: 'info' },
];
const EFFORTS = () => [
  { value: '', label: t('Standard des Modells') }, { value: 'low', label: t('niedrig (schnell, günstig)') }, { value: 'medium', label: t('mittel') },
  { value: 'high', label: t('hoch') }, { value: 'xhigh', label: t('sehr hoch') }, { value: 'max', label: t('maximal') },
];
// Zitierstile für Exporte: die in Zotero installierten (Ordner „styles“ des Zotero-Datenordners)
const STYLE_PREFIX = 'http://www.zotero.org/styles/';
const styleId = id => (!id ? STYLE_PREFIX + 'apa' : id.includes(':') ? id : STYLE_PREFIX + id);
const stylesState = () => ui('styles', { data: null, loading: false, error: null, analysis: null });

async function loadStyles(refresh = false) {
  const s = stylesState();
  if (s.loading) return;
  s.loading = true; update();
  try {
    s.data = await api.get(`/api/styles${refresh ? '?refresh=true' : ''}`);
    s.analysis = s.data.analysis; s.error = null;
  } catch (err) { s.error = err.message; }
  s.loading = false; update();
}

async function analyzeStyle(id) {
  const s = stylesState();
  try { s.analysis = await api.get(`/api/styles/analyze?id=${encodeURIComponent(id)}`); } catch { /* Vorschau fehlt */ }
  update();
}

function citationStyleCard() {
  const s = stylesState();
  if (!s.data && !s.loading && !s.error) loadStyles();
  const current = styleId(state.settings.citation_style);
  const styles = (s.data && s.data.styles) || [];
  const options = styles.map(x => ({ value: x.id, disabled: !x.supported,
    label: x.supported ? x.title : `${x.title} – ${t('Fussnotenstil, noch nicht unterstützt')}` }));
  if (!styles.find(x => x.id === current)) {
    options.unshift({ value: current, label: t('{id} (in Zotero nicht gefunden)', { id: current.replace(STYLE_PREFIX, '') }) });
  }
  const a = s.analysis;
  const noPage = state.settings.citation_no_page;
  return h('div', { class: 'stack' },
    field(t('Zitierstil für Exporte'), h('div', { class: 'row nowrap' },
      s.data ? select({ value: current, options, label: t('Zitierstil'), class: 'grow',
        onChange: async v => { await set('citation_style', v); analyzeStyle(v); } }) : spinner(16),
      iconBtn('refresh', t('Stile neu aus Zotero lesen'), () => loadStyles(true))),
    { help: s.error ? s.error : s.data && s.data.data_dir
      ? t('Die in Zotero installierten Stile (Datenordner {dir}). Neue Stile in Zotero unter Einstellungen → Zitieren installieren, dann hier aktualisieren.', { dir: s.data.data_dir })
      : t('Der Zotero-Datenordner wurde nicht gefunden – es stehen nur die Vorgaben zur Verfügung.') }),
    a && h('div', { class: 'style-preview' },
      h('div', { class: 'style-sample' }, h('span', { class: 'muted small' }, t('Beleg mit Seite')), h('code', null, a.preview.page)),
      h('div', { class: 'style-sample' }, h('span', { class: 'muted small' }, t('ohne Seitenzahl')), h('code', null, a.preview.no_page)),
      h('p', { class: 'muted small' }, !noPage ? t('Belege aus Quellen ohne Seitenzahlen bleiben ohne Kennzeichnung.')
        : a.mode === 'locator'
          ? t('Dieser Stil setzt keine Seitenbezeichnung vor die Zahl. „{x}“ kommt in Word als Seitenangabe in den Zotero-Beleg – das Trennzeichen setzt der Stil, auch bei „ebd.“.', { x: noPage })
          : t('Dieser Stil setzt „S.“ bzw. „p.“ vor die Seitenzahl. „{x}“ kommt in Word als Suffix in den Zotero-Beleg, mit dem Trennzeichen dieses Stils davor.', { x: noPage }))),
    field(t('Kennzeichnung ohne Seitenzahl'), textInput({ value: noPage, placeholder: t('leer = keine Kennzeichnung'),
      onChange: async v => { await set('citation_no_page', v.trim()); analyzeStyle(current); } }),
    { hint: t('Für Belege aus Quellen ohne gedruckte Seitenzahlen (Berichte, Webseiten …). Den Stil später besser hier wechseln und neu exportieren statt in Word: Die Kennzeichnung ist an den hier gewählten Stil angepasst.') }));
}

function st() {
  return ui('settings', { tab: 'setup', keyProvider: null, keyDraft: '', models: {}, modelsLoading: {}, tests: {}, testing: {},
    embModels: {}, embTesting: false, embTest: null, spaces: null, defaults: null, info: null, idxStats: null, update: null, checking: false });
}

const catalogOf = id => (state.catalog ? state.catalog.providers.find(p => p.id === id) : null) || { id, label: id, chat_models: [], embedding_models: [] };
const keyInfo = id => (state.keys && state.keys.keys[id]) || { stored: false };
const providerReady = id => { const p = catalogOf(id); return !p.needs_key || keyInfo(id).stored; };
const get = path => path.split('.').reduce((o, k) => (o == null ? o : o[k]), state.settings);
const patchOf = (path, value) => path.split('.').reduceRight((acc, k) => ({ [k]: acc }), value);
const set = (path, value) => saveSettings(patchOf(path, value));
const fmtGB = b => (b ? `${fmtNum(b / 1e9, 2)} GB` : '–');
// Kurzname eines Anbieters für Umschalter
const shortLabel = x => x.id === 'openai_compatible' ? t('Kompatibel') : x.id === 'sentence_transformers' ? 'Sentence-Transformers'
  : x.id === 'builtin' ? t('Eingebaut') : t(x.label).replace(' (ChatGPT)', '');

// ------------------------------------------------------------------ Aktionen, die auch die Startseite nutzt
export async function authorizeZotero() {
  let closed = false;
  openModal({
    title: t('Schreibzugriff freigeben'), sticky: true,
    body: () => h('div', { class: 'stack' },
      h('div', { class: 'row' }, spinner(18), h('b', null, t('Bitte in Zotero bestätigen …'))),
      h('p', null, t('Zotero fragt jetzt, ob Zotivity Notizen und Sammlungen anlegen darf. Bestätige dort mit „Erlauben“ – am besten mit „Entscheidung merken“, damit die Frage nicht jedes Mal kommt.')),
      notice('info', t('Kein Dialog zu sehen? Er kann hinter anderen Fenstern liegen. Zotivity versucht ihn nach vorne zu holen; sonst in der Taskleiste auf Zotero klicken.'))),
    actions: [{ label: t('Schliessen'), onClick: () => { closed = true; closeModal(); } }],
  });
  try {
    const r = await api.post('/api/zotero/authorize');
    if (!closed) closeModal();
    toast(r.authorized ? t('Schreibzugriff freigegeben.') : t('Zotero hat den Zugriff nicht erlaubt.'), r.authorized ? 'success' : 'warning');
  } catch (err) {
    if (!closed) closeModal();
    toast(err.kind === 'zotero_unavailable' ? t('Zotero ist nicht erreichbar – läuft Zotero und ist die lokale Schnittstelle aktiviert?') : err.message, 'error', 10000);
  }
  await Promise.all([loadStatus(), loadSetup()]);
}

export async function savePlugin() {
  const version = state.info ? state.info.version : '';
  const saved = await run(() => api.saveUrl(`zotivity-${version}.xpi`, '/plugin/zotivity.xpi'));
  if (!saved) return;
  openModal({
    title: t('Plugin in Zotero installieren'),
    body: () => h('div', { class: 'stack' },
      h('ol', { class: 'steps-list' },
        h('li', null, t('In Zotero „Werkzeuge → Plugins“ öffnen.')),
        h('li', null, t('Oben rechts auf das Zahnrad klicken und „Plugin aus Datei installieren …“ wählen.')),
        h('li', null, t('Die eben gespeicherte Datei auswählen:'), ' ', h('code', null, `zotivity-${version}.xpi`))),
      h('p', null, t('Danach gibt es in Zotero per Rechtsklick auf Sammlungen und Einträge das Menü „Zotivity“ (Indexieren, Fragen, Forschungsstand), und Zotivity startet mit Zotero.'))),
    actions: [{ label: t('Fertig'), kind: 'primary', onClick: () => { closeModal(); loadSetup(); } }],
  });
}

// ------------------------------------------------------------------ Sprachmodelle
function ensureModels(p) {
  const s = st();
  if (s.models[p] || s.modelsLoading[p] || !providerReady(p)) return;
  s.modelsLoading[p] = true;
  api.get(`/api/providers/${p}/models`).then(r => { s.models[p] = r; }).catch(() => { s.models[p] = { models: catalogOf(p).chat_models, loaded: false }; })
    .finally(() => { s.modelsLoading[p] = false; update(); });
}

function modelOptions(p) {
  const r = st().models[p];
  return r ? r.models : catalogOf(p).chat_models;
}

function keyCard() {
  const s = st();
  const providers = state.catalog.providers.filter(p => p.chat);
  const pid = s.keyProvider || state.settings.llm.provider;
  const p = catalogOf(pid);
  const k = keyInfo(pid);
  const backend = state.keys && state.keys.backend;
  const hasKeyField = p.needs_key || pid === 'openai_compatible';
  const saveKey = async () => {
    const value = s.keyDraft.trim();
    if (!value) return;
    const r = await run(() => api.put(`/api/keys/${pid}`, { key: value }));
    s.keyDraft = '';
    delete s.models[pid];
    await Promise.all([loadKeys(), state.settings && api.get('/api/settings').then(x => { state.settings = x; })]);
    loadStatus(); loadSetup();
    toast(r.switched ? t('Schlüssel gespeichert. Antworten kommen jetzt von {p} ({m}).', { p: r.switched.provider, m: r.switched.model }) : t('Schlüssel verschlüsselt gespeichert.'), 'success', 6000);
  };
  const baseUrls = state.settings.llm.base_urls || {};
  return card(t('Anbieter und API-Schlüssel'), 'key', h('div', { class: 'stack' },
    segmented({ value: pid, onChange: v => { s.keyProvider = v; s.keyDraft = ''; update(); }, options: providers.map(x => ({
      value: x.id, label: shortLabel(x), icon: x.needs_key ? (keyInfo(x.id).stored ? 'lock' : null) : 'monitor',
      title: x.needs_key ? (keyInfo(x.id).stored ? t('Schlüssel gespeichert') : t('kein Schlüssel')) : t('ohne Schlüssel') })), class: 'provider-seg' }),
    p.notes && h('p', { class: 'muted small' }, t(p.notes)),
    hasKeyField && field(t('API-Schlüssel'), h('div', { class: 'stack-sm' },
      k.stored && h('div', { class: 'key-status' }, icon('lock', 15), h('span', null, t('Gespeichert {mask}', { mask: k.masked || '' })),
        h('span', { class: 'muted small' }, k.source === 'env' ? t('(aus Umgebungsvariable)') : t('(verschlüsselt im Windows-Anmeldeinformationsspeicher)')),
        h('span', { class: 'spacer' }),
        k.source !== 'env' && iconBtn('trash', t('Schlüssel löschen'), async () => {
          if (!await confirmDialog(t('Schlüssel löschen?'), t('Der gespeicherte Schlüssel für {p} wird entfernt.', { p: t(p.label) }), { ok: t('Löschen'), danger: true })) return;
          await run(() => api.del(`/api/keys/${pid}`)); delete s.models[pid]; await loadKeys(); loadStatus(); loadSetup();
        })),
      h('div', { class: 'row' },
        h('div', { class: 'grow' }, textInput({ type: 'password', id: 'api-key-input', value: s.keyDraft, placeholder: k.stored ? t('Neuen Schlüssel eingeben, um ihn zu ersetzen') : t('Schlüssel einfügen'),
          label: t('API-Schlüssel'), onInput: v => { s.keyDraft = v; }, onKeyDown: e => { if (e.key === 'Enter') { s.keyDraft = e.target.value; saveKey(); } } })),
        btn(t('Speichern'), { kind: 'primary', icon: 'lock', onClick: () => { const el = document.getElementById('api-key-input'); if (el) s.keyDraft = el.value; saveKey(); } })),
      p.key_url && h('a', { href: p.key_url, class: 'small' }, icon('external', 13), ' ', t('Schlüssel bei {p} erstellen', { p: t(p.label) }))),
    { help: t('Der Schlüssel wird nie im Klartext angezeigt oder in Dateien geschrieben.') }),
    hasKeyField && backend && !backend.secure && notice('warning', t('Kein sicherer Schlüsselspeicher verfügbar ({b}).', { b: backend.backend }), null,
      { dismiss: `keystore:${backend.backend}`, session: true }),
    (pid === 'ollama' || pid === 'openai_compatible') && field(t('Server-Adresse'), textInput({ value: baseUrls[pid] || p.default_base_url, placeholder: p.default_base_url,
      onChange: v => saveSettings({ llm: { base_urls: { ...baseUrls, [pid]: v.trim() } } }) }),
    { hint: pid === 'ollama' ? t('Ollama muss installiert sein und laufen. Modelle mit „ollama pull <name>“ laden.') : t('Adresse mit /v1, z. B. LM Studio oder vLLM.') })));
}

function roleRow(role) {
  const s = st();
  const llm = state.settings.llm;
  const isMain = role === 'main';
  const pid = isMain ? llm.provider : llm.helper_provider;
  const model = isMain ? llm.model : llm.helper_model;
  const effort = isMain ? llm.effort : llm.helper_effort;
  const p = catalogOf(pid);
  ensureModels(pid);
  const r = s.models[pid];
  const test = s.tests[role];
  const chatProviders = state.catalog.providers.filter(x => x.chat);
  const setLLM = patch => { s.tests[role] = null; return saveSettings({ llm: patch }).then(() => { loadStatus(); loadSetup(); }); };
  const hints = {};
  if (p.default_main) hints[p.default_main] = isMain ? t('empfohlen') : '';
  if (p.default_helper) hints[p.default_helper] = isMain ? hints[p.default_helper] || '' : t('empfohlen');
  return h('div', { class: 'role' },
    h('div', { class: 'role-head' }, h('div', { class: 'role-title' }, icon(isMain ? 'ai' : 'layers', 16), isMain ? t('Hauptmodell') : t('Hilfsmodell')),
      h('div', { class: 'muted small' }, isMain ? t('Antworten, Gliederung und Text des Forschungsstands') : t('Suchanfragen, Vorauswahl der Texte – darf günstig und schnell sein'))),
    h('div', { class: 'role-grid' },
      field(t('Anbieter'), select({ value: pid, onChange: v => {
        const np = catalogOf(v);
        setLLM(isMain ? { provider: v, model: np.default_main || np.chat_models[0] || '' } : { helper_provider: v, helper_model: np.default_helper || np.default_main || np.chat_models[0] || '' });
      }, options: chatProviders.map(x => ({ value: x.id, label: t(x.label) + (providerReady(x.id) ? '' : ` – ${t('kein Schlüssel')}`) })) })),
      field(t('Modell'), h('div', { class: 'row nowrap' },
        h('div', { class: 'grow' }, combo({ value: model, options: modelOptions(pid), hints, openOnFocus: true, label: t('Modell'), placeholder: p.default_main,
          onChange: v => setLLM(isMain ? { model: v } : { helper_model: v }) })),
        s.modelsLoading[pid] ? spinner(14) : null),
      { hint: r ? (r.loaded ? t('{n} Modelle von {p} geladen', { n: r.models.length, p: t(p.label) }) : t('Vorschläge – mit gültigem Schlüssel wird die aktuelle Liste geladen')) : null }),
      field(t('Denktiefe'), select({ value: effort, options: EFFORTS(), onChange: v => setLLM(isMain ? { effort: v } : { helper_effort: v }) }),
        { help: t('Wie gründlich das Modell vor der Antwort „nachdenkt“ (Claude: effort, OpenAI/DeepSeek: reasoning, Gemini: thinking). Höher = besser bei schwierigen Fragen, aber langsamer und teurer.') })),
    priceRow(model),
    !providerReady(pid) && notice('warning', t('Für {p} ist kein API-Schlüssel gespeichert.', { p: t(p.label) }),
      h('div', { class: 'notice-actions' }, btn(t('Schlüssel eingeben'), { size: 'sm', onClick: () => { s.keyProvider = pid; update(); } })),
      { dismiss: `nokey:llm:${pid}`, session: true }),
    h('div', { class: 'row' },
      btn(t('Verbindung testen'), { size: 'sm', icon: 'play', busy: s.testing[role], disabled: !providerReady(pid), onClick: async () => {
        s.testing[role] = true; s.tests[role] = null; update();
        try { s.tests[role] = await api.post(`/api/providers/${pid}/test`, { model }); } catch (err) { s.tests[role] = { ok: false, error: err.message }; }
        s.testing[role] = false; update();
      } }),
      test && (test.ok ? h('span', { class: 'ok-text small' }, icon('check', 14), ' ', t('Antwort von {m}: „{r}“', { m: test.model, r: test.reply }))
        : h('span', { class: 'danger-text small' }, icon('alert', 14), ' ', test.error))));
}

// Selbst gepflegte Preise je Modell (für Kostenschätzungen im Forschungsstand)
function priceRow(model) {
  const llm = state.settings.llm;
  const prices = llm.prices || {};
  const [pin, pout] = prices[model] || [null, null];
  const setPrice = (i, v) => {
    const next = { ...prices };
    const cur = [...(next[model] || [null, null])];
    cur[i] = v;
    if (cur[0] == null && cur[1] == null) delete next[model]; else next[model] = [cur[0] ?? 0, cur[1] ?? 0];
    saveSettings({ llm: { prices: next } });
  };
  return h('div', { class: 'price-row' },
    h('span', { class: 'muted small' }, t('Preis von {m} pro 1 Mio. Tokens (optional, für Kostenschätzungen):', { m: model })),
    h('label', { class: 'price-field' }, h('span', { class: 'small' }, t('Input-Token')), numberInput({ value: pin, min: 0, max: 1000, step: 0.1, nullable: true, placeholder: '–', onChange: v => setPrice(0, v) })),
    h('label', { class: 'price-field' }, h('span', { class: 'small' }, t('Output-Token')), numberInput({ value: pout, min: 0, max: 1000, step: 0.5, nullable: true, placeholder: '–', onChange: v => setPrice(1, v) })),
    select({ value: llm.price_currency, class: 'currency', options: ['USD', 'EUR', 'CHF'], onChange: v => saveSettings({ llm: { price_currency: v } }) }));
}

function modelsTab() {
  return [keyCard(), card(t('Modelle'), 'ai', h('div', { class: 'stack' }, roleRow('main'), h('div', { class: 'divider' }), roleRow('helper'),
    h('p', { class: 'muted small' }, t('Tipp: Ein starkes Hauptmodell und ein günstiges Hilfsmodell desselben Anbieters sind meist die beste Kombination. Für die Auswertungsblätter lässt sich unter „Experten“ wählen, welches Modell sie schreibt.'))))];
}

// ------------------------------------------------------------------ Embedding
function loadEmbModels(p, force = false) {
  const s = st();
  if (!force && (s.embModels[p] || s.embModels[p] === false)) return;
  s.embModels[p] = false;
  api.get(`/api/embedding/models?provider=${encodeURIComponent(p)}`).then(r => { s.embModels[p] = r.models; update(); }).catch(() => { s.embModels[p] = []; update(); });
}

function ollamaInstalled(model, list) {
  if (!list) return null;
  const want = model.includes(':') ? model : `${model}:latest`;
  return list.includes(model) || list.includes(want);
}

// Zugeklappt: Anzahl, Platzbedarf und aktiver Index; aufgeklappt die Tabelle. „Modelle vergleichen …“ ab zwei Indizes.
function spacesCard() {
  const s = st();
  if (s.spaces === null) { s.spaces = false; api.get('/api/embedding/spaces').then(r => { s.spaces = r; update(); }).catch(() => {}); }
  if (!s.spaces || !s.spaces.spaces.length) return null;
  const list = s.spaces.spaces;
  const active = list.find(x => x.space === s.spaces.active);
  const bytes = list.reduce((a, x) => a + (x.index_bytes || 0), 0);
  const summary = [list.length === 1 ? t('1 Index') : t('{n} Indizes', { n: list.length }), t('Vektoren {s}', { s: fmtBytes(bytes) }),
    active ? t('aktiv: {m}', { m: active.label || active.model }) : t('für das aktive Modell noch keiner')].join(' · ');
  return foldCard('emb-spaces', t('Gespeicherte Indizes'), 'layers', summary, () => h('div', { class: 'stack-sm' },
    h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
      h('thead', null, h('tr', null, h('th', null, t('Modell')), h('th', { class: 'num' }, t('Modellgrösse')), h('th', { class: 'num' }, t('Dimensionen')),
        h('th', { class: 'num' }, t('Abschnitte')), h('th', { class: 'num' }, t('Vektoren')), h('th', null, t('angelegt')), h('th', { class: 'num' }))),
      h('tbody', null, s.spaces.spaces.map(x => h('tr', { key: x.space },
        h('td', null, h('b', null, x.model), h('span', { class: 'muted small' }, ` · ${providerLabel(x.provider)} `), x.space === s.spaces.active && badge(t('aktiv'), 'success')),
        h('td', { class: 'num', title: x.model_bytes ? t('Grösse der Modelldatei') : t('Nur für lokale Modelle bekannt (eingebaut oder Ollama)') }, fmtGB(x.model_bytes)),
        h('td', { class: 'num' }, fmtInt(x.dim)), h('td', { class: 'num' }, fmtInt(x.n)),
        h('td', { class: 'num', title: t('Speicherbedarf der Vektoren im Index') }, fmtBytes(x.index_bytes)),
        h('td', { class: 'muted small nowrap' }, fmtAgo(x.created_at)),
        h('td', { class: 'num nowrap' }, x.space !== s.spaces.active && x.n > 0 && btn(t('Verwenden'), { size: 'sm', kind: 'ghost',
          title: t('Dieses Modell wieder verwenden – sein Index ist sofort durchsuchbar'), onClick: () => activateSpace(x.space) }),
        x.space !== s.spaces.active && iconBtn('trash', t('Index löschen'), async () => {
          if (!await confirmDialog(t('Index löschen?'), t('Die {n} Vektoren von {m} werden gelöscht. Texte und Metadaten bleiben erhalten.', { n: fmtInt(x.n), m: x.model }), { ok: t('Löschen'), danger: true })) return;
          await run(() => api.del(`/api/embedding/spaces/${encodeURIComponent(x.space)}`)); s.spaces = null; ui('embmodels').spaces = null; update();
        }))))))),
    h('p', { class: 'muted small' }, t('Modellgrösse: Speicherbedarf des Embedding-Modells auf der Festplatte (eingebaute und Ollama-Modelle). Vektoren: Platzbedarf des Index für dieses Modell.'))),
  { actions: compareButton() });
}

// Während einer Indexierung: sagen, was ein Modellwechsel jetzt bewirkt (der Lauf endet sauber, nichts geht verloren)
function embeddingTab() {
  const cards = embeddingCards();
  if (!runningJob('index')) return cards;
  return [notice('info', t('Eine Indexierung läuft. Wechselst du jetzt das Embedding-Modell, endet sie nach dem laufenden Paket von Abschnitten. Bereits Verarbeitetes bleibt erhalten; wartende Läufe arbeiten mit dem neuen Modell.')), ...cards];
}

function embeddingCards() {
  const s = st();
  const e = state.settings.embedding;
  const p = catalogOf(e.provider);
  const providers = state.catalog.providers.filter(x => x.embeddings);
  if (e.provider === 'builtin') return builtinTab(providers);
  loadEmbModels(e.provider);
  const listed = s.embModels[e.provider] || [];
  const options = [...new Set([...p.embedding_models, ...listed.map(m => m.replace(/:latest$/, ''))])];
  const status = state.status && state.status.embedding;
  const pull = runningJob('pull');
  const installed = e.provider === 'ollama' ? ollamaInstalled(e.model, s.embModels.ollama || null) : null;
  const setEmb = patch => saveSettings({ embedding: patch }).then(() => { s.embTest = null; loadStatus(); loadSetup(); });
  const startPull = async () => {
    const job = await run(() => api.post('/api/ollama/pull', { model: e.model }));
    state.jobs[job.id] = job; update();
    const done = await watchJob(job.id);
    if (done.status === 'done') toast(t('{m} ist bereit.', { m: e.model }), 'success'); else if (done.status === 'error') toast(done.error, 'error', 10000);
    loadEmbModels('ollama', true); loadStatus(); loadSetup(); s.spaces = null;
  };
  return [
    card(t('Embedding-Modell'), 'index', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Das Embedding-Modell wandelt Textabschnitte in Vektoren um, damit nach Bedeutung gesucht werden kann – auch sprachübergreifend. Lokal (Ollama) bleiben alle Texte auf diesem Rechner.')),
      providerSwitch(providers),
      p.notes && h('p', { class: 'muted small' }, t(p.notes)),
      h('div', { class: 'grid-2' },
        field(t('Modell'), combo({ value: e.model, options, openOnFocus: true, label: t('Embedding-Modell'), onChange: v => setEmb({ model: v }) }),
          { hint: e.provider === 'ollama' ? t('Empfohlen: bge-m3 (mehrsprachig, 568 M Parameter, ca. 1,2 GB).') : null }),
        ['openai', 'gemini'].includes(e.provider) && field(t('Dimensionen'), numberInput({ value: e.dimensions, min: 64, max: 4096, step: 128, int: true, nullable: true, placeholder: t('Standard'),
          onChange: v => setEmb({ dimensions: v }) }), { help: t('Kürzere Vektoren sparen Speicher und sind etwas ungenauer. Leer = Standard des Modells.') }),
        ['ollama', 'openai_compatible'].includes(e.provider) && field(t('Server-Adresse'), textInput({ value: e.base_url || '', placeholder: p.default_base_url, onChange: v => setEmb({ base_url: v.trim() || null }) }))),
      e.provider === 'ollama' && state.status && !state.status.ollama && notice('warning', h('span', null, t('Ollama läuft nicht oder ist nicht installiert.'), ' ',
        h('a', { href: 'https://ollama.com/download' }, t('Ollama herunterladen')), ', ', t('installieren und starten – dann hier „Erneut prüfen“.')),
        h('div', { class: 'notice-actions' }, btn(t('Erneut prüfen'), { size: 'sm', icon: 'refresh', onClick: () => { loadEmbModels('ollama', true); loadStatus(); } })),
        { dismiss: 'ollama-missing', session: true }),
      e.provider === 'ollama' && installed === false && !pull && state.status && state.status.ollama && notice('info', t('{m} ist noch nicht heruntergeladen.', { m: e.model }),
        h('div', { class: 'notice-actions' }, btn(t('{m} herunterladen', { m: e.model }), { size: 'sm', kind: 'primary', icon: 'download', onClick: startPull }))),
      pull && h('div', { class: 'job-inline' }, h('div', { class: 'job-line' }, spinner(14), h('b', null, pull.title), h('span', { class: 'spacer' }),
        btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', onClick: () => api.post(`/api/jobs/${pull.id}/cancel`) })),
      progress(pull.done, pull.total, pull.total ? `${t('{a} von {b} MB', { a: fmtInt(Math.round(pull.done / 1e6)), b: fmtInt(Math.round(pull.total / 1e6)) })} · ${pull.message}` : pull.message)),
      ['openai', 'gemini'].includes(e.provider) && !providerReady(e.provider) && notice('warning', t('Für {p} ist kein API-Schlüssel gespeichert.', { p: t(p.label) }),
        h('div', { class: 'notice-actions' }, btn(t('Schlüssel eingeben'), { size: 'sm', onClick: () => { s.keyProvider = e.provider; s.tab = 'models'; update(); } })),
        { dismiss: `nokey:emb:${e.provider}`, session: true }),
      e.provider === 'ollama' && h('div', { class: 'grid-2' },
        field(t('CPU-Threads'), numberInput({ value: e.num_thread, min: 1, max: 256, int: true, nullable: true, placeholder: t('automatisch'), onChange: v => setEmb({ num_thread: v }) }),
          { help: t('Leer = Ollama entscheidet (meist Anzahl physischer Kerne).') }),
        field(t('Gerät'), segmented({ size: 'sm', value: e.device, onChange: v => setEmb({ device: v }), options: [
          { value: 'auto', label: t('Automatisch') }, { value: 'cpu', label: 'CPU' }, { value: 'gpu', label: t('Grafikkarte') }] }))),
      h('div', { class: 'row' },
        status && (status.ok ? h('span', { class: 'ok-text small' }, icon('check', 14), ' ', t('bereit · {n} Dimensionen', { n: status.dim })) : h('span', { class: 'danger-text small' }, icon('alert', 14), ' ', status.error)),
        h('span', { class: 'spacer' }),
        btn(t('Testen'), { size: 'sm', icon: 'play', busy: s.embTesting, onClick: async () => {
          s.embTesting = true; update();
          try { const r = await api.post('/api/embedding/test', {}); toast(t('Embedding funktioniert ({n} Dimensionen).', { n: r.dim }), 'success'); } catch (err) { toast(err.message, 'error', 10000); }
          s.embTesting = false; loadStatus();
        } })),
      notice('info', t('Jedes Modell hat einen eigenen Index. Nach einem Wechsel werden die Texte nicht neu gelesen, müssen aber für das neue Modell eingebettet werden (Zotivity bietet das gleich an). Der Index des bisherigen Modells bleibt erhalten; zurückwechseln geht sofort.')),
      adoptNotice())),
    spacesCard(),
  ];
}

// Anbieter-Umschalter (oben im Embedding-Reiter)
function providerSwitch(providers) {
  const e = state.settings.embedding;
  const setEmb = patch => saveSettings({ embedding: patch }).then(() => { st().embTest = null; loadStatus(); loadSetup(); });
  return segmented({ value: e.provider, onChange: v => {
    const np = catalogOf(v);
    // Eingebaut: zuletzt genutztes eingebautes Modell bzw. die Vorauswahl des Katalogs (bge-m3)
    setEmb({ provider: v, model: v === 'builtin' ? 'bge-m3' : np.embedding_models[0] || '', dimensions: null, query_prefix: null, document_prefix: null });
  }, options: providers.map(x => ({ value: x.id, label: shortLabel(x), icon: ['ollama', 'sentence_transformers', 'builtin'].includes(x.id) ? 'monitor' : 'globe' })) });
}

// Eingebaute Laufzeit: Modellkatalog statt Modellfeld
function builtinTab(providers) {
  const s = st();
  const e = state.settings.embedding;
  const status = state.status && state.status.embedding;
  const p = catalogOf('builtin');
  return [
    card(t('Embedding-Modell'), 'index', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Das Embedding-Modell wandelt Textabschnitte in Vektoren um, damit nach Bedeutung gesucht werden kann – auch sprachübergreifend. Lokal (Ollama) bleiben alle Texte auf diesem Rechner.')),
      providerSwitch(providers),
      p.notes && h('p', { class: 'muted small' }, t(p.notes)),
      h('div', { class: 'row' },
        status && (status.ok ? h('span', { class: 'ok-text small' }, icon('check', 14), ' ', t('{m} bereit · {n} Dimensionen', { m: e.model, n: status.dim }))
          : h('span', { class: 'warn-text small' }, icon('alert', 14), ' ', status.error)),
        h('span', { class: 'spacer' }),
        status && status.ok && btn(t('Testen'), { size: 'sm', icon: 'play', busy: s.embTesting, onClick: async () => {
          s.embTesting = true; update();
          try { const r = await api.post('/api/embedding/test', {}); toast(t('Embedding funktioniert ({n} Dimensionen).', { n: r.dim }), 'success'); } catch (err) { toast(err.message, 'error', 10000); }
          s.embTesting = false; loadStatus();
        } })),
      adoptNotice())),
    // Im Alltag: aktives Modell und installierte Modelle. Katalog und Namenssuche im Dialog „Modell hinzufügen“,
    // gespeicherte Indizes und Laufzeit zugeklappt, Vergleich als Dialog
    installedModelsCard(),
    spacesCard(),
    builtinOptionsCard(),
  ];
}

// ------------------------------------------------------------------ Zotero und Export
function zoteroTab() {
  const z = state.status && state.status.zotero;
  const r = state.settings.review;
  const pluginStep = state.setup && state.setup.steps.find(x => x.id === 'plugin');
  return [
    card(t('Verbindung'), 'zotero', h('div', { class: 'stack' },
      z ? h('div', { class: 'conn' },
        h('span', { class: ['dot', z.local_api ? 'ok' : z.running ? 'warn' : 'err'] }),
        h('div', null, h('b', null, z.local_api ? t('Verbunden mit Zotero {v}', { v: z.version || '' }) : z.running ? t('Zotero läuft, aber die lokale Schnittstelle ist aus') : t('Zotero ist nicht geöffnet')),
          z.message && !z.local_api && h('div', { class: 'muted small' }, z.message)),
        h('span', { class: 'spacer' }),
        !z.local_api && btn(t('Anleitung'), { size: 'sm', icon: 'help', onClick: zoteroHelp }),
        btn(t('Prüfen'), { size: 'sm', kind: 'ghost', icon: 'refresh', onClick: () => { loadStatus(); loadSetup(); } })) : spinner(16),
      field(t('Adresse der lokalen Zotero-Schnittstelle'), textInput({ value: state.settings.zotero.api_url, onChange: v => set('zotero.api_url', v.trim()).then(loadStatus) }),
        { hint: t('Standard: http://127.0.0.1:23119 – nur ändern, wenn Zotero anders eingerichtet ist.') }))),
    card(t('Schreibzugriff'), 'edit', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Nötig, damit Zotivity Auswertungsblätter als Notizen an Einträgen speichern und für den Forschungsstand Sammlungen anlegen kann. Lesen funktioniert ohne.')),
      h('div', { class: 'row' },
        z && z.write_access ? badge(t('freigegeben'), 'success') : badge(t('nicht freigegeben'), 'neutral'),
        z && z.write_access && z.write_session ? h('span', { class: 'muted small' }, t('für diese Sitzung – in Zotero „Entscheidung merken“ wählen, damit es dauerhaft gilt')) : null,
        h('span', { class: 'spacer' }),
        z && z.write_access ? btn(t('Freigabe entfernen'), { size: 'sm', kind: 'ghost', onClick: async () => { await run(() => api.del('/api/zotero/authorize')); loadStatus(); loadSetup(); } })
          : btn(t('Schreibzugriff freigeben'), { size: 'sm', kind: 'primary', disabled: !(z && z.local_api), why: t('Zotero ist nicht verbunden.'), onClick: authorizeZotero })),
      toggle({ checked: r.write_notes_to_zotero, label: t('Auswertungsblätter als Notiz am Zotero-Eintrag speichern'), onChange: v => set('review.write_notes_to_zotero', v) }),
      field(t('Schlagwort für diese Notizen'), textInput({ value: r.note_tag, onChange: v => set('review.note_tag', v.trim() || 'Zotivity-Auswertung') })))),
    card(t('Belege und Export'), 'quote', h('div', { class: 'stack' },
      field(t('Links der Belege in Exporten'), segmented({ value: r.link_target, onChange: v => set('review.link_target', v), options: [
        { value: 'pdf', label: t('PDF an der zitierten Seite'), icon: 'pdf' }, { value: 'item', label: t('Eintrag in Zotero'), icon: 'zotero' }] }),
      { hint: t('Gilt für den Forschungsstand als Markdown und als Notiz in Zotero. In Zotivity selbst öffnet ein Klick auf einen Beleg eine Auswahl (Eintrag oder PDF). Ohne PDF wird immer der Eintrag verlinkt.') }),
      citationStyleCard(),
      h('p', { class: 'muted small' }, t('Word: Belege und Literaturverzeichnis sind Zotero-Felder, die Zotero beim Aktualisieren im gewählten Stil formatiert. LaTeX: biblatex mit BibTeX-Daten aus Zotero.')))),
    card(t('Zotero-Plugin'), 'plug', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Das Plugin ergänzt Zotero um das Menü „Zotivity“ (Rechtsklick auf Sammlungen und Einträge) und startet Zotivity zusammen mit Zotero. Es ist optional.')),
      h('div', { class: 'row' },
        pluginStep && pluginStep.done ? badge(t('installiert'), 'success') : badge(t('nicht erkannt'), 'neutral'),
        h('span', { class: 'spacer' }), btn(t('Plugin speichern …'), { size: 'sm', icon: 'download', onClick: savePlugin })))),
    card(t('Zotero-Server (Web-API)'), 'globe', h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Optional und nur für die Recherche: Sie schreibt sonst über Zotero auf diesem Computer. Mit einem Schlüssel von zotero.org geht es auch, wenn Zotero hier nicht läuft; die Zotero-App übernimmt die Einträge beim nächsten Sync.')),
      researchKeyRows(k => k.id === 'zotero-web'))),
  ];
}

// ------------------------------------------------------------------ Schlüssel der Recherche
function researchKeys() {
  const s = st();
  if (s.rkeys === undefined) {
    s.rkeys = null;
    api.get('/api/research-keys').then(r => { s.rkeys = r; }).catch(err => { s.rkeys = { keys: [], error: err.message }; }).finally(update);
  }
  return s.rkeys;
}

async function researchKeysChanged() {
  st().rkeys = undefined;
  await Promise.all([loadInfo().catch(() => {}), loadSetup()]);
  update();
}

function researchKeyRows(which) {
  const s = st();
  const data = researchKeys();
  if (!data) return spinner(16);
  s.rdraft = s.rdraft || {};
  const inputId = id => `research-key-${id}`;
  const save = async k => {
    const el = document.getElementById(inputId(k.id));
    const key = (el ? el.value : s.rdraft[k.id] || '').trim();
    if (!key) return;
    await run(() => api.put(`/api/research-keys/${k.id}`, { key }));
    s.rdraft[k.id] = '';
    if (el) el.value = '';
    toast(t('Schlüssel gespeichert.'), 'success', 2000);
    await researchKeysChanged();
  };
  const remove = async k => {
    if (!await confirmDialog(t('Schlüssel löschen?'), t('Der gespeicherte Schlüssel für {p} wird entfernt.', { p: k.label }), { ok: t('Löschen'), danger: true })) return;
    await run(() => api.del(`/api/research-keys/${k.id}`));
    await researchKeysChanged();
  };
  return h('div', { class: 'stack' }, data.keys.filter(which).map(k => h('div', { key: k.id, class: 'stack-sm' },
    h('div', { class: 'row wrap' }, h('b', null, k.label),
      k.stored ? [icon('lock', 14), h('span', { class: 'muted small' }, k.source === 'env' ? t('aus Umgebungsvariable') : t('Gespeichert {mask}', { mask: k.masked || '' }))]
        : h('span', { class: 'muted small' }, t('kein Schlüssel')),
      h('span', { class: 'spacer' }),
      k.stored && k.source !== 'env' ? iconBtn('trash', t('Schlüssel löschen'), () => remove(k)) : null),
    h('div', { class: 'muted small' }, k.hint),
    h('div', { class: 'row' },
      h('div', { class: 'grow' }, textInput({ type: 'password', id: inputId(k.id), value: s.rdraft[k.id] || '', label: t('Schlüssel für {p}', { p: k.label }),
        placeholder: k.stored ? t('Neuen Schlüssel eingeben, um ihn zu ersetzen') : t('Schlüssel einfügen'),
        onInput: v => { s.rdraft[k.id] = v; }, onKeyDown: e => { if (e.key === 'Enter') save(k); } })),
      btn(t('Speichern'), { kind: 'primary', icon: 'lock', onClick: () => save(k) })),
    h('a', { href: k.url, class: 'small' }, icon('external', 13), ' ', t('Schlüssel bei {p} erstellen', { p: k.label })))));
}

function databasesTab() {
  return [card(t('Schlüssel für Datenbanken'), 'key', h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Die Recherche fragt offene Fachdatenbanken direkt ab. Manche verlangen einen eigenen Schlüssel oder arbeiten damit schneller. Die Schlüssel liegen verschlüsselt im Schlüsselspeicher des Betriebssystems und werden nie im Klartext angezeigt.')),
    researchKeyRows(k => k.id !== 'zotero-web')))];
}

function setupTab() {
  const s = state.setup;
  const first = !!(s && s.first_run);
  return [
    first ? h('p', null, t('Willkommen. Hier richtest du einmal ein, was Zotivity auf diesem Computer braucht. Jeder Schritt lässt sich überspringen und später hier nachholen.')) : null,
    setupCard(),
    h('div', { class: 'row wrap' }, h('p', { class: 'muted small grow' }, t('Einmal je Computer. Wie es danach weitergeht, zeigt die Anleitung.')),
      btn(t('Weiter: Anleitung'), { kind: first || (s && s.ready) ? 'primary' : 'secondary', icon: 'arrowRight', onClick: () => navigate('guide') }))];
}

// ------------------------------------------------------------------ Sprache
function languageTab() {
  const cur = state.settings.language;
  const out = state.settings.output_language;
  return [
    card(t('Sprache der Oberfläche'), 'globe', h('div', { class: 'stack' },
      h('div', { class: 'lang-grid' }, LANGUAGES.map(l => h('button', { key: l.code, type: 'button', class: ['lang-tile', l.code === cur && 'active'],
        onclick: () => saveSettings({ language: l.code }) }, h('span', { class: 'lang-code' }, l.code), h('span', null, l.label)))),
      h('p', { class: 'muted small' }, t('Gilt für Menüs, Meldungen und die Hilfe. Weitere Sprachen lassen sich ergänzen (Wörterbuch in static/js/i18n).')))),
    card(t('Sprache der KI-Ausgaben'), 'ai', h('div', { class: 'stack' },
      field(t('Antworten, Auswertungsblätter und Forschungsstand auf'), select({ value: out, onChange: v => saveSettings({ output_language: v }), options: [
        { value: 'auto', label: t('wie die Frage (automatisch)') },
        ...OUTPUT_LANGUAGES.map(c => ({ value: c, label: languageName(c) }))] })),
      h('p', { class: 'muted small' }, t('Wörtliche Zitate bleiben in der Originalsprache. Beim Forschungsstand lässt sich die Sprache zusätzlich je Vorhaben wählen.')))),
  ];
}

// ------------------------------------------------------------------ Darstellung
// Index: automatisch und in Etappen, Schutz für grosse Bibliotheken, Sicherung (Karten aus indexing.js)
function indexTab() {
  return [autoCard(), safetyCard(), duplicatesSettingsCard(), backupCard()];
}

function appearanceTab() {
  return [card(t('Erscheinungsbild'), 'sun', h('div', { class: 'stack' },
    segmented({ value: state.settings.appearance, onChange: v => saveSettings({ appearance: v }), options: [
      { value: 'system', label: t('System'), icon: 'monitor' }, { value: 'light', label: t('Hell'), icon: 'sun' },
      { value: 'gray', label: t('Grau'), icon: 'contrast' }, { value: 'dark', label: t('Dunkel'), icon: 'moon' }] }),
    h('p', { class: 'muted small' }, t('„System“ folgt der Einstellung von Windows. „Grau“ ist ein gedämpftes Dunkelgrau mit weniger Kontrast als „Dunkel“ – angenehm für lange Lesesitzungen.'))))];
}

// ------------------------------------------------------------------ Experteneinstellungen
const ADVANCED = () => [
  { id: 'retrieval', title: t('Suche'), icon: 'search', fields: [
    ['retrieval.top_k', t('Textstellen für die Antwort (top-k)'), 'int', { min: 1, max: 200, help: t('Wie viele Textstellen das Sprachmodell erhält. Mehr = vollständiger, aber langsamer und teurer.') }],
    ['retrieval.max_chunks_per_doc', t('Höchstens je Text'), 'int', { min: 1, max: 50, help: t('Verhindert, dass ein einzelnes Werk die Antwort dominiert.') }],
    ['retrieval.candidate_k', t('Kandidaten je Suchverfahren'), 'int', { min: 5, max: 2000, help: t('Treffer aus Bedeutungs- und Stichwortsuche vor der Zusammenführung.') }],
    ['retrieval.hybrid_weight', t('Gewicht der Bedeutungssuche'), 'float', { min: 0, max: 1, step: 0.05, help: t('1 = nur Bedeutungssuche (Embeddings), 0 = nur Stichwortsuche (BM25).') }],
    ['retrieval.rrf_k', t('RRF-Konstante'), 'int', { min: 1, max: 1000, help: t('Glättung bei der Zusammenführung der Ranglisten (Reciprocal Rank Fusion).') }],
    ['retrieval.mmr_lambda', t('Relevanz gegenüber Vielfalt (MMR)'), 'float', { min: 0, max: 1, step: 0.05, help: t('1 = nur Relevanz; kleiner = ähnliche Textstellen werden zugunsten von Vielfalt übersprungen.') }],
    ['retrieval.min_similarity', t('Mindest-Ähnlichkeit'), 'float', { min: -1, max: 1, step: 0.05, help: t('Treffer der Bedeutungssuche unter diesem Wert werden verworfen.') }],
    ['retrieval.neighbor_chunks', t('Nachbarabschnitte mitsenden'), 'int', { min: 0, max: 3, help: t('Gibt dem Modell mehr Zusammenhang um jede Textstelle.') }],
    ['retrieval.multi_query', t('Mehrfachsuche'), 'bool', { help: t('Das Hilfsmodell formuliert zusätzliche Suchanfragen (Deutsch/Englisch, Synonyme).') }],
    ['retrieval.n_queries', t('Anzahl zusätzlicher Suchanfragen'), 'int', { min: 1, max: 20 }],
    ['retrieval.research_rounds', t('Recherche-Runden'), 'int', { min: 0, max: 5, help: t('Das Modell prüft die Treffer auf Lücken und sucht gezielt nach.') }],
    ['retrieval.rerank', t('Neu sortieren'), 'select', { options: [['none', t('aus')], ['llm', t('mit dem Hilfsmodell')], ['cross_encoder', t('Cross-Encoder (lokal)')]] }],
    ['retrieval.rerank_candidates', t('Kandidaten für die Neusortierung'), 'int', { min: 5, max: 300 }],
    ['retrieval.context_token_budget', t('Kontext-Budget (Tokens)'), 'int', { min: 1000, max: 900000, step: 1000 }],
  ] },
  { id: 'llm', title: t('Sprachmodell'), icon: 'ai', fields: [
    ['llm.temperature', t('Temperatur'), 'float', { min: 0, max: 2, step: 0.1, nullable: true, help: t('Leer = Standard des Modells. Neuere Claude-Modelle akzeptieren keine Temperatur.') }],
    ['llm.max_output_tokens', t('Max. Output-Token'), 'int', { min: 256, max: 128000, step: 1000 }],
    ['llm.request_timeout', t('Zeitlimit je Anfrage (Sekunden)'), 'int', { min: 10, max: 3600, step: 30 }],
  ] },
  { id: 'review', title: t('Forschungsstand'), icon: 'review', fields: [
    ['review.n_queries', t('Suchanfragen'), 'int', { min: 3, max: 60 }],
    ['review.candidate_docs', t('Kandidaten (Texte)'), 'int', { min: 10, max: 1000 }],
    ['review.per_query_k', t('Treffer je Suchanfrage'), 'int', { min: 10, max: 2000 }],
    ['review.fulltext_token_limit', t('Volltext bis (Tokens)'), 'int', { min: 2000, max: 900000, step: 5000, help: t('Bis zu dieser Länge wird ein Text ganz gelesen, sonst die zur Frage passenden Teile.') }],
    ['review.relevant_chunks_if_long', t('Abschnitte bei langen Texten'), 'int', { min: 5, max: 500 }],
    ['review.sheet_model', t('Modell für Auswertungsblätter'), 'select', { options: [['main', t('Hauptmodell')], ['helper', t('Hilfsmodell')]] }],
    ['review.screening_model', t('Modell für die Vorauswahl'), 'select', { options: [['helper', t('Hilfsmodell')], ['main', t('Hauptmodell')]] }],
    ['review.target_words', t('Standard-Länge (Wörter)'), 'int', { min: 300, max: 40000, step: 500, help: t('Länge des Textes mit Überschriften und Belegen – Literaturverzeichnis und Anhang „Methode der Literatursuche“ kommen dazu.') }],
    ['review.parallel_requests', t('Parallele Anfragen'), 'int', { min: 1, max: 16 }],
  ] },
  { id: 'chunking', title: t('Zerlegung in Abschnitte'), icon: 'layers', note: t('Wirkt auf neu indexierte Texte. Für den ganzen Bestand müssten die Texte neu eingelesen werden.'), fields: [
    ['chunking.chunk_tokens', t('Abschnittslänge (Tokens)'), 'int', { min: 64, max: 4000, step: 50 }],
    ['chunking.overlap_tokens', t('Überlappung (Tokens)'), 'int', { min: 0, max: 1000, step: 10 }],
    ['chunking.min_chunk_tokens', t('Mindestlänge (Tokens)'), 'int', { min: 0, max: 500 }],
    ['chunking.metadata_header', t('Titel/Autor/Jahr vor jeden Abschnitt (nur fürs Embedding)'), 'bool'],
    ['chunking.index_abstracts', t('Abstracts als eigene Abschnitte'), 'bool'],
  ] },
  { id: 'indexing', title: t('Einlesen'), icon: 'index', fields: [
    ['indexing.ocr', t('Texterkennung (OCR) für Scans'), 'bool', { help: t('Benötigt eine Tesseract-Installation.') }],
    ['indexing.ocr_languages', t('OCR-Sprachen'), 'text', { help: t('Tesseract-Kürzel, z. B. deu+eng.') }],
    ['indexing.min_chars_per_page', t('Zeichen je Seite, ab denen Text vorhanden ist'), 'int', { min: 0, max: 5000 }],
    ['indexing.max_pages_per_document', t('Max. Seiten je Dokument'), 'int', { min: 1, max: 100000 }],
    ['indexing.use_zotero_fulltext_fallback', t('Volltext von Zotero nutzen, wenn kein Text extrahierbar ist'), 'bool'],
    ['indexing.throttle_seconds', t('Pause zwischen Dokumenten (Sekunden)'), 'float', { min: 0, max: 10, step: 0.5 }],
    ['embedding.batch_size', t('Abschnitte je Embedding-Anfrage'), 'int', { min: 1, max: 512 }],
    ['embedding.request_timeout', t('Zeitlimit Embedding (Sekunden)'), 'int', { min: 5, max: 3600, step: 10 }],
  ] },
  { id: 'server', title: t('Dienst'), icon: 'monitor', fields: [
    ['server.port', t('Port des lokalen Dienstes'), 'int', { min: 1024, max: 65535, help: t('Wirkt nach einem Neustart. Das Zotero-Plugin erwartet standardmässig 23120.') }],
    ['server.exit_after_zotero_closed_minutes', t('Dienst beenden, wenn Zotero so lange geschlossen ist (Minuten, 0 = nie)'), 'int', { min: 0, max: 1440 }],
  ] },
];

function fmtValue(v) {
  if (v === null || v === undefined || v === '') return t('leer');
  if (typeof v === 'boolean') return v ? t('an') : t('aus');
  return String(v);
}

function settingControl(path, type, o = {}) {
  const v = get(path);
  if (type === 'bool') return toggle({ checked: !!v, label: v ? t('an') : t('aus'), onChange: x => set(path, x) });
  if (type === 'select') return select({ value: v, options: o.options.map(([value, label]) => ({ value, label })), onChange: x => set(path, x) });
  if (type === 'text') return textInput({ value: v, onChange: x => set(path, x.trim()) });
  return numberInput({ value: v, min: o.min, max: o.max, step: o.step || 1, int: type === 'int', nullable: o.nullable, placeholder: o.nullable ? t('Standard') : '', onChange: x => set(path, x) });
}

// ------------------------------------------------------------------ Presets
const FIELD_LABELS = () => Object.fromEntries([
  ['retrieval.top_k', t('Textstellen (top-k)')], ['retrieval.max_chunks_per_doc', t('Höchstens je Text')], ['retrieval.candidate_k', t('Kandidaten je Suchverfahren')],
  ['retrieval.hybrid_weight', t('Gewicht Bedeutungssuche')], ['retrieval.rrf_k', t('RRF-Konstante')], ['retrieval.mmr_lambda', t('Relevanz vs. Vielfalt')],
  ['retrieval.min_similarity', t('Mindest-Ähnlichkeit')], ['retrieval.neighbor_chunks', t('Nachbarabschnitte')], ['retrieval.multi_query', t('Mehrfachsuche')],
  ['retrieval.n_queries', t('Suchanfragen')], ['retrieval.research_rounds', t('Recherche-Runden')], ['retrieval.rerank', t('Neu sortieren')],
  ['retrieval.rerank_candidates', t('Kandidaten Neusortierung')], ['retrieval.context_token_budget', t('Kontext-Budget')], ['llm.effort', t('Denktiefe')],
]);

function presetCard() {
  const p = state.presets;
  if (!p) return card(t('Presets'), 'sliders', spinner(16));
  const active = p.presets.find(x => x.id === p.active);
  const apply = async id => { state.presets = await run(() => api.post('/api/presets/apply', { id })); await loadSettings(); update(); };
  const saveAs = () => {
    const v = { label: '', description: '' };
    openModal({
      title: t('Aktuelle Werte als Preset speichern'),
      body: () => h('div', { class: 'stack' },
        field(t('Name'), textInput({ value: v.label, id: 'preset-name', placeholder: t('z. B. „Seminar Methoden“'), onInput: x => { v.label = x; } })),
        field(t('Beschreibung (optional)'), textInput({ value: v.description, onInput: x => { v.description = x; } })),
        h('p', { class: 'muted small' }, t('Gespeichert werden die Such- und Antwortwerte (Textstellen, Mehrfachsuche, Neusortierung, Denktiefe …) – keine Modelle oder Schlüssel.'))),
      actions: [{ label: t('Abbrechen'), onClick: closeModal }, { label: t('Speichern'), kind: 'primary', onClick: async () => {
        if (!v.label.trim()) { toast(t('Bitte einen Namen eingeben.'), 'warning'); return; }
        state.presets = await run(() => api.post('/api/presets', { label: v.label.trim(), description: v.description }));
        closeModal(); toast(t('Preset gespeichert.'), 'success'); update();
      } }],
    });
    requestAnimationFrame(() => document.getElementById('preset-name')?.focus());
  };
  const exportPreset = async x => {
    const data = JSON.stringify({ format: 'zotivity-preset', label: x.label, description: x.description, values: x.values }, null, 1);
    if (await api.saveText(`${x.label.replace(/[\\/:*?"<>|]+/g, ' ').trim()}.zoty-preset.json`, data, 'application/json')) toast(t('Preset gespeichert.'), 'success', 2500);
  };
  const importPreset = () => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.json,application/json';
    input.onchange = async () => {
      const f = input.files && input.files[0];
      if (!f) return;
      try {
        const d = JSON.parse(await f.text());
        if (!['zotivity-preset', 'zotllm-preset', 'zoterollm-preset'].includes(d.format) || !d.values) throw new Error(t('Keine Zotivity-Preset-Datei.'));
        state.presets = await api.post('/api/presets', { label: d.label || f.name, description: d.description || '', values: d.values, activate: false });
        toast(t('Preset „{name}“ importiert.', { name: d.label }), 'success'); update();
      } catch (err) { toast(t('Import fehlgeschlagen: {e}', { e: err.message }), 'error', 8000); }
    };
    input.click();
  };
  const fmt = v => typeof v === 'boolean' ? (v ? t('an') : t('aus')) : v === '' ? t('Standard') : String(v);
  const labels = FIELD_LABELS();
  return card(t('Presets'), 'sliders', h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Ein Preset setzt die Such- und Antwortwerte für einen Zweck auf einmal. Wählbar auch direkt in der Leiste über den Fragen.')),
    h('div', { class: 'preset-grid' }, p.presets.map(x => h('button', { key: x.id, type: 'button', class: ['preset-tile', x.id === p.active && 'active'],
      onclick: () => { if (x.id !== p.active || p.changed.length) apply(x.id); } },
    h('div', { class: 'preset-tile-head' }, h('b', null, x.builtin ? t(x.label) : x.label), x.id === p.active ? badge(p.changed.length ? t('aktiv · geändert') : t('aktiv'), p.changed.length ? 'warning' : 'accent') : null,
      !x.builtin ? badge(t('eigenes'), 'neutral') : null),
    h('div', { class: 'muted small' }, x.builtin ? t(x.description || '') : x.description || ''),
    h('div', { class: 'preset-tile-tools', onclick: e => e.stopPropagation() },
      iconBtn('download', t('Als Datei speichern'), () => exportPreset(x)),
      !x.builtin && iconBtn('trash', t('Löschen'), async () => {
        if (!await confirmDialog(t('Preset „{name}“ löschen?', { name: x.label }), t('Die Einstellungen selbst bleiben, wie sie sind.'), { ok: t('Löschen'), danger: true })) return;
        state.presets = await run(() => api.del(`/api/presets/${x.id}`)); update();
      }))))),
    p.changed.length ? notice('warning', h('span', null, t('Die aktuellen Werte weichen von „{name}“ ab:', { name: active ? t(active.label) : p.active }), ' ',
      p.changed.map((c, i) => h('span', { key: c.field }, i ? ', ' : '', h('b', null, labels[c.field] || c.field), ' ', t('{a} statt {b}', { a: fmt(c.current), b: fmt(c.preset) })))),
    h('div', { class: 'notice-actions' },
      btn(t('„{name}“ wiederherstellen', { name: active ? t(active.label) : '' }), { size: 'sm', onClick: () => apply(p.active) }),
      btn(t('Als neues Preset speichern …'), { size: 'sm', kind: 'primary', onClick: saveAs })),
    { dismiss: `preset:${p.active}:${p.changed.map(c => `${c.field}=${c.current}`).join(',')}` }) : null,
    h('div', { class: 'row' },
      btn(t('Aktuelle Werte als Preset speichern …'), { size: 'sm', icon: 'plus', onClick: saveAs }),
      btn(t('Preset importieren …'), { size: 'sm', kind: 'ghost', icon: 'download', onClick: importPreset }))));
}

function advancedTab() {
  const s = st();
  if (!s.defaults) { api.get('/api/settings/defaults').then(d => { s.defaults = d; update(); }).catch(() => {}); }
  if (!state.presets) loadPresets();
  const def = path => s.defaults ? path.split('.').reduce((o, k) => (o == null ? o : o[k]), s.defaults) : undefined;
  return [
    presetCard(),
    notice('info', t('Die einzelnen Werte sind für Feinabstimmung gedacht. Geänderte Werte sind markiert und lassen sich einzeln auf den Standard zurücksetzen.')),
    ...ADVANCED().map(group => {
      const changed = group.fields.filter(([path]) => s.defaults && JSON.stringify(get(path)) !== JSON.stringify(def(path)));
      return card(group.title, group.icon, h('div', { class: 'stack' },
        group.note && h('p', { class: 'muted small' }, group.note),
        h('div', { class: 'adv-grid' }, group.fields.map(([path, label, type, o = {}]) => {
          const isChanged = changed.some(c => c[0] === path);
          return h('div', { key: path, class: ['adv-field', isChanged && 'changed'] },
            field(label, settingControl(path, type, o), { help: o.help, hint: isChanged ? h('span', null, t('Standard: {v}', { v: fmtValue(def(path)) }), ' ',
              h('button', { type: 'button', class: 'link-btn', onclick: () => set(path, def(path)) }, t('zurücksetzen'))) : null }));
        }))),
      { key: group.id, actions: changed.length ? btn(t('{n} zurücksetzen', { n: changed.length }), { size: 'sm', kind: 'ghost', icon: 'refresh',
        onClick: () => saveSettings(changed.reduce((acc, [path]) => mergeDeep(acc, patchOf(path, def(path))), {})) }) : null });
    }),
  ];
}

function mergeDeep(a, b) {
  for (const [k, v] of Object.entries(b)) a[k] = v && typeof v === 'object' && !Array.isArray(v) ? mergeDeep(a[k] || {}, v) : v;
  return a;
}

// ------------------------------------------------------------------ Programm & Daten
async function checkUpdates(quiet = false) {
  const s = st();
  s.checking = true; update();
  try { s.update = await api.post('/api/update/check', {}); } catch (err) { s.update = null; if (!quiet) toast(err.message, 'error', 8000); }
  s.checking = false; update();
  return s.update;
}

export async function installUpdate(u) {
  const ok = await confirmDialog(t('Auf Version {v} aktualisieren?', { v: u.latest }),
    t('Zotivity lädt den Installer, beendet sich und startet nach der Installation neu. Einstellungen, Index, Korpora und gespeicherte Schlüssel bleiben erhalten.'), { ok: t('Jetzt aktualisieren') });
  if (!ok) return;
  toast(t('Update wird geladen …'), 'info', 0);
  const r = await run(() => api.post('/api/update/install', { installer: u.installer, sha256: u.sha256 }));
  if (r.started) toast(t('Der Installer läuft – Zotivity wird gleich neu gestartet.'), 'success', 0);
  else toast(t('Installer gespeichert: {p}', { p: r.path }), 'info', 0);
}

function aboutTab() {
  const s = st();
  if (!s.info) { s.info = {}; api.get('/api/app/info').then(i => { s.info = i; update(); }).catch(() => {}); }
  if (!s.idxStats) { s.idxStats = {}; api.get('/api/index/stats').then(i => { s.idxStats = i.stats; update(); }).catch(() => {}); }
  const i = s.info;
  const x = s.idxStats;
  const u = s.update;
  const folder = (label, path) => path ? h('div', { class: 'path-row', key: label },
    h('div', { class: 'path-label' }, label), h('code', { class: 'path' }, path),
    api.isDesktop() && iconBtn('folder', t('Im Explorer öffnen'), () => api.revealPath(path))) : null;
  return [
    card(t('Updates'), 'download', h('div', { class: 'stack' },
      h('div', { class: 'row' }, h('b', null, `Zotivity ${i.version || ''}`), h('span', { class: 'spacer' }),
        btn(t('Nach Updates suchen'), { size: 'sm', icon: 'refresh', busy: s.checking, disabled: !state.settings.update_url, why: t('Zuerst eine Update-Quelle angeben.'), onClick: () => checkUpdates() })),
      u && (!u.configured ? notice('info', t('Keine Update-Quelle eingetragen.'))
        : u.available ? notice('success', h('span', null, h('b', null, t('Version {v} ist verfügbar.', { v: u.latest })), u.notes ? h('div', { class: 'small' }, u.notes) : null),
          h('div', { class: 'notice-actions' }, btn(t('Jetzt aktualisieren'), { size: 'sm', kind: 'primary', icon: 'download', onClick: () => installUpdate(u) })))
          : notice('info', t('Zotivity ist aktuell ({v}).', { v: u.current }))),
      field(t('Update-Quelle'), textInput({ value: state.settings.update_url, placeholder: t('https://…/zotivity-update.json  oder  \\\\server\\freigabe\\zotivity-update.json'),
        onChange: v => set('update_url', v.trim()) }), { help: t('Adresse der Datei zotivity-update.json, die beim Erstellen des Installers entsteht (HTTPS oder Datei-/Netzwerkpfad).') }),
      toggle({ checked: state.settings.check_updates_on_start, label: t('Beim Start nach Updates suchen'), onChange: v => set('check_updates_on_start', v) }))),
    card(t('Index'), 'index', h('div', { class: 'stats-row' },
      stat(t('Einträge'), fmtInt(x.items)), stat(t('Dateien'), fmtInt(x.attachments)), stat(t('Abschnitte'), fmtInt(x.chunks)),
      stat(t('eingebettet'), fmtInt(x.embedded)), stat(t('Datenbank'), x.db_bytes ? fmtBytes(x.db_bytes) : '–'))),
    card(t('Speicherorte'), 'folder', h('div', { class: 'stack-sm' },
      folder(t('Daten (Index, Verläufe)'), i.data_dir), folder(t('Einstellungen'), i.config_dir), folder(t('Protokolle'), i.log_dir),
      i.keystore && h('div', { class: 'path-row' }, h('div', { class: 'path-label' }, t('Schlüsselspeicher')),
        h('span', null, i.keystore.backend, ' ', i.keystore.secure ? badge(t('verschlüsselt'), 'success') : badge(t('unsicher'), 'danger'))))),
    i.desktop && card(t('Programm beenden'), 'x', h('div', { class: 'row' },
      h('p', { class: 'muted small grow' }, t('Schliessen des Fensters beendet Zotivity. Mit dem Zotero-Plugin startet es beim nächsten Start von Zotero bzw. bei einem Befehl aus Zotero wieder unsichtbar im Hintergrund und endet einige Minuten nach Zotero.')),
      btn(t('Zotivity beenden'), { kind: 'danger', onClick: async () => {
        if (!await confirmDialog(t('Zotivity beenden?'), t('Laufende Indexierungen werden abgebrochen; bereits verarbeitete Texte bleiben im Index.'), { ok: t('Beenden'), danger: true })) return;
        await api.post('/api/shutdown').catch(() => {});
      } }))),
  ];
}

function stat(label, value) {
  return h('div', { class: 'stat' }, h('div', { class: 'stat-value' }, value ?? '–'), h('div', { class: 'stat-label' }, label));
}

// ------------------------------------------------------------------ Ansicht
export function settingsView() {
  const s = st();
  if (!state.settings || !state.catalog) return h('div', { class: 'center-pad' }, spinner(20));
  if (!state.keys) loadKeys().catch(() => {});
  const body = { setup: setupTab, databases: databasesTab, models: modelsTab, embedding: embeddingTab, index: indexTab, zotero: zoteroTab, language: languageTab, appearance: appearanceTab, advanced: advancedTab, about: aboutTab }[s.tab] || modelsTab;
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Einstellungen'), t('Sprachmodelle, Embedding, Index, Zotero, Sprache und Feinabstimmung')),
    h('div', { class: 'settings' },
      h('nav', { class: 'settings-nav', ...paneProps('settings', 230) }, TABS.map(tab => h('button', { key: tab.id, type: 'button', class: ['settings-tab', s.tab === tab.id && 'active'],
        onclick: () => { s.tab = tab.id; update(); } }, icon(tab.icon, 17), h('span', null, tab.label()),
      tab.id === 'models' && state.status && !state.status.llm.key ? h('span', { class: 'rail-dot', title: t('Kein Schlüssel') }) : null,
      tab.id === 'embedding' && state.status && !state.status.embedding.ok ? h('span', { class: 'rail-dot', title: t('Embedding nicht bereit') }) : null)),
      splitter('settings', { def: 230, min: 170, max: 420 })),
      h('div', { class: 'settings-body scroll' }, h('div', { class: ['settings-inner', s.tab === 'embedding' && 'wide'], key: s.tab }, body()))));
}

export { checkUpdates, providerLabel, navigate };
