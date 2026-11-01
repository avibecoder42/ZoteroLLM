// Screening nach Titel und Abstract: eine Karte je Treffer, Tastatur J/K blättern, 1–9 Ordner, X ausschliessen,
// ? unsicher, G Grenzfall (Kennzeichen mit Begründung, bleibt beim Entscheid erhalten), Z rückgängig, A KI-Vorschlag
// übernehmen. Entscheidet wird von Menschen; jeder Entscheid landet mit Zeit im Verlauf. Eigene Warteschlangen für
// Grenzfälle, Ausgeblendete und offene Treffer nach KI-Vorschlag (Claude oder Gemini ordnet auf Wunsch stapelweise vor).
// Oben rechts: KI-Schalter (Vorschläge zeigen oder blind sichten – je Entscheid wird vermerkt, ob sie sichtbar waren)
// und die Ansicht „Karten“ (einzeln) oder „Liste“ (alle offenen auf einmal, screening_list.js).
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, openModal, closeModal } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt, debounce } from '../../core/util.js';
import { btn, card, field, segmented, select, checkbox, toggle, emptyState, progress, badge, notice, textInput, spinner, paneProps, splitter } from '../../ui/components.js';
import { R, rs, invalidate, needsLoad, refreshSummary, sourceBadges, folderLabel, statusBadge, borderlineText, aiInfo, aiBadge,
  AI_LABELS, fmtUsd, aiVisible, tokenText, costOf, addUsed, noteUsage } from './common.js';
import { listView, listSideCard } from './screening_list.js';
import { icon } from '../../ui/icons.js';

const savedView = () => { try { return localStorage.getItem('litsearch.screenView') === 'list' ? 'list' : 'cards'; } catch { return 'cards'; } };
const sc = () => ui('rs-screen', { status: 'open', index: 0, jumpTo: null, saving: false, view: savedView() });
const isList = () => sc().view === 'list';
const summaryLater = debounce(refreshSummary, 600);

function loadQueue() {
  const s = rs();
  const st = sc();
  if (!needsLoad('queue') || s.busy['loading:queue']) return s.queue;
  s.busy['loading:queue'] = true;
  api.get(`${R}/projects/${s.pid}/screening?status=${st.status}`).then(r => {
    s.queue = r;
    delete s.stale.queue;
    if (st.jumpTo != null) {
      const i = r.items.findIndex(it => it.id === st.jumpTo);
      st.index = i >= 0 ? i : Math.min(st.index, Math.max(0, r.items.length - 1));
      st.jumpTo = null;
    } else {
      st.index = Math.min(st.index, Math.max(0, r.items.length - 1));
    }
  }).catch(err => { s.queue = undefined; toast(err.message, 'error'); })
    .finally(() => { delete s.busy['loading:queue']; update(); });
  return s.queue;
}

const isDecided = it => !!(it.decision && it.decision.status !== 'open');
const openOnly = status => status === 'open' || status === 'borderline' || status.startsWith('ai_');

function setStatus(v) {
  const st = sc();
  st.status = v; st.index = 0;
  rs().queue = null;  // andere Auswahl: nicht die alte zeigen
  update();
}

// In der Liste: offene Treffer, offene Grenzfälle oder die als „unsicher“ markierten (Entschiedene: Karten)
const LIST_STATUSES = ['open', 'borderline', 'maybe'];

function setView(v) {
  const st = sc();
  st.view = v;
  try { localStorage.setItem('litsearch.screenView', v); } catch { /* privat */ }
  if (v === 'list' && !LIST_STATUSES.includes(st.status)) setStatus('open'); else update();
}

// KI-Schalter: gilt je Projekt (gespeichert), blendet Vorschläge im Screening und im Pool aus oder ein
async function setAiVisible(v) {
  const s = rs();
  const p = await run(() => api.put(`${R}/projects/${s.pid}`, { settings: { ai_visible: v } }));
  s.project.settings = p.settings;
  invalidate('pool');
  if (!v && sc().status.startsWith('ai_')) setStatus('open'); else update();
}

