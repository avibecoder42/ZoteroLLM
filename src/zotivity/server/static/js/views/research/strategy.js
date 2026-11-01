// Suchstrategie: Konzeptblöcke (Population, Phänomen, Kontext, Ausschluss) → Suchstrings je Quelle mit Trefferzahl.
// Auf Wunsch schlägt das Sprachmodell Blöcke vor (Konzept 3.2): Die Vorschläge stehen direkt bei den Blöcken – Begriffe
// einzeln weglassen, einen Block verwerfen oder neu anfordern (mit Wunsch), übernommen wird je Block oder alle. Blöcke und
// Suchstrings scrollen je für sich; alles wird automatisch gespeichert.
import { h } from '../../core/vdom.js';
import { update, ui, toast, openModal, closeModal } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt, debounce, copyToClipboard } from '../../core/util.js';
import { btn, iconBtn, card, field, textInput, textArea, segmented, notice, emptyState, spinner, badge } from '../../ui/components.js';
import { icon } from '../../ui/icons.js';
import { R, rs, busy, isBusy, invalidate, sourceLabel, isLive, aiInfo, tokenText, noteUsage, addUsed, workspace, saveLater, saveState, serverText } from './common.js';
import { estimateLine } from './project.js';

const blank = (name = '') => ({ name, kind: 'include', field: 'tiab', terms: [], mesh: [], psycinfo: [] });
// Neue Blöcke heissen der Reihe nach wie die typischen Konzepte (Population, Phänomen, Kontext), danach leer
const TYPICAL = () => [t('Population'), t('Phänomen'), t('Kontext')];
function addBlock(st, kind = 'include') {
  if (kind === 'exclude') st.blocks.push({ ...blank(t('Ausschluss')), kind: 'exclude', field: 'ti' });
  else {
    const used = new Set(st.blocks.map(b => (b.name || '').toLowerCase()));
    st.blocks.push(blank(TYPICAL().find(n => !used.has(n.toLowerCase())) || ''));
  }
  changed();
}

function bst() {
  const s = rs();
  const st = ui('rs-strategy', { pid: null, blocks: null, built: null, counts: {}, buildSeq: 0, ai: null });
  if (st.pid !== s.pid) {
    st.pid = s.pid;
    st.blocks = JSON.parse(JSON.stringify((s.project && s.project.blocks) || []));
    st.built = null; st.counts = {}; st.ai = null; st.sourcesChanged = false;
    if (st.blocks.length) rebuild();
  } else if (st.sourcesChanged) {  // andere Quellen gewählt: Suchstrings neu erzeugen, die Blöcke bleiben
    st.sourcesChanged = false;
    if (st.blocks.length) rebuild();
  }
  return st;
}

const linesOf = v => (v || []).join('\n');
const toLines = v => v.split('\n').map(x => x.trim()).filter(Boolean);

// Strings neu erzeugen (Dienst) und für PubMed/OpenAlex die Trefferzahl holen
const rebuild = debounce(async () => {
  const st = ui('rs-strategy');
  const s = rs();
  if (!s.pid) return;
  const seq = ++st.buildSeq;
  try {
    const built = await api.post(`${R}/projects/${s.pid}/build`, { blocks: st.blocks });
    if (seq !== st.buildSeq) return;
    st.built = built;
    update();
    for (const src of Object.keys(built)) if (isLive(src)) countLive(src, built[src].string, seq);
  } catch (err) { toast(err.message, 'error'); }
}, 450);

async function countLive(src, string, seq) {
  const st = ui('rs-strategy');
  if (!string) { st.counts[src] = null; update(); return; }
  st.counts[src] = { loading: true };
  update();
  try {
    const r = await api.post(`${R}/count`, { source: src, string });
    if (seq === st.buildSeq) st.counts[src] = r;
  } catch (err) {
    if (seq === st.buildSeq) st.counts[src] = { error: err.message };
  }
  update();
}

function saveBlocks() {
  const st = ui('rs-strategy');
  const pid = rs().pid;
  saveLater('blocks', async opts => {
    const r = await api.put(`${R}/projects/${pid}/blocks`, { blocks: st.blocks }, opts);
    if (rs().pid === pid && rs().project) rs().project.blocks = r.blocks;
  });
}

function changed() {
  update();
  rebuild();
  saveBlocks();
}

