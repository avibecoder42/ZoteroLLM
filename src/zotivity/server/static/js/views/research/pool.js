// Pool: alle Treffer ohne Duplikate, Abgleich mit Zotero, Vorfilter, die nur markieren (Konzept 3.7): Regeln mit
// Ausnahmen (Grenzfall statt ausgeblendet), „Ausgeblendete prüfen“ als Schnellsichtung, Abstracts nachladen,
// Recall-Check mit Schlüsselarbeiten, Filter nach KI-Vorschlag. Der Pool folgt der jeweils letzten Suche je Suchstring;
// „Pool zurücksetzen“ leert ihn (nach Rückfrage).
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, openModal, closeModal, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtInt, debounce } from '../../core/util.js';
import { btn, iconBtn, card, field, textInput, textArea, select, segmented, checkbox, notice, emptyState, badge, progress, spinner } from '../../ui/components.js';
import { R, rs, enc, busy, isBusy, invalidate, needsLoad, refreshSummary, sourceLabel, sourceBadges, statusBadge, authorsShort,
  loadProject, borderlineText, aiInfo, aiBadge, aiVisible, workspace, targetName, serverText } from './common.js';

const PAGE = 200;
const PATTERN_KINDS = ['title', 'text', 'journal'];

function fst() {
  return ui('rs-pool', { source: '', query: '', year_from: '', year_to: '', journal: '', lang: '', text: '', status: '', show_hidden: false,
    limit: PAGE, open: {}, newKind: 'title', newPattern: '' });
}

function poolPath(s, f) {
  const q = ['source', 'query', 'year_from', 'year_to', 'journal', 'lang', 'text', 'status'].filter(k => f[k] !== '' && f[k] != null)
    .map(k => `${k}=${enc(f[k])}`);
  if (f.show_hidden) q.push('show_hidden=true');
  return `${R}/projects/${s.pid}/pool${q.length ? '?' + q.join('&') : ''}`;
}

export function loadPool() {
  const s = rs();
  const f = fst();
  const seq = (f.seq = (f.seq || 0) + 1);
  s.busy['loading:pool'] = true;
  return api.get(poolPath(s, f)).then(r => { if (seq === f.seq) { s.pool = r; delete s.stale.pool; } })
    .catch(err => toast(err.message, 'error')).finally(() => { delete s.busy['loading:pool']; update(); });
}
const reload = debounce(loadPool, 350);

const STAT_KEYS = ['count', 'label', 'matched', 'hidden', 'exception', 'reviewed', 'flagged', 'included', 'excluded'];
async function savePrefilters(list) {
  const s = rs();
  const clean = list.map(f => Object.fromEntries(Object.entries(f).filter(([k]) => !STAT_KEYS.includes(k))));
  await run(() => api.put(`${R}/projects/${s.pid}`, { prefilters: clean }));
  invalidate('queue', 'plan');
  await Promise.all([loadPool(), loadProject(), refreshSummary()]);
}

async function zoteroMatch() {
  const s = rs();
  const r = await busy('zotero-match', () => api.post(`${R}/projects/${s.pid}/zotero/match`, {}));
  if (!r) return;
  toast(t('Abgleich mit Zotero: {m} von {n} Einträgen der Zielbibliothek sind schon im Pool.', { m: fmtInt(r.matches), n: fmtInt(r.items) }), 'success', 6000);
  invalidate('queue', 'plan');
  loadPool(); refreshSummary();
}