// Wer gerade entscheidet (Namen unter „Projekt“): steht beim Entscheid und im Protokoll
async function setReviewer(v) {
  const s = rs();
  const p = await run(() => api.put(`${R}/projects/${s.pid}`, { settings: { current_reviewer: v } }));
  s.project.settings = p.settings;
  update();
}

function current() {
  const q = rs().queue;
  return q && q.items.length ? q.items[sc().index] : null;
}

function go(delta) {
  const q = rs().queue;
  if (!q || !q.items.length) return;
  const st = sc();
  st.index = Math.max(0, Math.min(q.items.length - 1, st.index + delta));
  update();
  scrollCardTop();
}

function scrollCardTop() {
  requestAnimationFrame(() => { const el = document.querySelector('.rs-screen-card'); if (el) el.scrollTop = 0; });
}

// Nach einem Entscheid zum nächsten noch offenen Treffer (in „offen“) bzw. zum nächsten
function advance() {
  const q = rs().queue;
  const st = sc();
  let i = st.index + 1;
  if (openOnly(st.status)) while (i < q.items.length && isDecided(q.items[i])) i += 1;
  st.index = Math.min(i, q.items.length - 1);
  if (i >= q.items.length) toast(t('Ende der Liste erreicht.'), 'info', 2500);
  scrollCardTop();
}

async function decide(status, folder = null, reason = '') {
  const s = rs();
  const it = current();
  const st = sc();
  if (!it || st.saving) return;
  if (status === 'include' && !(s.project.folder_map || []).some(f => String(f.slot) === String(folder) && f.path)) {
    toast(t('Ordner {n} ist noch keiner Sammlung zugeordnet (Tab „Ordner“). Der Entscheid gilt trotzdem.', { n: folder }), 'warning', 5000);
  }
  st.saving = true;
  try {
    it.decision = await run(() => api.post(`${R}/projects/${s.pid}/decisions`, { record_id: it.id, status, folder, reason,
      ai_shown: aiVisible() && !!(it.ai && it.ai.label), method: 'card' }));
    invalidate('plan', 'pool', 'recall');
    advance();
    summaryLater();
  } finally {
    st.saving = false;
    update();
  }
}

async function undo() {
  const s = rs();
  const st = sc();
  const r = await run(() => api.post(`${R}/projects/${s.pid}/decisions/undo`));
  if (!r.undone) { toast(t('Nichts mehr rückgängig zu machen.'), 'info', 2500); return; }
  st.jumpTo = r.undone.record_id;
  invalidate('queue', 'plan', 'pool', 'recall');
  summaryLater();
  toast(r.undone.count > 1 ? t('Sammel-Übernahme zurückgenommen ({n} Entscheide).', { n: fmtInt(r.undone.count) }) : t('Letzter Entscheid zurückgenommen.'), 'info', 3000);
  update();
}

// G: Kennzeichen „Grenzfall“ setzen (mit Begründung) oder wieder entfernen
function borderlineDialog(prefill = '') {
  const s = rs();
  const it = current();
  if (!it) return;
  const human = (it.borderline || []).find(b => b.where === 'human');
  const d = { reason: human ? human.reason : prefill };
  const save = async on => {
    it.decision = await run(() => api.post(`${R}/projects/${s.pid}/borderline`, { record_id: it.id, on, reason: on ? d.reason.trim() : '' }));
    closeModal();
    it.borderline = (it.borderline || []).filter(b => b.where !== 'human');
    if (on) it.borderline.unshift({ where: 'human', reason: d.reason.trim(), strength: 3, label: t('von Hand') });
    invalidate('plan', 'pool', 'recall');
    summaryLater();
    update();
  };
  openModal({
    title: t('Grenzfall'),
    body: () => h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Liegt inhaltlich an der Grenze eines Kriteriums. Das Kennzeichen bleibt, auch wenn du danach in einen Ordner aufnimmst oder mit X ausschliesst, und erscheint im Protokoll.')),
      (it.borderline || []).filter(b => b.where !== 'human').map((b, i) => h('div', { key: i, class: 'warn-text small' }, borderlineText(b))),
      textInput({ value: d.reason, placeholder: t('Begründung, z. B. Grenze Spass/Cyberbullying'), onInput: v => { d.reason = v; },
        onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); save(true); } },
        ref: el => { if (el && !el.__focused) { el.__focused = true; setTimeout(() => el.focus(), 30); } } })),
    actions: () => [
      ...(human ? [{ label: t('Kennzeichen entfernen'), kind: 'danger', onClick: () => save(false) }] : []),
      { label: t('Abbrechen'), onClick: closeModal },
      { label: t('Als Grenzfall kennzeichnen'), kind: 'primary', icon: 'target', onClick: () => save(true) }],
  });
}

