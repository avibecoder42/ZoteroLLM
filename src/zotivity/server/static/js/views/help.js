// Hilfe: Handbuch (Markdown je Sprache unter static/help/<code>.md) mit Inhaltsverzeichnis und Volltextsuche – offline.
// Suche: Treffer sind Überschriften, Absätze und Listenpunkte. Alle Wörter müssen vorkommen (Wortteile genügen,
// Gross-/Kleinschreibung, Akzente und ß/ss egal), "in Anführungszeichen" = genaue Wortfolge. Links stehen die
// Treffer mit Ausschnitt, im Handbuch sind alle Fundstellen markiert; Enter/↓ und Umschalt+Enter/↑ springen weiter.
// Neue Sprache: Datei static/help/<code>.md anlegen – fehlt sie, erscheint das deutsche Handbuch.
import { h } from '../core/vdom.js';
import { state, update, ui } from '../core/store.js';
import { t, language, LANGUAGES } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { iconBtn, spinner, segmented, notice, paneProps, splitter } from '../ui/components.js';
import { debounce } from '../core/util.js';
import { navigate, viewHeader } from './shell.js';

let terms = [];  // normalisierte Suchbegriffe (für die Markierung)

// Hilfe öffnen, optional an einem Kapitel (Überschrift oder Teil davon), z. B. openHelp('Suchen')
export function openHelp(chapter = null) {
  const st = ui('help', {});
  st.jump = chapter;
  navigate('help');
}

// ----------------------------------------------------------------------------- Laden und Zerlegen
async function load(lang) {
  for (const code of [lang, 'de']) {
    try {
      const r = await fetch(`/static/help/${code}.md`, { cache: 'no-cache' });
      if (r.ok) return { md: await r.text(), lang: code };
    } catch { /* nächste Sprache */ }
  }
  throw new Error(t('Die Hilfe konnte nicht geladen werden.'));
}

export function parseMarkdown(md) {
  const chapters = [];
  let cur = null;
  let list = null;
  let para = [];
  const flush = () => {
    if (para.length && cur) cur.blocks.push({ type: 'p', text: para.join(' ') });
    para = [];
  };
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (line.startsWith('# ')) continue;
    if (line.startsWith('## ')) { flush(); list = null; cur = { title: line.slice(3).trim(), blocks: [] }; chapters.push(cur); continue; }
    if (!cur) continue;
    if (line.startsWith('### ')) { flush(); list = null; cur.blocks.push({ type: 'h3', text: line.slice(4).trim() }); continue; }
    const li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (li) {
      flush();
      if (!list) { list = { type: /^\s*\d+\./.test(line) ? 'ol' : 'ul', items: [] }; cur.blocks.push(list); }
      list.items.push(li[1]);
      continue;
    }
    if (line.startsWith('> ')) { flush(); list = null; cur.blocks.push({ type: 'tip', text: line.slice(2) }); continue; }
    if (!line.trim()) { flush(); list = null; continue; }
    list = null;
    para.push(line.trim());
  }
  flush();
  return chapters;
}

// ----------------------------------------------------------------------------- Suche
const fold = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/ß/g, 'ss');

// Normalisierter Text mit Rückverweis auf die Position jedes Zeichens im Original (für die Markierung)
function normMap(text) {
  let s = '';
  const idx = [];
  for (let i = 0; i < text.length; i++) {
    for (const ch of fold(text[i])) { s += ch; idx.push(i); }
  }
  return { s, idx };
}

export function searchTerms(query) {
  const out = [];
  const re = /"([^"]+)"?|(\S+)/g;
  let m;
  while ((m = re.exec(query || ''))) {
    const v = fold(m[1] || m[2]).replace(/\s+/g, ' ').trim();
    if (v) out.push(v);
  }
  return [...new Set(out)];
}