// ------------------------------------------------------------------ Regel bearbeiten (Muster, Ausnahmen)
function editRule(rule, list) {
  const s = rs();
  const d = { ...rule, exceptions: rule.exceptions || '', exception_scope: rule.exception_scope || 'text', terms: null, picked: new Set() };
  const loadTerms = async () => {
    d.terms = await run(() => api.get(`${R}/projects/${s.pid}/terms`));
    update();
  };
  const addPicked = () => {
    const have = new Set(d.exceptions.split(/\s*[,;\n]\s*/).map(x => x.trim().toLowerCase()).filter(Boolean));
    const add = [...d.picked].filter(x => !have.has(x.toLowerCase())).map(x => (x.includes(' ') ? `"${x}"` : x));
    d.exceptions = [d.exceptions.trim(), ...add].filter(Boolean).join(', ');
    d.picked.clear();
    update();
  };
  const save = async () => {
    const { terms, picked, ...rest } = d;
    await savePrefilters(list.map(x => (x.id === rule.id ? rest : x)));
    closeModal();
  };
  const termGroup = (name, terms, key) => h('div', { key, class: 'stack-sm' }, h('b', { class: 'small' }, name),
    h('div', { class: 'chips' }, terms.map(x => h('button', { type: 'button', key: x, class: ['chip', d.picked.has(x) && 'chip-accent'],
      onclick: () => { d.picked.has(x) ? d.picked.delete(x) : d.picked.add(x); update(); } }, h('span', null, x)))));
  openModal({
    title: t('Vorfilter bearbeiten'), cls: 'modal-wide',
    body: () => h('div', { class: 'stack' },
      field(t('Ausschliessen, wenn … enthält'), textInput({ value: d.pattern, onInput: v => { d.pattern = v; update(); } }),
        { hint: t('Begriffe mit Komma oder OR trennen. * = beliebige Fortsetzung, auch mitten im Wort und in der Mehrzahl (bully* findet Cyberbullies); (y|ie) schreibt Wortformen aus.') }),
      PATTERN_KINDS.includes(d.kind) && d.kind !== 'journal' && h('div', { class: 'stack-sm' },
        field(t('Ausser es kommt vor (Grenzfall statt ausblenden)'), textArea({ value: d.exceptions, rows: 4,
          placeholder: 'banter, teas*, jok*, conflict*, "what counts", defin*, percept*', onInput: v => { d.exceptions = v; update(); } })),
        segmented({ size: 'sm', value: d.exception_scope, onChange: v => { d.exception_scope = v; update(); }, options: [
          { value: 'text', label: t('in Titel oder Abstract') }, { value: 'title', label: t('nur im Titel') }] }),
        h('div', { class: 'muted small' }, t('Treffer mit Ausnahmebegriff werden nicht ausgeblendet, sondern als Grenzfall gekennzeichnet – zuerst die mit dem Begriff im Titel.')),
        d.terms == null ? btn(t('Ausnahmen aus der Suchstrategie vorschlagen'), { size: 'sm', icon: 'layers', onClick: loadTerms })
          : h('div', { class: 'stack-sm rs-terms' },
            h('div', { class: 'muted small' }, t('Begriffe anklicken, dann übernehmen. Die Begriffe des Phänomens passen meist am besten.')),
            d.terms.blocks.map((b, i) => termGroup(t('Block: {n}', { n: b.name }), b.terms, `b${i}`)),
            d.terms.queries.map((q, i) => termGroup(t('Suchstring: {n}', { n: q.name }), q.terms, `q${i}`)),
            !d.terms.blocks.length && !d.terms.queries.length && h('div', { class: 'muted small' }, t('Keine Begriffe gefunden.')),
            btn(t('{n} übernehmen', { n: d.picked.size }), { size: 'sm', icon: 'plus', disabled: !d.picked.size, onClick: addPicked })))),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      { label: t('Speichern'), kind: 'primary', disabled: !(d.pattern || '').trim(), onClick: save }],
  });
}