// A: KI-Vorschlag übernehmen – passend mit dem vorgeschlagenen Ordner, nicht passend mit dem Kriterium, Grenzfall als
// Kennzeichen (Begründung zum Bearbeiten vorbelegt). Der Vorschlag wird beim Entscheid mitgespeichert.
function acceptAi() {
  const it = current();
  const ai = aiVisible() && it && it.ai;
  if (!ai || !ai.label) return;
  if (ai.label === 'include') {
    if (ai.folder) decide('include', ai.folder);
    else toast(t('Die KI hat keinen Ordner vorgeschlagen – bitte einen Ordner wählen.'), 'info', 3500);
  } else if (ai.label === 'exclude') {
    const c = (ai.criterion || '').toLowerCase();
    const hit = c && (rs().queue.criteria_out || []).find(x => c.includes(x.toLowerCase()) || x.toLowerCase().includes(c));
    decide('exclude', null, hit || '');
  } else {
    borderlineDialog(ai.reason || '');
  }
}

export function screeningKey(e) {
  const tag = (e.target && e.target.tagName) || '';
  if (e.ctrlKey || e.metaKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || (e.target && e.target.isContentEditable)) return false;
  const k = e.key;
  if (isList()) {  // in der Liste nur „rückgängig“
    if (k !== 'z' && k !== 'Z') return false;
    undo();
    e.preventDefault();
    return true;
  }
  if (k === 'j' || k === 'J' || k === 'ArrowRight') go(1);
  else if (k === 'k' || k === 'K' || k === 'ArrowLeft') go(-1);
  else if (/^[1-9]$/.test(k)) {
    if ((rs().project.folder_map || []).some(f => Number(f.slot) === Number(k))) decide('include', Number(k));
    else toast(t('Ordner {n} gibt es nicht (Tab „Ordner“).', { n: k }), 'info', 2500);
  }
  else if (k === 'x' || k === 'X') decide('exclude');
  else if (k === '?' || k === 'ß') decide('maybe');
  else if (k === 'z' || k === 'Z') undo();
  else if (k === 'g' || k === 'G') borderlineDialog();
  else if (k === 'a' || k === 'A') acceptAi();
  else return false;
  e.preventDefault();
  return true;
}