export function findRanges(text, words) {
  if (!words.length || !text) return [];
  const { s, idx } = normMap(text);
  const ranges = [];
  for (const w of words) {
    let at = s.indexOf(w);
    while (at >= 0) {
      ranges.push([idx[at], idx[at + w.length - 1] + 1]);
      at = s.indexOf(w, at + w.length);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([...r]);
  }
  return merged;
}

function marked(text) {
  const ranges = findRanges(text, terms);
  if (!ranges.length) return [text];
  const out = [];
  let pos = 0;
  for (const [a, b] of ranges) {
    if (a > pos) out.push(text.slice(pos, a));
    out.push(h('mark', null, text.slice(a, b)));
    pos = b;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

const plain = text => String(text || '').replace(/\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*/g, (_m, a, b, c) => a || b || c);

function units(chapters) {
  const out = [];
  chapters.forEach((c, ci) => {
    out.push({ id: `help-${ci}-h`, ci, kind: 'h2', text: c.title, section: c.title, sub: '' });
    let sub = '';
    c.blocks.forEach((b, bi) => {
      if (b.type === 'h3') {
        sub = b.text;
        out.push({ id: `help-${ci}-${bi}`, ci, kind: 'h3', text: b.text, section: c.title, sub: '' });
      } else if (b.items) {
        b.items.forEach((it, k) => out.push({ id: `help-${ci}-${bi}-${k}`, ci, kind: 'li', text: plain(it), section: c.title, sub }));
      } else {
        out.push({ id: `help-${ci}-${bi}`, ci, kind: b.type, text: plain(b.text), section: c.title, sub });
      }
    });
  });
  return out;
}

// Ein Treffer braucht alle Wörter (Kapitel- und Abschnittstitel zählen mit), mindestens eines im eigenen Text
export function searchHelp(chapters, query) {
  const words = searchTerms(query);
  if (!words.length) return { words, hits: [] };
  const hits = [];
  for (const u of units(chapters)) {
    const own = fold(u.text);
    if (!words.some(w => own.includes(w))) continue;
    const hay = fold(`${u.section} ${u.sub} ${u.text}`);
    if (words.every(w => hay.includes(w))) hits.push(u);
  }
  return { words, hits };
}

function snippet(text, words, size = 120) {
  const first = findRanges(text, words)[0];
  if (!first || text.length <= size) return text;
  let start = Math.max(0, first[0] - Math.round(size * 0.35));
  let end = Math.min(text.length, start + size);
  start = Math.max(0, end - size);
  if (start > 0) { const sp = text.indexOf(' ', start); if (sp > 0 && sp < first[0]) start = sp + 1; }
  if (end < text.length) { const sp = text.lastIndexOf(' ', end); if (sp > first[1]) end = sp; }
  return (start > 0 ? '… ' : '') + text.slice(start, end) + (end < text.length ? ' …' : '');
}

// ----------------------------------------------------------------------------- Darstellung
function inline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(...marked(text.slice(last, m.index)));
    const tok = m[0];
    if (tok.startsWith('**')) out.push(h('strong', null, marked(tok.slice(2, -2))));
    else if (tok.startsWith('`')) out.push(h('code', null, marked(tok.slice(1, -1))));
    else out.push(h('em', null, marked(tok.slice(1, -1))));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(...marked(text.slice(last)));
  return out;
}

function reveal(id, { smooth = true, center = true } = {}) {
  requestAnimationFrame(() => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: center ? 'center' : 'start' });
    const hit = document.querySelector(`[data-hit="${id}"]`);
    if (hit) hit.scrollIntoView({ block: 'nearest' });
  });
}
const revealSoon = debounce(id => reveal(id, { smooth: false }), 250);