// ------------------------------------------------------------------ Ausgeblendete prüfen (Schnellsichtung)
function reviewHidden(rule) {
  const s = rs();
  const d = { items: null, sel: new Set(), open: {} };
  const load = async () => {
    const r = await run(() => api.get(`${R}/projects/${s.pid}/pool?status=hidden&rule=${enc(rule.id)}`));
    d.items = r.items.filter(it => it.hidden_by.includes(rule.id));
    d.sel = new Set([...d.sel].filter(id => d.items.some(it => it.id === id)));
    update();
  };
  const act = async verdict => {
    if (!d.sel.size) return;
    await busy('review', () => api.post(`${R}/projects/${s.pid}/review`, { record_ids: [...d.sel], verdict, rule_id: rule.id }));
    toast({ restore: t('{n} zurückgeholt.'), borderline: t('{n} als Grenzfall gekennzeichnet.'), exclude: t('{n} bleiben ausgeschlossen.') }[verdict]
      .replace('{n}', fmtInt(d.sel.size)), 'success', 3000);
    d.sel.clear();
    invalidate('queue', 'plan', 'recall');
    await load();
    loadPool(); refreshSummary();
  };
  load();
  openModal({
    title: t('Ausgeblendete prüfen: {r}', { r: serverText(rule.label) }), cls: 'modal-xl',
    body: () => {
      if (!d.items) return h('div', { class: 'muted' }, spinner(13), ' ', t('Lade …'));
      if (!d.items.length) return emptyState('check', t('Alles geprüft'), t('Diese Regel blendet nichts mehr aus, das noch zu prüfen wäre.'));
      const allOn = d.items.every(it => d.sel.has(it.id));
      return h('div', { class: 'stack-sm' },
        h('div', { class: 'row' },
          checkbox({ checked: allOn, indeterminate: !allOn && d.sel.size > 0, label: t('{n} ausgeblendet – alle wählen', { n: fmtInt(d.items.length) }),
            onChange: v => { d.sel = new Set(v ? d.items.map(it => it.id) : []); update(); } }),
          h('span', { class: 'spacer' }), h('span', { class: 'muted small' }, t('{n} gewählt', { n: fmtInt(d.sel.size) }))),
        h('div', { class: 'rs-quick' }, d.items.map(it => h('div', { key: it.id, class: ['rs-quick-row', d.sel.has(it.id) && 'on'] },
          checkbox({ checked: d.sel.has(it.id), onChange: v => { v ? d.sel.add(it.id) : d.sel.delete(it.id); update(); } }),
          h('div', { class: 'grow' },
            h('button', { type: 'button', class: 'rs-link rs-quick-title', onclick: () => { d.open[it.id] = !d.open[it.id]; update(); } }, it.title || t('(ohne Titel)')),
            h('div', { class: 'muted small' }, [it.year, authorsShort(it.authors), it.journal].filter(Boolean).join(' · '),
              it.no_abstract ? [' · ', h('span', { class: 'warn-text' }, t('nur Titel'))] : null),
            d.open[it.id] && h('p', { class: 'rs-abstract small' }, it.abstract || t('Kein Abstract.')))))));
    },
    actions: () => [
      { label: t('Schliessen'), onClick: closeModal },
      { label: t('Bleibt ausgeschlossen'), icon: 'x', disabled: !d.sel.size || isBusy('review'), onClick: () => act('exclude') },
      { label: t('Grenzfall'), icon: 'target', disabled: !d.sel.size || isBusy('review'), onClick: () => act('borderline') },
      { label: t('Zurückholen'), kind: 'primary', icon: 'undo', disabled: !d.sel.size || isBusy('review'), onClick: () => act('restore') }],
  });
}

// ------------------------------------------------------------------ Vorfilter
function ruleStats(x) {
  const parts = [];
  if (x.active) {
    parts.push(t('{n} ausgeblendet', { n: fmtInt(x.hidden || 0) }));
    if (x.exception) parts.push(t('{n} Grenzfälle (Ausnahme)', { n: fmtInt(x.exception) }));
    if (x.reviewed) parts.push(t('{n} geprüft', { n: fmtInt(x.reviewed) }));
  } else {
    parts.push(t('würde {n} ausblenden', { n: fmtInt(x.count || 0) }));
  }
  return parts.join(' · ');
}