function decisionPanel(it, queue) {
  const s = rs();
  const p = s.project;
  const d = it.decision;
  const slots = (p.folder_map || []).map(f => Number(f.slot)).sort((a, b) => a - b);
  const active = (status, folder) => d && d.status === status && (folder == null || String(d.folder) === String(folder));
  const ai = aiVisible() && it.ai && it.ai.label ? it.ai : null;
  const hint = (label, folder) => ai && ai.label === label && (folder == null || ai.folder === folder) && 'rs-key-suggested';
  const key = k => h('kbd', { class: 'rs-kbd' }, k);
  return h('div', { class: 'stack' },
    h('div', { class: 'rs-keys' },
      slots.length ? null : h('div', { class: 'muted small' }, t('Noch keine Ordner – im Tab „Ordner“ anlegen.')),
      slots.map(n => h('button', { key: n, type: 'button', class: ['rs-key', 'rs-key-in', active('include', n) && 'active',
        !(p.folder_map || []).some(f => Number(f.slot) === n && f.path) && 'rs-key-unset', hint('include', n)], onclick: () => decide('include', n),
        title: n > 9 ? t('Ordner {n} (ohne Kürzel)', { n }) : undefined },
      n <= 9 ? key(String(n)) : h('span', { class: 'rs-kbd rs-kbd-none' }, String(n)), h('span', null, folderLabel(p, n)))),
      h('button', { type: 'button', class: ['rs-key', 'rs-key-maybe', active('maybe') && 'active'], onclick: () => decide('maybe') }, key('?'), h('span', null, t('unsicher'))),
      h('button', { type: 'button', class: ['rs-key', 'rs-key-out', active('exclude') && 'active', hint('exclude')], onclick: () => decide('exclude') }, key('X'), h('span', null, t('ausschliessen'))),
      h('button', { type: 'button', class: ['rs-key', 'rs-key-border', (it.borderline || []).some(b => b.where === 'human') && 'active', hint('borderline')],
        onclick: () => borderlineDialog() },
        key('G'), h('span', null, t('Grenzfall …')))),
    queue.criteria_out.length ? h('div', { class: 'stack-sm' }, h('div', { class: 'muted small' }, t('Ausschliessen mit Grund:')),
      h('div', { class: 'chips' }, queue.criteria_out.map(r => h('button', { type: 'button', key: r,
        class: ['chip', d && d.status === 'exclude' && d.reason === r && 'chip-accent'], title: r, onclick: () => decide('exclude', null, r) }, h('span', null, r))))) : null,
    h('div', { class: 'row wrap small muted' }, key('J'), t('weiter'), key('K'), t('zurück'), key('G'), t('Grenzfall'), key('Z'), t('rückgängig'),
      ai ? [key('A'), t('KI-Vorschlag übernehmen')] : null));
}

function aiBox(it, p) {
  const ai = it.ai;
  if (!aiVisible() || !ai || !ai.label) return null;
  return h('div', { class: ['rs-ai', `rs-ai-${ai.label}`] },
    h('div', { class: 'row wrap' }, aiBadge(ai, p),
      ai.criterion ? h('span', { class: 'muted small rs-clamp1', title: ai.criterion }, ai.criterion) : null,
      h('span', { class: 'spacer' }),
      !isDecided(it) && btn(t('Übernehmen (A)'), { size: 'sm', kind: 'ghost', onClick: acceptAi })),
    ai.reason ? h('div', { class: 'small' }, ai.reason) : null,
    h('div', { class: 'muted small' }, t('Vorschlag von {m} – entscheiden tust du.', { m: ai.model || 'KI' })));
}

function recordCard(it, queue) {
  const p = rs().project;
  const st = sc();
  const authors = (it.authors || []).map(a => (Array.isArray(a) ? [a[0], a[1]].filter(Boolean).join(', ') : a));
  return h('article', { class: 'card rs-screen-card', key: it.id },
    h('div', { class: 'row small muted' },
      h('span', null, t('{i} von {n}', { i: fmtInt(st.index + 1), n: fmtInt(queue.items.length) })),
      h('span', { class: 'spacer' }), statusBadge(it.decision, p),
      it.zotero_key ? badge(t('schon in Zotero'), 'info') : null),
    aiBox(it, p),
    (it.borderline || []).some(b => b.where !== 'ai') ? h('div', { class: 'rs-borderline' },
      it.borderline.filter(b => b.where !== 'ai').map((b, i) => h('div', { key: i }, borderlineText(b)))) : null,
    it.hidden_by && it.hidden_by.length ? notice('warning', t('Durch einen Vorfilter ausgeblendet – hier zum Prüfen. Zurückholen geht im Pool unter „Ausgeblendete prüfen“; ein Entscheid hier gilt trotzdem.')) : null,
    h('h2', { class: 'rs-screen-title' }, it.title || t('(ohne Titel)')),
    h('div', { class: 'rs-screen-meta' },
      h('div', null, authors.slice(0, 8).join('; ') + (authors.length > 8 ? ` … (+${authors.length - 8})` : '')),
      h('div', null, h('b', null, it.journal || t('Zeitschrift unbekannt')), it.year ? ` · ${it.year}` : '', it.lang ? ` · ${it.lang}` : '',
        it.type && it.type !== 'journalArticle' ? ` · ${it.type}` : '')),
    it.no_abstract ? notice('warning', h('div', null, h('b', null, t('Nur Titel. ')),
      t('Kein Abstract gefunden – im Pool lassen sich fehlende Abstracts nachladen (Crossref, PubMed, Semantic Scholar). Im Zweifel: G oder ?.'),
      it.abstract ? h('p', { class: 'rs-abstract small' }, it.abstract) : null))
      : h('div', { class: 'rs-abstract rs-screen-abstract' }, it.abstract,
        it.abstract_source ? h('div', { class: 'muted small' }, t('Abstract aus {s}', { s: it.abstract_source })) : null),
    it.subjects && it.subjects.length ? h('div', { class: 'muted small' }, t('Schlagwörter: {s}', { s: it.subjects.slice(0, 15).join('; ') })) : null,
    h('div', { class: 'row wrap small' }, sourceBadges(it.sources), h('span', { class: 'muted' }, it.queries.join(', ')),
      h('span', { class: 'spacer' }),
      it.doi && h('a', { href: `https://doi.org/${it.doi}`, target: '_blank', rel: 'noopener' }, 'DOI'),
      it.pmid && h('a', { href: `https://pubmed.ncbi.nlm.nih.gov/${it.pmid}/`, target: '_blank', rel: 'noopener' }, 'PubMed'),
      it.openalex_id && h('a', { href: `https://openalex.org/${it.openalex_id}`, target: '_blank', rel: 'noopener' }, 'OpenAlex')));
}