function blockCard(b, i, st) {
  const move = d => { const j = i + d; if (j < 0 || j >= st.blocks.length) return; [st.blocks[i], st.blocks[j]] = [st.blocks[j], st.blocks[i]]; changed(); };
  const fold = ui(`rs-block-${i}`, { headings: (b.mesh || []).length > 0 || (b.psycinfo || []).length > 0 });
  const proposed = st.ai ? st.ai.blocks.find(sb => norm(sb.name) === norm(b.name)) : null;
  return h('section', { class: ['card', 'rs-block', b.kind === 'exclude' && 'rs-block-exclude'], key: `b${i}` },
    h('div', { class: 'row' },
      textInput({ value: b.name, placeholder: t('Name des Blocks'), class: 'rs-block-name', onInput: v => { b.name = v; update(); saveBlocks(); } }),
      segmented({ size: 'sm', value: b.kind, options: [{ value: 'include', label: t('einschliessen') }, { value: 'exclude', label: t('ausschliessen') }],
        onChange: v => { b.kind = v; changed(); } }),
      segmented({ size: 'sm', value: b.field, options: [{ value: 'tiab', label: t('Titel + Abstract') }, { value: 'ti', label: t('nur Titel') }],
        onChange: v => { b.field = v; changed(); } }),
      h('span', { class: 'spacer' }),
      iconBtn('chevronUp', t('nach oben'), () => move(-1), { disabled: i === 0 }),
      iconBtn('chevronDown', t('nach unten'), () => move(1), { disabled: i === st.blocks.length - 1 }),
      iconBtn('trash', t('Block entfernen'), () => { st.blocks.splice(i, 1); changed(); })),
    field(t('Begriffe (einer pro Zeile, * für beliebige Endung)'), textArea({ value: linesOf(b.terms), rows: 5,
      placeholder: 'adolescen*\nteen*\n"young people"', onInput: v => { b.terms = toLines(v); changed(); } })),
    proposed ? suggestion(st, proposed, b) : null,
    h('button', { type: 'button', class: 'rs-link small', onclick: () => { fold.headings = !fold.headings; update(); } },
      fold.headings ? t('Schlagwörter ausblenden') : t('Schlagwörter (MeSH, PsycInfo) …')),
    fold.headings && h('div', { class: 'field-row' },
      field(t('MeSH (PubMed)'), textArea({ value: linesOf(b.mesh), rows: 3, placeholder: 'Adolescent', onInput: v => { b.mesh = toLines(v); changed(); } })),
      field(t('PsycInfo-Schlagwörter (Ovid)'), textArea({ value: linesOf(b.psycinfo), rows: 3, placeholder: 'Internet Addiction', onInput: v => { b.psycinfo = toLines(v); changed(); } }))));
}

// ------------------------------------------------------------------ KI-Vorschlag für Blöcke
const norm = x => String(x || '').toLowerCase();
const missing = (have, add) => add.filter(x => !(have || []).some(y => norm(y) === norm(x)));

// Gleichnamiger Block vorhanden? Dann nur die fehlenden Begriffe und Schlagwörter
function fresh(st, sb) {
  const same = st.blocks.find(b => norm(b.name) === norm(sb.name));
  const n = same ? missing(same.terms, sb.terms).length + missing(same.mesh, sb.mesh).length + missing(same.psycinfo, sb.psycinfo).length
    : sb.terms.length + sb.mesh.length + sb.psycinfo.length;
  return { same, n };
}

function adoptBlock(st, sb) {
  const { same } = fresh(st, sb);
  if (same) {
    for (const k of ['terms', 'mesh', 'psycinfo']) same[k] = [...(same[k] || []), ...missing(same[k], sb[k])];
  } else {
    st.blocks.push({ name: sb.name, kind: sb.kind, field: sb.field, terms: [...sb.terms], mesh: [...sb.mesh], psycinfo: [...sb.psycinfo] });
  }
  const i = st.blocks.indexOf(same || st.blocks[st.blocks.length - 1]);
  if (sb.mesh.length || sb.psycinfo.length) ui(`rs-block-${i}`, {}).headings = true;  // zum Prüfen aufklappen
}

async function askAi(st) {
  const s = rs();
  const r = await busy('ai-blocks', () => api.post(`${R}/projects/${s.pid}/ai/blocks`, { blocks: st.blocks }));
  if (r) { st.ai = r; noteUsage(r); update(); }
}