function prefilterCard(pool) {
  const f = fst();
  const list = pool.prefilters;
  const toggle = (x, v) => savePrefilters(list.map(y => (y.id === x.id ? { ...y, active: v } : y)));
  const remove = x => savePrefilters(list.filter(y => y.id !== x.id));
  const add = () => {
    const pattern = f.newPattern.trim();
    if (!pattern && f.newKind !== 'type') return;
    let item;
    if (f.newKind === 'year_min') item = { kind: 'year_min', value: Number(pattern), active: true };
    else if (f.newKind === 'type') item = { kind: 'type', allowed: ['journalArticle'], active: true };
    else item = { kind: f.newKind, pattern, active: true, exceptions: '', exception_scope: 'text' };
    f.newPattern = '';
    savePrefilters([...list, item]);
  };
  const custom = x => [...PATTERN_KINDS, 'year_min', 'type'].includes(x.kind);
  return card(t('Vorfilter vor dem Screening'), 'filter', h('div', { class: 'stack-sm' },
    h('p', { class: 'muted small' }, t('Vorfilter markieren nur – kein Treffer verschwindet. Treffer mit einem Ausnahmebegriff werden Grenzfälle; Ausgeblendete lassen sich prüfen und zurückholen.')),
    h('div', { class: 'rs-prefilters' }, list.map(x => h('div', { key: x.id, class: ['rs-prefilter', x.active && 'active'] },
      checkbox({ checked: x.active, label: serverText(x.label), onChange: v => toggle(x, v) }),
      h('span', { class: 'muted small' }, ruleStats(x)),
      h('span', { class: 'spacer' }),
      x.active && x.hidden > 0 && btn(t('Ausgeblendete prüfen'), { size: 'sm', kind: 'ghost', icon: 'review', onClick: () => reviewHidden(x) }),
      PATTERN_KINDS.includes(x.kind) && iconBtn('edit', t('Bearbeiten (Muster, Ausnahmen)'), () => editRule(x, list)),
      custom(x) && iconBtn('x', t('Vorfilter entfernen'), () => remove(x))))),
    h('div', { class: 'row wrap rs-prefilter-add' },
      select({ value: f.newKind, options: [{ value: 'title', label: t('Titel enthält') }, { value: 'text', label: t('Titel/Abstract enthält') },
        { value: 'journal', label: t('Zeitschrift enthält') }, { value: 'year_min', label: t('erschienen vor') },
        { value: 'type', label: t('nur Zeitschriftenartikel') }], onChange: v => { f.newKind = v; update(); } }),
      f.newKind !== 'type' && h('div', { class: 'grow' }, textInput({ value: f.newPattern, placeholder: f.newKind === 'year_min' ? '2006' : 'bully* OR mobbing',
        onInput: v => { f.newPattern = v; update(); }, onKeyDown: e => { if (e.key === 'Enter') add(); } })),
      btn(t('Vorfilter hinzufügen'), { size: 'sm', icon: 'plus', disabled: f.newKind !== 'type' && !f.newPattern.trim(), onClick: add }))));
}

// ------------------------------------------------------------------ Abstracts nachladen
async function fetchAbstracts(retry = false) {
  const s = rs();
  const st = ui('rs-abstracts', {});
  st.run = { checked: 0, filled: 0, by: {}, errors: [] };
  update();
  try {
    for (;;) {
      if (!st.run) break;  // angehalten
      const r = await run(() => api.post(`${R}/projects/${s.pid}/abstracts`, { limit: 25, retry }));
      if (!st.run) break;
      st.run.checked += r.checked; st.run.filled += r.filled; st.run.remaining = r.remaining;
      for (const [k, v] of Object.entries(r.by_source)) st.run.by[k] = (st.run.by[k] || 0) + v;
      st.run.errors = [...new Set([...st.run.errors, ...r.errors])];
      update();
      if (!r.remaining || !r.checked) break;
    }
    const done = st.run;
    if (done) {
      toast(t('{f} von {c} Abstracts nachgeladen ({by}).', { f: fmtInt(done.filled), c: fmtInt(done.checked),
        by: Object.entries(done.by).map(([k, v]) => `${k} ${v}`).join(', ') || '–' }), 'success', 8000);
      done.errors.forEach(e => toast(e, 'warning', 10000));
    }
  } catch { /* Meldung kam schon */ } finally {
    st.run = null;
    invalidate('queue');
    loadPool(); refreshSummary();
  }
}