// ------------------------------------------------------------------ KI-Vorschläge (Claude oder Gemini)
const aiSt = () => ui('rs-ai', { run: null });
const AI_COUNT_LABEL = { include: () => t('passend'), borderline: () => t('Grenzfall'), exclude: () => t('nicht passend'),
  'keine Antwort': () => t('ohne gültige Antwort') };
const countsText = c => Object.entries(c).map(([k, v]) => `${(AI_COUNT_LABEL[k] || (() => k))()} ${fmtInt(v)}`).join(', ');

// Stapel für Stapel, bis nichts mehr offen ist oder angehalten wird; ``since`` sorgt dafür, dass ein Durchgang jeden
// Treffer nur einmal fragt
async function aiRun(scope, redo, total) {
  const s = rs();
  const a = aiSt();
  const r0 = { pid: s.pid, total, done: 0, counts: {}, since: null, stop: false, used: { input: 0, output: 0, cost: null } };
  a.run = r0;
  update();
  try {
    while (!r0.stop) {
      const r = await run(() => api.post(`${R}/projects/${r0.pid}/ai/screening`, { limit: 20, scope, redo, since: r0.since }));
      Object.assign(r0, { since: r.since, total: r0.done + r.processed + r.remaining, used: addUsed(r0.used, r.used) });
      r0.done += r.processed;
      noteUsage(r);
      for (const [k, v] of Object.entries(r.counts || {})) r0.counts[k] = (r0.counts[k] || 0) + v;
      invalidate('queue', 'pool');
      update();
      if (!r.remaining || !r.processed) break;
    }
  } catch { /* Meldung kam schon */ } finally {
    a.run = null;
    invalidate('queue', 'pool');
    refreshSummary();
    if (r0.done) {
      toast(t('KI-Vorschläge für {n} Treffer ({c}). Verbrauch: {u}.', { n: fmtInt(r0.done), c: countsText(r0.counts), u: tokenText(r0.used, false) }),
        'success', 15000);
    }
    update();
  }
}