function chipList(label, list, onDrop) {
  if (!list.length) return null;
  return h('div', { class: 'rs-ai-chips' }, label ? h('span', { class: 'muted small' }, label) : null,
    h('div', { class: 'chips' }, list.map(x => h('span', { key: x, class: 'chip' }, h('span', null, x),
      h('button', { type: 'button', class: 'chip-x', title: t('Weglassen'), 'aria-label': t('Weglassen'), onclick: () => onDrop(x) }, '×')))));
}

async function redoBlock(st, sb) {
  const s = rs();
  const r = st.ai;
  const res = await busy(`ai-block:${sb.name}`, () => api.post(`${R}/projects/${s.pid}/ai/blocks`, {
    blocks: st.blocks, focus: { name: sb.name, kind: sb.kind, terms: sb.terms, hint: sb.hint || '' } }));
  if (!res) return;
  noteUsage(res);
  r.used = addUsed(r.used || {}, res.used);
  if (!res.blocks.length) { toast(t('Kein brauchbarer neuer Vorschlag für „{b}“.', { b: sb.name }), 'warning'); return; }
  r.blocks = r.blocks.map(x => (x === sb ? res.blocks[0] : x));
  update();
}

// Kopf des KI-Vorschlags: Überblick und „Alle übernehmen“; die Vorschläge selbst stehen bei den Blöcken
function aiBar(st) {
  const r = st.ai;
  if (!r) return null;
  const open = r.blocks.filter(sb => fresh(st, sb).n);
  const count = open.reduce((a, sb) => a + fresh(st, sb).n, 0);
  const headings = open.some(sb => sb.mesh.length || sb.psycinfo.length);
  return h('div', { class: 'rs-ai-suggest' },
    h('div', { class: 'row wrap' }, icon('ai', 16),
      h('b', { class: 'grow' }, !r.blocks.length ? t('KI-Vorschlag ({m}): nichts Brauchbares', { m: r.model || r.label })
        : open.length ? t('KI-Vorschlag ({m}): {b} Blöcke, {n} neue Begriffe', { m: r.model || r.label, b: open.length, n: count })
          : t('KI-Vorschlag ({m}): alles übernommen', { m: r.model || r.label })),
      open.length ? btn(t('Alle übernehmen'), { size: 'sm', kind: 'primary', icon: 'check', onClick: () => { open.forEach(sb => adoptBlock(st, sb)); changed(); } }) : null,
      btn(open.length ? t('Verwerfen') : t('Schliessen'), { size: 'sm', kind: 'ghost', onClick: () => { st.ai = null; update(); } })),
    headings ? h('div', { class: 'warn-text small' }, t('MeSH und PsycInfo-Schlagwörter prüfen (MeSH-Browser, APA-Thesaurus) – Sprachmodelle erfinden manchmal Einträge.')) : null,
    r.note ? h('div', { class: 'muted small' }, r.note) : null,
    open.length ? h('div', { class: 'muted small' }, t('Die Vorschläge stehen unten bei den Blöcken. × lässt einen Begriff weg, ↻ fordert einen Block neu an. Die Trefferzahlen rechts zeigen, was Übernommenes bewirkt.')) : null,
    r.used ? h('div', { class: 'muted small' }, t('Verbrauch: {u}', { u: tokenText(r.used, false) })) : null);
}

// Vorschlag zu einem Block: in dessen Karte nur, was dort noch fehlt; ohne gleichnamigen Block in einer eigenen Karte
function suggestion(st, sb, same) {
  const list = k => (same ? missing(same[k], sb[k]) : sb[k]);
  const n = list('terms').length + list('mesh').length + list('psycinfo').length;
  if (!n) return null;
  const r = st.ai;
  const drop = k => x => { sb[k] = sb[k].filter(y => y !== x); update(); };
  const busyKey = `ai-block:${sb.name}`;
  return h('div', { class: 'rs-suggest' },
    h('div', { class: 'row wrap' },
      h('span', { class: 'rs-suggest-label' }, icon('ai', 13), t('Vorschlag')),
      same ? null : sb.kind === 'exclude' ? badge(t('ausschliessen, nur Titel'), 'danger') : badge(sb.field === 'ti' ? t('nur Titel') : t('Titel + Abstract'), 'neutral'),
      h('span', { class: 'spacer' }),
      btn(same ? t('{n} ergänzen', { n }) : t('Übernehmen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => { adoptBlock(st, sb); changed(); },
        title: same ? t('Fehlende Begriffe in den Block „{b}“ übernehmen', { b: same.name }) : t('Als neuen Block übernehmen') }),
      iconBtn('refresh', t('Diesen Block neu vorschlagen lassen'), () => { sb.asking = !sb.asking; update(); }, { disabled: isBusy(busyKey) }),
      iconBtn('x', t('Diesen Vorschlag verwerfen'), () => { r.blocks = r.blocks.filter(x => x !== sb); update(); })),
    sb.reason ? h('div', { class: 'muted small' }, sb.reason) : null,
    chipList('', list('terms'), drop('terms')),
    chipList('MeSH', list('mesh'), drop('mesh')),
    chipList('PsycInfo', list('psycinfo'), drop('psycinfo')),
    sb.asking ? h('div', { class: 'row' },
      h('div', { class: 'grow' }, textInput({ value: sb.hint || '', placeholder: t('Was soll anders sein? (optional, z. B. mehr Alltagsbegriffe, ohne Mobbing)'),
        onInput: v => { sb.hint = v; }, onKeyDown: e => { if (e.key === 'Enter') redoBlock(st, sb); } })),
      btn(t('Neu anfordern'), { size: 'sm', icon: 'ai', busy: isBusy(busyKey), onClick: () => redoBlock(st, sb) })) : null);
}