function abstractsNotice(pool) {
  const st = ui('rs-abstracts', {});
  if (st.run) {
    const r = st.run;
    const total = r.checked + (r.remaining ?? pool.abstracts_open);
    return notice('info', h('div', { class: 'stack-sm' },
      progress(r.checked, total, t('Abstracts nachladen: {c} geprüft, {f} gefunden', { c: fmtInt(r.checked), f: fmtInt(r.filled) })),
      h('div', { class: 'notice-actions' }, btn(t('Anhalten'), { size: 'sm', kind: 'ghost', onClick: () => { st.run = null; update(); } }))));
  }
  if (!pool.no_abstract) return null;
  return notice(pool.abstracts_open ? 'warning' : 'info', h('div', null,
    t('{n} Treffer ohne Abstract – sie bleiben im Pool und erscheinen im Screening mit „nur Titel“.', { n: fmtInt(pool.no_abstract) }),
    pool.abstracts_open ? h('div', { class: 'notice-actions' },
      btn(t('Abstracts nachladen ({n})', { n: fmtInt(pool.abstracts_open) }), { size: 'sm', icon: 'download', onClick: () => fetchAbstracts(false),
        title: t('Reihenfolge: Crossref, PubMed, Semantic Scholar') }))
      : pool.abstracts_retry ? h('div', { class: 'notice-actions' },
        h('span', { class: 'muted small' }, t('Bei {n} Treffern war eine Quelle nicht erreichbar oder überlastet (z. B. Semantic Scholar ohne Schlüssel).', { n: fmtInt(pool.abstracts_retry) })),
        btn(t('Erneut versuchen'), { size: 'sm', icon: 'refresh', onClick: () => fetchAbstracts(true) }))
        : h('div', { class: 'muted small' }, t('Alle Quellen sind schon abgefragt.'))));
}

// ------------------------------------------------------------------ Recall-Check
function recallCard() {
  const s = rs();
  const st = ui(`rs-recall-${s.pid}`, { data: undefined, text: null, edit: false });
  if (st.data === undefined || needsLoad('recall')) {
    if (!s.busy['loading:recall']) {
      s.busy['loading:recall'] = true;
      api.get(`${R}/projects/${s.pid}/recall`).then(r => { st.data = r; s.recall = r; delete s.stale.recall; })
        .catch(() => { st.data = { papers: [], warnings: 0 }; }).finally(() => { delete s.busy['loading:recall']; update(); });
    }
  }
  const data = st.data;
  const save = async () => {
    st.data = await busy('recall-save', () => api.put(`${R}/projects/${s.pid}/key-papers`, { text: st.text || '' }));
    st.edit = false;
    refreshSummary();
  };
  const startEdit = () => { st.text = ((data && data.papers) || []).map(p => p.doi).join('\n'); st.edit = true; update(); };
  const KIND = { missing: 'danger', hidden: 'danger', borderline: 'warning', visible: 'neutral', include: 'success', exclude: 'neutral', maybe: 'warning' };
  return card(t('Recall-Check (Schlüsselarbeiten)'), 'target', h('div', { class: 'stack-sm' },
    h('p', { class: 'muted small' }, t('Bekannte Schlüsselarbeiten als DOIs. Die App warnt, wenn eine davon nicht gefunden oder still ausgeblendet wird.')),
    st.edit ? h('div', { class: 'stack-sm' },
      textArea({ value: st.text, rows: 6, class: 'rs-mono', placeholder: '10.1016/j.chb.2020.106297\n10.1016/j.acap.2019.11.001',
        onInput: v => { st.text = v; update(); } }),
      h('div', { class: 'muted small' }, t('Eine DOI pro Zeile, oder einfach eine Tabelle mit DOIs einfügen.')),
      h('div', { class: 'row' }, btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', onClick: () => { st.edit = false; update(); } }),
        btn(t('Prüfen'), { size: 'sm', kind: 'primary', busy: isBusy('recall-save'), onClick: save })))
      : h('div', { class: 'row' }, btn(data && data.papers.length ? t('Liste bearbeiten') : t('Schlüsselarbeiten eintragen'), { size: 'sm', icon: 'edit', onClick: startEdit }),
        data && data.papers.length ? h('span', { class: data.warnings ? 'danger-text small' : 'ok-text small' },
          data.warnings ? t('{n} Warnungen', { n: data.warnings }) : t('alle {n} gefunden und sichtbar', { n: data.papers.length })) : null),
    data && data.papers.length && !st.edit ? h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
      h('tbody', null, data.papers.map(p => h('tr', { key: p.doi },
        h('td', null, badge(p.message, KIND[p.status] || 'neutral')),
        h('td', null, h('div', { class: 'small' }, p.title || h('span', { class: 'muted' }, p.doi)),
          h('div', { class: 'muted small' }, h('a', { href: `https://doi.org/${p.doi}`, target: '_blank', rel: 'noopener' }, p.doi),
            p.no_abstract ? ` · ${t('nur Titel')}` : '', p.zotero ? ` · ${t('in Zotero')}` : '')))))))
      : null));
}