function aiStartDialog() {
  const s = rs();
  const d = { plan: null, scope: 'open', failed: true, again: false };
  run(() => api.get(`${R}/projects/${s.pid}/ai/plan`)).then(r => { d.plan = r; update(); }).catch(() => closeModal());
  const redo = () => (d.again ? 'all' : d.failed ? 'failed' : '');
  const count = () => {
    const c = d.plan.scopes[d.scope];
    return c.new + (d.failed || d.again ? c.failed : 0) + (d.again ? c.done : 0);
  };
  const scopeLabel = { open: t('offene'), borderline: t('offene Grenzfälle'), all: t('alle sichtbaren (auch entschiedene)') };
  openModal({
    title: t('KI-Vorschläge holen'),
    body: () => {
      if (!d.plan) return h('div', { class: 'muted' }, spinner(13), ' ', t('Lade …'));
      const c = d.plan.scopes[d.scope];
      const n = count();
      const tk = c.tokens || {};
      const inTok = (tk.new || 0) + (d.failed || d.again ? tk.failed || 0 : 0) + (d.again ? tk.done || 0 : 0)
        + Math.ceil(n / d.plan.batch) * (d.plan.system_tokens || 0);
      const outTok = n * (d.plan.out_per_record || 0);
      const est = { input: inTok, output: outTok, cost: costOf(d.plan.prices, inTok, outTok) };
      return h('div', { class: 'stack' },
        h('p', { class: 'small' }, t('{m} ordnet Treffer als „passend“, „nicht passend“ oder „Grenzfall“ ein – mit einem Satz Begründung, dem Kriterium und einem Ordner-Vorschlag. Das ist nur ein Vorschlag: Entschieden wird von Hand; Vorschlag und Entscheid stehen beide im Protokoll.', { m: d.plan.label })),
        notice('info', t('Ans Modell gehen Titel, Zeitschrift, Jahr und Abstract der Treffer sowie Titel, Fragestellung, Kriterien und Ordnernamen des Projekts – an {v} (API). Nichts aus Zotero, keine Volltexte.',
          { v: d.plan.vendor || t('den Anbieter') })),
        field(t('Welche Treffer'), segmented({ size: 'sm', value: d.scope, onChange: v => { d.scope = v; update(); },
          options: Object.keys(scopeLabel).map(k => ({ value: k, label: scopeLabel[k] })) })),
        h('div', { class: 'muted small' }, t('{n} noch ohne Vorschlag · {f} ohne gültige Antwort · {d} mit Vorschlag',
          { n: fmtInt(c.new), f: fmtInt(c.failed), d: fmtInt(c.done) })),
        c.failed ? checkbox({ checked: d.failed || d.again, disabled: d.again, label: t('Treffer ohne gültige Antwort noch einmal fragen ({n})', { n: fmtInt(c.failed) }),
          onChange: v => { d.failed = v; update(); } }) : null,
        c.done ? checkbox({ checked: d.again, label: t('Vorhandene Vorschläge neu einordnen lassen ({n}), z. B. nach geänderten Kriterien', { n: fmtInt(c.done) }),
          onChange: v => { d.again = v; update(); } }) : null,
        h('div', { class: 'small' }, h('b', null, t('{n} Treffer', { n: fmtInt(n) })), ` · ${t('in Stapeln zu {b}', { b: d.plan.batch })}`,
          n ? h('div', null, t('Geschätzt: {u}', { u: tokenText(est) }), est.cost == null ? h('span', { class: 'muted' }, ` · ${t('Kosten: siehe Konto beim Anbieter')}`) : null) : null),
        h('div', { class: 'muted small' }, t('Modell {m}, Aufwand {e} (Einstellungen › Sprachmodelle); Schlüssel aus {k}. Du kannst währenddessen weiter sichten und den Lauf jederzeit anhalten.',
          { m: d.plan.model, e: d.plan.effort || '–', k: d.plan.key_source || '–' })));
    },
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      { label: t('Starten'), kind: 'primary', icon: 'ai', disabled: !d.plan || !count(),
        onClick: () => { const args = [d.scope, redo(), count()]; closeModal(); aiRun(...args); } }],
  });
}