function aiButton(st, opts = {}) {
  const ai = aiInfo();
  if (!ai.available) return null;
  const p = rs().project || {};
  const ready = !!(p.question || p.description || '').trim();
  return btn(t('KI-Vorschlag'), { icon: 'ai', size: 'sm', kind: 'ghost', ...opts, busy: isBusy('ai-blocks'), disabled: !ready, onClick: () => askAi(st),
    title: ready ? t('Schlägt aus Fragestellung und Kriterien Blöcke mit Begriffen, MeSH und PsycInfo-Schlagwörtern vor ({m}, {v}). Gesendet werden Projekttext und die Blöcke hier.',
      { m: ai.label, v: ai.vendor }) : t('Zuerst unter Projekt eine Fragestellung eintragen.') });
}

function countText(c) {
  if (!c) return null;
  if (c.loading) return h('span', { class: 'muted small' }, spinner(12), ' ', t('zählt …'));
  if (c.error) return h('span', { class: 'danger-text small', title: c.error }, t('Fehler'));
  // Obergrenze (swisscovery mit mehreren Blöcken): „bis zu …“, Erklärung im Tooltip
  return h('b', { class: 'rs-count', title: (c.warnings || []).map(serverText).join('\n') || undefined },
    c.upper_bound ? t('bis zu {n} Treffer', { n: fmtInt(c.count) }) : t('{n} Treffer', { n: fmtInt(c.count) }));
}

// Vorschläge für Blöcke, die es noch nicht gibt: eigene Karte in der Liste der Blöcke
function suggestedCards(st) {
  if (!st.ai) return null;
  return st.ai.blocks.filter(sb => !st.blocks.some(b => norm(b.name) === norm(sb.name))).map(sb =>
    h('section', { class: ['card', 'rs-block', 'rs-block-suggested'], key: `s${sb.name}` }, h('b', null, sb.name), suggestion(st, sb, null)));
}

// Als Suchstring übernehmen – für eine Quelle oder alle direkt durchsuchbaren auf einmal. Name vorbelegt; gleicher Name
// wie ein bestehender Suchstring derselben Quelle ergibt dessen nächste Version.
function adopt(items) {
  const s = rs();
  const st = { name: t('Suchstrategie') };
  const save = async () => {
    const name = st.name.trim();
    if (!name) return;
    const ok = await busy('adopt', async () => {
      for (const { src, string } of items) await api.post(`${R}/projects/${s.pid}/queries`, { name, source: src, string });
      return true;
    });
    if (!ok) return;
    closeModal();
    invalidate('queries');
    toast(t('Als Suchstring „{n}“ gespeichert für {s} (unter Suche & Import).', { n: name, s: items.map(x => sourceLabel(x.src)).join(', ') }), 'success', 5000);
  };
  openModal({ title: items.length > 1 ? t('Als Suchstrings übernehmen ({n} Quellen)', { n: items.length }) : t('Als Suchstring für {s} übernehmen', { s: sourceLabel(items[0].src) }),
    body: () => h('div', { class: 'stack' },
      field(t('Name'), textInput({ value: st.name, onInput: v => { st.name = v; update(); }, onKeyDown: e => { if (e.key === 'Enter') save(); } }),
        { hint: t('Gleicher Name wie ein bestehender Suchstring: wird dessen nächste Version (die alte bleibt im Protokoll).') }),
      items.map(({ src, string }) => h('div', { key: src, class: 'stack-sm' }, items.length > 1 ? h('b', { class: 'small' }, sourceLabel(src)) : null,
        h('pre', { class: 'rs-string' }, string)))),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      { label: t('Übernehmen'), kind: 'primary', disabled: !st.name.trim(), busy: isBusy('adopt'), onClick: save }] });
}