// ------------------------------------------------------------------ Liste
function filterBar(pool) {
  const f = fst();
  const set = (k, v) => { f[k] = v; f.limit = PAGE; update(); reload(); };
  return h('div', { class: 'rs-filterbar' },
    h('div', { class: 'rs-filter-search' }, textInput({ value: f.text, placeholder: t('Suchen in Titel und Abstract (z. B. teas* OR banter)'), onInput: v => set('text', v) })),
    select({ value: f.source, options: [{ value: '', label: t('alle Quellen') }, ...pool.sources.map(x => ({ value: x, label: sourceLabel(x) }))], onChange: v => set('source', v) }),
    select({ value: f.query, options: [{ value: '', label: t('alle Suchstrings') }, ...pool.queries.map(x => ({ value: x, label: x }))], onChange: v => set('query', v) }),
    select({ value: f.status, options: [{ value: '', label: t('alle Entscheide') }, { value: 'open', label: t('offen') }, { value: 'borderline', label: t('Grenzfälle') },
      { value: 'include', label: t('eingeschlossen') }, { value: 'maybe', label: t('unsicher') }, { value: 'exclude', label: t('ausgeschlossen') },
      { value: 'hidden', label: t('nur ausgeblendete') },
      ...(aiVisible() && (aiInfo().available || pool.items.some(it => it.ai)) ? [{ value: 'ai_include', label: t('KI: passend') }, { value: 'ai_borderline', label: t('KI: Grenzfall') },
        { value: 'ai_exclude', label: t('KI: nicht passend') }, { value: 'ai_none', label: t('KI: ohne Vorschlag') }] : [])],
    onChange: v => set('status', v) }),
    h('input', { class: 'input rs-year', type: 'number', placeholder: t('ab Jahr'), value: f.year_from, onchange: e => set('year_from', e.target.value) }),
    h('input', { class: 'input rs-year', type: 'number', placeholder: t('bis Jahr'), value: f.year_to, onchange: e => set('year_to', e.target.value) }),
    h('div', { class: 'rs-filter-journal' }, textInput({ value: f.journal, placeholder: t('Zeitschrift'), onInput: v => set('journal', v) })),
    h('input', { class: 'input rs-lang', placeholder: t('Sprache'), value: f.lang, title: t('Sprachcode, z. B. en'), oninput: e => set('lang', e.target.value) }),
    checkbox({ checked: f.show_hidden, label: t('Ausgeblendete zeigen'), onChange: v => set('show_hidden', v) }));
}