// KI-Leiste oben im Screening (immer an derselben Stelle): Stand der Vorschläge als Filter, „Vorschläge holen …“,
// während des Laufs Fortschritt, Verbrauch und „Anhalten“
function aiBar(queue) {
  const s = rs();
  const st = sc();
  const ai = aiInfo();
  if (!aiVisible()) return null;
  if (!ai.available) {
    return h('div', { class: 'rs-ai-bar' }, icon('ai', 15),
      h('span', { class: 'muted small grow' }, t('KI-Vorschläge: unter Einstellungen › Sprachmodelle einen Schlüssel speichern. Die Recherche nutzt das Modell der Vorauswahl im Forschungsstand.')));
  }
  const a = aiSt().run;
  const c = (queue && queue.ai_counts) || {};
  const none = !Object.keys(c).some(k => k !== 'none');
  const chip = (status, label) => h('button', { type: 'button', key: status, class: ['chip', st.status === status && 'chip-accent'],
    title: t('Nur offene Treffer mit diesem Vorschlag zeigen'), onclick: () => setStatus(st.status === status ? 'open' : status) },
  h('span', null, `${label} ${fmtInt(c[status.slice(3)] || 0)}`));
  const meta = h('div', { class: 'rs-ai-bar-meta muted small' }, ai.label || ai.model,
    ai.key_source ? ` · ${t('Schlüssel aus {k}', { k: ai.key_source })}` : '',
    ai.used_total && ai.used_total.requests ? ` · ${t('seit Dienststart {u}', { u: tokenText(ai.used_total, false) })}` : '');
  if (a) {
    const here = a.pid === s.pid;
    return h('div', { class: 'rs-ai-bar' }, icon('ai', 15),
      h('div', { class: 'grow' }, progress(a.done, a.total, here
        ? t('KI ordnet ein: {d} von {n} – die Vorschläge erscheinen laufend. Bisher {u}.', { d: fmtInt(a.done), n: fmtInt(a.total), u: tokenText(a.used, false) })
        : t('Ein KI-Lauf läuft in einem anderen Projekt.'))),
      btn(a.stop ? t('Hält nach diesem Stapel an …') : t('Anhalten'), { size: 'sm', icon: 'stop', disabled: a.stop, onClick: () => { a.stop = true; update(); } }),
      meta);
  }
  return h('div', { class: 'rs-ai-bar' }, icon('ai', 15),
    none ? h('span', { class: 'small' }, t('Noch keine KI-Vorschläge – deshalb ist nichts grün markiert.'))
      : isList() ? h('span', { class: 'small' }, t('Offene nach Vorschlag:'), ' ',
        [['include', AI_LABELS.include()], ['borderline', AI_LABELS.borderline()], ['exclude', AI_LABELS.exclude()], ['none', t('ohne')]]
          .map(([k, l]) => `${l} ${fmtInt(c[k] || 0)}`).join(' · '))
        : h('div', { class: 'chips' }, chip('ai_include', AI_LABELS.include()), chip('ai_borderline', AI_LABELS.borderline()),
          chip('ai_exclude', AI_LABELS.exclude()), chip('ai_none', t('ohne Vorschlag'))),
    h('span', { class: 'spacer' }),
    btn(t('Vorschläge holen …'), { size: 'sm', icon: 'ai', kind: none || c.none ? 'primary' : 'ghost', onClick: aiStartDialog,
      title: c.none ? t('{n} offene Treffer haben noch keinen Vorschlag', { n: fmtInt(c.none) }) : '' }),
    meta);
}