export function helpView() {
  const st = ui('help', { query: '', chapters: null, lang: null, loadedLang: null, loading: false, error: null, active: 0, jump: null });
  const lang = st.lang || language();
  if (st.loadedLang !== lang && !st.loading) {
    st.loading = true;
    load(lang).then(r => { st.chapters = parseMarkdown(r.md); st.loadedLang = lang; st.shownLang = r.lang; st.error = null; })
      .catch(err => { st.error = err.message; st.loadedLang = lang; })
      .finally(() => { st.loading = false; update(); });
  }
  const chapters = st.chapters || [];
  // Sprung an ein Kapitel (openHelp('…'))
  if (st.jump && chapters.length) {
    const q = st.jump.toLowerCase();
    const ci = chapters.findIndex(c => c.title.toLowerCase().includes(q));
    st.jump = null;
    if (ci >= 0) reveal(`help-${ci}`, { center: false });
  }
  const { words, hits } = searchHelp(chapters, st.query);
  terms = words;
  const searching = words.length > 0;
  if (st.active >= hits.length) st.active = 0;
  const active = searching && hits.length ? hits[st.active] : null;
  const go = i => {
    if (!hits.length) return;
    st.active = (i + hits.length) % hits.length;
    update();
    reveal(hits[st.active].id);
  };
  const setQuery = v => {
    st.query = v;
    st.active = 0;
    update();
    const first = searchHelp(chapters, v).hits[0];
    if (first) revealSoon(first.id);
  };
  const onKey = e => {
    if (e.key === 'Enter' || e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      go(st.active + (e.key === 'ArrowUp' || (e.key === 'Enter' && e.shiftKey) ? -1 : 1));
    } else if (e.key === 'Escape' && st.query) {
      e.preventDefault();
      e.stopPropagation();
      setQuery('');
    }
  };
  const hitIds = new Set(hits.map(u => u.id));
  const cls = id => [hitIds.has(id) && 'help-hit-unit', active && active.id === id && 'help-hit-active'];

  const contents = () => chapters.map((c, ci) => [
    h('button', { key: 'c' + ci, type: 'button', class: 'help-toc-item', onclick: () => reveal(`help-${ci}`, { center: false }) },
      h('span', { class: 'help-toc-num' }, ci + 1), h('span', null, c.title)),
    ...c.blocks.map((b, bi) => b.type === 'h3' ? h('button', { key: `s${ci}-${bi}`, type: 'button', class: 'help-toc-item sub',
      onclick: () => reveal(`help-${ci}-${bi}`, { center: false }) }, b.text) : null),
  ]);
  const results = () => {
    if (!hits.length) {
      return h('div', { class: 'help-empty muted small' }, h('p', null, t('Keine Treffer.')),
        h('p', null, t('Weniger oder kürzere Wörter versuchen; eine genaue Wortfolge in "Anführungszeichen".')));
    }
    const out = [];
    let chapter = -1;
    hits.forEach((u, i) => {
      if (u.ci !== chapter) {
        chapter = u.ci;
        out.push(h('div', { key: 'g' + u.ci, class: 'help-hit-group' }, `${u.ci + 1}  ${u.section}`));
      }
      out.push(h('button', { key: u.id, type: 'button', class: ['help-hit', i === st.active && 'active'], 'data-hit': u.id, onclick: () => go(i) },
        u.sub && u.kind !== 'h3' ? h('span', { class: 'help-hit-path' }, u.sub) : null,
        h('span', { class: ['help-hit-text', (u.kind === 'h2' || u.kind === 'h3') && 'heading'] }, marked(snippet(u.text, words)))));
    });
    return out;
  };

  const langs = LANGUAGES.map(l => ({ value: l.code, label: l.code.toUpperCase(), title: l.label }));
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Hilfe'), t('Handbuch zu Zotivity {v}', { v: (state.info && state.info.version) || '' }), [
      langs.length > 1 ? segmented({ size: 'sm', value: lang, onChange: v => { st.lang = v; update(); }, options: langs }) : null]),
    h('div', { class: 'help' },
      h('aside', { class: 'help-nav', ...paneProps('help', 300) },
        h('div', { class: 'help-search' },
          h('div', { class: 'tree-search' }, icon('search', 14),
            h('input', { class: 'input input-sm', id: 'help-search', value: st.query, placeholder: t('Hilfe durchsuchen …'), 'aria-label': t('Hilfe durchsuchen'),
              oninput: e => setQuery(e.target.value), onkeydown: onKey })),
          st.query ? iconBtn('x', t('Suche löschen'), () => setQuery('')) : null),
        searching && hits.length > 0 && h('div', { class: 'help-search-bar' },
          h('span', { class: 'muted small' }, t('Treffer {i} von {n}', { i: st.active + 1, n: hits.length })),
          h('span', { class: 'spacer' }),
          iconBtn('chevronUp', t('Vorheriger Treffer (Umschalt+Enter)'), () => go(st.active - 1)),
          iconBtn('chevronDown', t('Nächster Treffer (Enter)'), () => go(st.active + 1))),
        h('div', { class: 'help-toc' }, searching ? results() : contents()),
        splitter('help', { def: 300, min: 200, max: 560 })),
      h('div', { class: 'help-body' },
        st.error ? notice('error', st.error) : null,
        st.shownLang && st.shownLang !== lang ? notice('info', t('Die Hilfe gibt es noch nicht in dieser Sprache – angezeigt wird die deutsche Fassung.')) : null,
        st.loading && !chapters.length ? h('div', { class: 'center-pad' }, spinner(22)) : null,
        h('article', { class: 'prose help-doc' }, chapters.map((c, ci) => h('section', { key: `${st.loadedLang}-${ci}`, id: `help-${ci}`, class: 'help-chapter' },
          h('h2', { id: `help-${ci}-h`, class: cls(`help-${ci}-h`) }, h('span', { class: 'help-num' }, ci + 1), marked(c.title)),
          c.blocks.map((b, j) => {
            const id = `help-${ci}-${j}`;
            if (b.type === 'h3') return h('h3', { key: j, id, class: cls(id) }, marked(b.text));
            if (b.type === 'p') return h('p', { key: j, id, class: cls(id) }, inline(b.text));
            if (b.type === 'tip') return h('div', { key: j, id, class: ['help-tip', ...cls(id)] }, icon('info', 15), h('span', null, inline(b.text)));
            return h(b.type, { key: j }, b.items.map((it, k) => h('li', { key: k, id: `${id}-${k}`, class: cls(`${id}-${k}`) }, inline(it))));
          })))))));
}