function row(it, project, labels) {
  const f = fst();
  const open = !!f.open[it.id];
  return [
    h('tr', { key: it.id, class: [it.hidden_by.length && 'rs-hidden'], onclick: () => { f.open[it.id] = !open; update(); } },
      h('td', { class: 'num muted' }, it.year || ''),
      h('td', null, h('div', { class: 'rs-title' }, it.title || t('(ohne Titel)')),
        h('div', { class: 'muted small' }, [authorsShort(it.authors), it.journal].filter(Boolean).join(' · '),
          it.no_abstract ? [' · ', h('span', { class: 'warn-text' }, t('nur Titel'))] : null)),
      h('td', null, sourceBadges(it.sources), h('div', { class: 'muted small rs-clamp1' }, it.queries.join(', '))),
      h('td', null, statusBadge(it.decision, project),
        it.ai && aiVisible() ? h('div', null, aiBadge(it.ai, project)) : null,
        it.borderline.some(b => b.where !== 'ai') ? h('div', { title: it.borderline.map(borderlineText).join('\n') }, badge(t('Grenzfall'), 'warning')) : null,
        it.zotero_key ? h('div', null, badge(t('in Zotero'), 'info')) : null,
        it.stale ? h('div', null, badge(t('nicht mehr in aktueller Suche'), 'neutral', t('Nur aus einer früheren Suche oder einem gelöschten Suchstring; bleibt, weil schon entschieden'))) : null,
        it.hidden_by.length ? h('div', { class: 'muted small', title: it.hidden_by.map(id => labels[id] || id).join('\n') }, t('ausgeblendet')) : null)),
    open && h('tr', { key: `d${it.id}`, class: 'rs-detail-row' }, h('td', { colspan: 4 },
      it.borderline.filter(b => b.where !== 'ai').map((b, i) => h('div', { key: i, class: 'warn-text small' }, borderlineText(b))),
      it.ai && aiVisible() ? h('div', { class: 'small' }, h('b', null, t('KI ({m}): ', { m: it.ai.model })), it.ai.reason,
        it.ai.criterion ? h('span', { class: 'muted' }, ` – ${it.ai.criterion}`) : null) : null,
      it.hidden_by.length ? h('div', { class: 'muted small' }, t('Ausgeblendet durch: {r}', { r: it.hidden_by.map(id => labels[id] || id).join('; ') })) : null,
      h('p', { class: 'rs-abstract' }, it.abstract || h('span', { class: 'muted' }, t('Kein Abstract.'))),
      h('div', { class: 'row wrap small muted' },
        it.doi && h('a', { href: `https://doi.org/${it.doi}`, target: '_blank', rel: 'noopener' }, `DOI ${it.doi}`),
        it.pmid && h('a', { href: `https://pubmed.ncbi.nlm.nih.gov/${it.pmid}/`, target: '_blank', rel: 'noopener' }, `PMID ${it.pmid}`),
        it.openalex_id && h('a', { href: `https://openalex.org/${it.openalex_id}`, target: '_blank', rel: 'noopener' }, it.openalex_id),
        !it.doi && it.url && h('a', { href: it.url, target: '_blank', rel: 'noopener' }, t('Quelle')),
        it.abstract_source && h('span', null, t('Abstract aus {s}', { s: it.abstract_source })),
        it.lang && h('span', null, it.lang), it.cited_by != null && h('span', null, t('{n}× zitiert', { n: it.cited_by })),
        btn(t('Im Screening öffnen'), { size: 'sm', kind: 'ghost', onClick: e => { e.stopPropagation(); openInScreening(it.id); } })))),
  ];
}

async function resetPool(pool) {
  const s = rs();
  const sum = s.project.summary || {};
  const ok = await confirmDialog(t('Pool zurücksetzen?'), h('div', { class: 'stack-sm' },
    h('p', null, t('Alle {n} Treffer dieses Projekts löschen – mit ihren Entscheiden ({d} gesichtet), Grenzfall-Kennzeichen und KI-Vorschlägen.',
      { n: fmtInt(pool.total), d: fmtInt(sum.screened || 0) })),
    h('p', { class: 'muted small' }, t('Suchstrings, Suchstrategie, Vorfilter und das Protokoll der Läufe bleiben. Danach unter Suche & Import neu suchen. In Zotero ändert sich nichts.'))),
  { ok: t('Zurücksetzen'), danger: true });
  if (!ok) return;
  const r = await busy('reset-pool', () => api.post(`${R}/projects/${s.pid}/pool/reset`, { confirm: true }));
  if (!r) return;
  toast(t('Pool zurückgesetzt: {n} Treffer und {d} Entscheide gelöscht.', { n: fmtInt(r.deleted), d: fmtInt(r.decisions) }), 'success', 6000);
  invalidate('pool', 'queue', 'plan', 'recall', 'runs');
  loadPool(); refreshSummary();
}