export function screeningTab() {
  const s = rs();
  const st = sc();
  const queue = loadQueue();
  const sum = s.project.summary || {};
  const list = isList();
  const it = queue && !list ? queue.items[st.index] : null;
  const hasAi = aiInfo().available || (queue && Object.keys(queue.ai_counts || {}).some(k => k !== 'none'));
  return h('div', { class: 'view-body rs-screen' },
    h('div', { class: 'rs-screen-main' },
      h('div', { class: 'row wrap rs-screen-top' },
        segmented({ size: 'sm', value: st.status, onChange: setStatus, options: [
          { value: 'open', label: t('offen') }, { value: 'borderline', label: t('Grenzfälle'), badge: sum.borderline_open ? String(sum.borderline_open) : null },
          { value: 'maybe', label: t('unsicher') },
          ...(list ? [] : [{ value: 'include', label: t('eingeschlossen') }, { value: 'exclude', label: t('ausgeschlossen') }, { value: 'all', label: t('alle') },
            { value: 'hidden', label: t('ausgeblendet'), title: t('Durch Vorfilter ausgeblendete Treffer einzeln prüfen') }])] }),
        list ? h('span', { class: 'muted small', title: t('Eingeschlossene, Ausgeschlossene und Ausgeblendete zeigt die Ansicht „Karten“') }, t('Entschiedene: Ansicht Karten')) : null,
        hasAi ? toggle({ checked: aiVisible(), label: t('KI-Vorschläge'), onChange: setAiVisible,
          title: aiVisible() ? t('Ausschalten: blind sichten – KI-Vorschläge sind im Screening und im Pool ausgeblendet; im Protokoll steht, welche Entscheide ohne sichtbaren Vorschlag fielen.')
            : t('Einschalten: KI-Vorschläge auf den Karten, in der Liste und im Pool zeigen.') }) : null,
        !list && st.status.startsWith('ai_') ? btn(t('KI: {l} ×', { l: st.status === 'ai_none' ? t('ohne Vorschlag') : AI_LABELS[st.status.slice(3)]() }),
          { size: 'sm', kind: 'ghost', title: t('Zurück zu allen offenen'), onClick: () => setStatus('open') }) : null,
        h('span', { class: 'spacer' }),
        (s.project.settings.reviewers || []).length ? h('div', { class: 'rs-reviewer', title: t('Steht beim Entscheid und im Protokoll') },
          select({ value: s.project.settings.current_reviewer || '', label: t('Es entscheidet'), onChange: setReviewer, options: [
            { value: '', label: t('Es entscheidet: niemand gewählt') },
            ...s.project.settings.reviewers.map(n => ({ value: n, label: t('Es entscheidet: {n}', { n }) }))] })) : null,
        segmented({ size: 'sm', value: st.view, onChange: setView, options: [
          { value: 'cards', label: t('Karten'), title: t('Ein Treffer nach dem anderen, ganzer Abstract') },
          { value: 'list', label: t('Liste'), title: t('Alle offenen Treffer auf einmal, an- und abwählen, dann übernehmen') }] }),
        list ? null : btn('', { icon: 'arrowLeft', size: 'sm', kind: 'ghost', title: t('zurück (K)'), onClick: () => go(-1) }),
        list ? null : btn('', { icon: 'arrowRight', size: 'sm', kind: 'ghost', title: t('weiter (J)'), onClick: () => go(1) })),
      aiBar(queue),
      queue == null ? h('div', { class: 'muted' }, t('Lade …'))
        : list ? listView(queue, st.status)
        : it ? recordCard(it, queue)
          : emptyState('check', st.status === 'open' ? t('Alles gesichtet') : t('Keine Treffer in dieser Auswahl'),
            st.status === 'open' ? t('Im Pool gibt es nichts Offenes mehr. Ausgeblendete prüfen: Auswahl „ausgeblendet“ oder im Pool.') : null)),
    h('aside', { class: 'rs-screen-side', ...paneProps('rs-screening', 'clamp(280px, 22vw, 480px)') }, h('div', { class: 'rs-screen-side-inner' },
      card(t('Fortschritt'), 'check', h('div', { class: 'stack-sm' },
        progress(sum.screened || 0, sum.visible || 0, t('gesichtet {a} von {b}', { a: fmtInt(sum.screened || 0), b: fmtInt(sum.visible || 0) })),
        h('div', { class: 'small' }, t('eingeschlossen {i} · unsicher {m} · ausgeschlossen {x}', { i: fmtInt(sum.included || 0), m: fmtInt(sum.maybe || 0), x: fmtInt(sum.excluded || 0) })),
        h('div', { class: 'small' }, t('Grenzfälle {b} (offen {o}) · ausgeblendet {h}', { b: fmtInt(sum.borderline || 0), o: fmtInt(sum.borderline_open || 0), h: fmtInt(sum.hidden || 0) })),
        sum.recall_warnings ? h('div', { class: 'danger-text small' }, t('Recall-Check: {n} Warnungen (siehe Pool)', { n: sum.recall_warnings })) : null)),
      queue && it ? card(t('Entscheid'), 'target', decisionPanel(it, queue)) : null,
      list ? listSideCard(queue, { onUndo: undo, status: st.status }) : null),
    splitter('rs-screening', { def: 'clamp(280px, 22vw, 480px)', min: 240, max: 720, side: 'right' })));
}