function builtCard(st) {
  const b = st.built;
  if (!b) return null;
  const row = src => {
    const x = b[src];
    return h('div', { class: 'rs-built', key: src },
      h('div', { class: 'row' }, h('b', null, sourceLabel(src)), isLive(src) ? countText(st.counts[src]) : h('span', { class: 'muted small' }, t('Trefferzahl in der Datenbank prüfen')),
        isLive(src) && x.string ? iconBtn('refresh', t('Trefferzahl neu holen'), () => countLive(src, x.string, st.buildSeq),
          { disabled: !!(st.counts[src] && st.counts[src].loading) }) : null,
        h('span', { class: 'spacer' }),
        x.string && iconBtn('copy', t('Kopieren'), async () => { await copyToClipboard(x.string); toast(t('Kopiert.'), 'success', 1500); }),
        x.string && isLive(src) && btn(t('Als Suchstring übernehmen'), { size: 'sm', icon: 'plus', onClick: () => adopt([{ src, string: x.string }]) })),
      x.string ? h('pre', { class: 'rs-string' }, x.string) : h('div', { class: 'muted small' }, t('Noch leer.')),
      st.counts[src] && st.counts[src].upper_bound ? h('div', { class: 'muted small' }, '· ', serverText((st.counts[src].warnings || [])[0])) : null,
      (x.notes || []).map((n, i) => h('div', { class: 'muted small', key: i }, '· ', serverText(n))));
  };
  const live = Object.keys(b).filter(src => isLive(src) && b[src].string).map(src => ({ src, string: b[src].string }));
  return card(t('Suchstrings je Quelle'), 'layers', h('div', { class: 'stack' },
    h('div', { class: 'muted small' }, t('Quellen wählen im Tab „Datenbanken“.')),
    Object.keys(b).map(row)),
    { actions: [live.length > 1 ? btn(t('Alle übernehmen ({n})', { n: live.length }), { size: 'sm', icon: 'plus', onClick: () => adopt(live),
      title: t('Für alle direkt durchsuchbaren Quellen als Suchstrings übernehmen') }) : null] });
}

export function strategyTab() {
  const st = bst();
  const main = h('div', { class: 'stack' },
    h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('Konzeptblöcke')),
      saveState(),
      st.blocks.length || st.ai ? aiButton(st) : null,  // ohne Blöcke steht der Knopf in der Mitte
      aiInfo().available ? estimateLine('blocks', { blocks: st.blocks }, JSON.stringify(st.blocks).length + ':' + st.blocks.length) : null),
    notice('info', t('Innerhalb eines Blocks gilt ODER, zwischen Blöcken UND. Ausschlussblöcke kommen mit NOT dazu. Fertige, verschachtelte Strings lassen sich unter Suche & Import direkt einfügen oder als Dateien laden.')),
    aiBar(st),
    st.blocks.length ? st.blocks.map((b, i) => blockCard(b, i, st))
      : st.ai ? null : emptyState('layers', t('Noch keine Blöcke'), t('Typisch sind Population, Phänomen und Kontext, dazu ein Ausschlussblock. Blöcke sind freiwillig: fertige Suchstrings gehen auch direkt unter Suche & Import.'),
        aiButton(st, { kind: 'primary', size: '' })),
    suggestedCards(st),
    h('div', { class: 'row' }, btn(t('Block hinzufügen'), { icon: 'plus', kind: st.blocks.length || st.ai || !aiInfo().available ? 'secondary' : 'ghost',
      onClick: () => addBlock(st), title: t('Neuer Block; die ersten heissen Population, Phänomen, Kontext') }),
    btn(t('Ausschlussblock'), { icon: 'minus', kind: 'ghost', onClick: () => addBlock(st, 'exclude') })));
  const side = builtCard(st) || card(t('Suchstrings je Quelle'), 'layers',
    h('p', { class: 'muted small' }, t('Erscheinen hier, sobald ein Block Begriffe hat – mit Trefferzahl für PubMed und OpenAlex.')));
  return workspace('strategy', main, side, { def: 'clamp(340px, 38vw, 900px)', max: 1100 });
}