function openInScreening(rid) {
  const s = rs();
  const sc = ui('rs-screen', {});
  sc.status = 'all'; sc.jumpTo = rid;
  s.queue = null;  // andere Auswahl (alle): nicht die alte zeigen
  s.tab = 'screening';
  update();
}

export function poolTab() {
  const s = rs();
  const p = s.project;
  if (needsLoad('pool') && !s.busy['loading:pool']) loadPool();
  const pool = s.pool;
  if (!pool) return h('div', { class: 'view-body muted' }, t('Lade Pool …'));
  const f = fst();
  const sum = p.summary || {};
  const labels = Object.fromEntries(pool.prefilters.map(x => [x.id, serverText(x.label)]));
  return workspace('pool', h('div', { class: 'stack-lg' },
      h('div', { class: 'row wrap' },
        h('div', { class: 'grow' }, h('h2', null, t('Pool')),
          h('div', { class: 'muted' }, t('{n} eindeutige Treffer · {h} durch Vorfilter ausgeblendet · {v} zu sichten · {b} Grenzfälle',
            { n: fmtInt(pool.total), h: fmtInt(pool.hidden), v: fmtInt(pool.total - pool.hidden), b: fmtInt(sum.borderline || 0) }))),
        pool.total ? btn(t('Pool zurücksetzen …'), { icon: 'trash', kind: 'ghost', busy: isBusy('reset-pool'), onClick: () => resetPool(pool),
          title: t('Alle Treffer und Entscheide löschen, um neu zu suchen') }) : null,
        btn(t('Mit Zotero abgleichen'), { icon: 'zotero', busy: isBusy('zotero-match'), onClick: zoteroMatch,
          title: t('Liest die Zielbibliothek ({lib}) und markiert Treffer, die dort schon sind (DOI, PMID, Titel).', { lib: targetName(p) }) })),
      !pool.total ? emptyState('library', t('Der Pool ist leer'), t('Unter Suche & Import Suchstrings ausführen oder RIS-Dateien importieren.'))
        : h('div', { class: 'stack' },
          pool.stale ? notice('info', t('{n} Treffer stammen nur noch aus früheren Suchen oder gelöschten Suchstrings. Sie bleiben, weil sie schon entschieden sind, und sind mit „nicht mehr in aktueller Suche“ markiert.', { n: fmtInt(pool.stale) })) : null,
          sum.in_zotero ? notice('info', t('{n} Treffer sind schon in Zotero ({lib}).', { n: fmtInt(sum.in_zotero), lib: targetName(p) })) : null,
          abstractsNotice(pool),
          filterBar(pool),
          h('div', { class: 'muted small' }, t('{n} angezeigt', { n: fmtInt(pool.items.length) }), s.busy['loading:pool'] ? ' …' : ''),
          h('div', { class: 'table-wrap card rs-table-card' }, h('table', { class: 'grid clickable rs-pool' },
            h('thead', null, h('tr', null, h('th', { class: 'num' }, t('Jahr')), h('th', null, t('Titel')), h('th', null, t('Fundstelle')), h('th', null, t('Stand')))),
            h('tbody', null, pool.items.slice(0, f.limit).map(it => row(it, p, labels))))),
          pool.items.length > f.limit && h('div', { class: 'row center' },
            btn(t('Weitere {n} zeigen', { n: Math.min(PAGE, pool.items.length - f.limit) }), { onClick: () => { f.limit += PAGE; update(); } })))),
  [prefilterCard(pool), recallCard()]);
}
