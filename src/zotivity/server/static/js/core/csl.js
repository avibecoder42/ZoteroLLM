// CSL im Browser: citeproc-js laden (dieselbe Software rendert in Zotero), Beispiele rendern und jeden Teil der
// Ausgabe dem Element im Stil zuordnen, aus dem er stammt.
//
// Zuordnung: Jedes Element mit Präfix/Suffix bekommt unsichtbare Marker (Zeichen aus dem Privatbereich von Unicode)
// vor und nach seiner Ausgabe. citeproc-js gibt Affixe nur aus, wenn das Element etwas ausgibt – die Marker umschliessen
// also genau seine Ausgabe. Angezeigt wird die unveränderte Ausgabe; die Marker-Fassung liefert nur die Zuordnung
// (über einen Zeichenabgleich, falls citeproc-js wegen der Marker Satzzeichen anders zusammenzieht).

export const NS = 'http://purl.org/net/xbiblio/csl';
const AFFIX_TAGS = new Set(['text', 'names', 'name', 'name-part', 'date', 'date-part', 'number', 'label', 'group']);
const OPEN = '';
const CLOSE = '';
const ID_BASE = 0xE100;

// -- Laden ---------------------------------------------------------------------------------------------------------
let loading = null;
export function loadCiteproc() {
  if (window.CSL && window.CSL.Engine) return Promise.resolve(window.CSL);
  if (loading) return loading;
  const add = src => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`${src} nicht geladen`));
    document.head.appendChild(s);
  });
  loading = add('/static/vendor/citeproc/shim.js')
    .then(() => add('/static/vendor/citeproc/citeproc_commonjs.js'))
    .then(() => { try { delete window.module; } catch { window.module = undefined; } return window.CSL; })
    .catch(err => { loading = null; throw err; });
  return loading;
}

// Mitgelieferte Sprachdateien; andere Sprachen fallen auf die Hauptsprache bzw. Englisch zurück
export const LOCALES = ['de-DE', 'de-AT', 'de-CH', 'en-US', 'en-GB', 'fr-FR', 'it-IT'];
const PRIMARY = { de: 'de-DE', en: 'en-US', fr: 'fr-FR', it: 'it-IT' };
const localeCache = {};

export function localeTag(tag) {
  if (!tag) return 'en-US';
  if (LOCALES.includes(tag)) return tag;
  return PRIMARY[String(tag).slice(0, 2).toLowerCase()] || 'en-US';
}

export async function preloadLocales(tags) {
  const wanted = [...new Set(['en-US', ...tags.filter(Boolean).map(localeTag)])];
  await Promise.all(wanted.filter(t => !(t in localeCache)).map(async t => {
    const r = await fetch(`/static/vendor/csl-locales/locales-${t}.xml`);
    localeCache[t] = r.ok ? await r.text() : null;
  }));
}

function retrieveLocale(tag) {
  return localeCache[localeTag(tag)] || localeCache['en-US'] || false;
}

// -- Stil als XML-Dokument -----------------------------------------------------------------------------------------
export function parseStyle(xml) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const err = doc.getElementsByTagName('parsererror')[0];
  if (err) {
    // Chromium: „This page contains the following errors: error on line 3 at column 7: …“ – nur die Fundstelle
    const m = (err.textContent || '').match(/line (\d+) at column (\d+): ([^\n]+)/);
    throw new Error(m ? `Zeile ${m[1]}, Spalte ${m[2]}: ${m[3].trim()}` : (err.textContent || 'XML-Fehler').split('\n').filter(Boolean)[0]);
  }
  if (!doc.documentElement || doc.documentElement.localName !== 'style') throw new Error('Keine CSL-Datei (Wurzelelement <style> fehlt).');
  return doc;
}

export function serializeStyle(doc, original = '') {
  let xml = new XMLSerializer().serializeToString(doc);
  const decl = (original.match(/^\s*<\?xml[^>]*\?>/) || [])[0];
  if (decl && !xml.startsWith('<?xml')) xml = decl.trim() + '\n' + xml;
  return xml;
}

// Alle Elemente in Dokumentreihenfolge – der Index ist die Kennung in den Markern
export function elements(doc) {
  return [...doc.getElementsByTagNameNS(NS, '*')];
}

export function styleInfo(doc) {
  const info = doc.getElementsByTagNameNS(NS, 'info')[0];
  const get = tag => (info && info.getElementsByTagNameNS(NS, tag)[0] || {}).textContent || '';
  const cat = info ? [...info.getElementsByTagNameNS(NS, 'category')] : [];
  return {
    title: get('title').trim(), id: get('id').trim(),
    format: (cat.find(c => c.getAttribute('citation-format')) || { getAttribute: () => '' }).getAttribute('citation-format') || '',
    locale: doc.documentElement.getAttribute('default-locale') || '',
    hasBibliography: !!doc.getElementsByTagNameNS(NS, 'bibliography')[0],
  };
}

function instrumented(doc) {
  const copy = doc.cloneNode(true);
  elements(copy).forEach((el, i) => {
    if (!AFFIX_TAGS.has(el.localName) || i > 0x0F00) return;
    const mark = String.fromCharCode(ID_BASE + i);
    el.setAttribute('prefix', OPEN + mark + (el.getAttribute('prefix') || ''));
    el.setAttribute('suffix', (el.getAttribute('suffix') || '') + CLOSE + mark);
  });
  return new XMLSerializer().serializeToString(copy);
}

// -- Rendern -------------------------------------------------------------------------------------------------------
// items: { id: CSL-JSON }. Rückgabe je Beispiel: Beleg im Text und Eintrag im Literaturverzeichnis (HTML), dazu die
// Zuordnung als Liste von Abschnitten [{text, path:[Elementindizes]}].
export function render(xml, items, lang, { mapping = true } = {}) {
  const CSL = window.CSL;
  const ids = Object.keys(items);
  const run = styleXml => {
    const engine = new CSL.Engine({ retrieveLocale, retrieveItem: id => items[id] }, styleXml, localeTag(lang), true);
    engine.updateItems(ids);
    const out = { cites: {}, bib: {} };
    for (const id of ids) {
      const loc = items[id].__locator;
      const cite = loc ? { id, locator: loc, label: 'page' } : { id };
      try {
        out.cites[id] = engine.makeCitationCluster([cite]);
      } catch (e) {
        out.cites[id] = '';
        out.error = out.error || e.message;
      }
    }
    try {
      const bib = engine.makeBibliography();  // false, wenn der Stil kein Literaturverzeichnis hat
      if (bib) {
        const [params, entries] = bib;
        params.entry_ids.forEach((eid, i) => { out.bib[eid[0]] = entries[i]; });
        out.bibParams = params;
      }
    } catch (e) {
      out.error = out.error || e.message;
    }
    return out;
  };
  const clean = run(xml);
  if (!mapping) return { clean, marked: null };
  let marked = null;
  try {
    marked = run(instrumented(parseStyle(xml)));
  } catch {
    marked = null;  // Zuordnung ist ein Komfort – die Vorschau gilt auch ohne
  }
  return { clean, marked };
}

// HTML der Ausgabe → DOM-Fragment mit <span class="csl-node" data-path="3 7 12"> um zugeordnete Textstücke
export function annotate(cleanHtml, markedHtml) {
  const tpl = document.createElement('template');
  tpl.innerHTML = cleanHtml || '';
  if (!markedHtml) return tpl.content;
  const chars = markedChars(markedHtml);
  const plain = chars.map(c => c.ch).join('');
  const walker = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
  const texts = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) texts.push(n);
  const cleanText = texts.map(n => n.data).join('');
  const align = cleanText === plain ? null : alignChars(cleanText, plain);
  let pos = 0;
  for (const node of texts) {
    const frag = document.createDocumentFragment();
    let run = '';
    let runPath = null;
    const flush = () => {
      if (!run) return;
      if (runPath && runPath.length) {
        const span = document.createElement('span');
        span.className = 'csl-node';
        span.dataset.path = runPath.join(' ');
        span.textContent = run;
        frag.appendChild(span);
      } else {
        frag.appendChild(document.createTextNode(run));
      }
      run = '';
    };
    for (const ch of node.data) {
      const j = align ? align[pos] : pos;
      const path = j != null && j >= 0 && chars[j] ? chars[j].path : null;
      const key = path ? path.join(' ') : '';
      if (runPath === null || key !== (runPath ? runPath.join(' ') : '')) { flush(); runPath = path || []; }
      run += ch;
      pos++;
    }
    flush();
    node.parentNode.replaceChild(frag, node);
  }
  return tpl.content;
}

// Text der Marker-Ausgabe mit dem jeweils offenen Elementpfad je Zeichen
function markedChars(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html || '';
  const out = [];
  const stack = [];
  const text = tpl.content.textContent || '';
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if ((c === OPEN || c === CLOSE) && i + 1 < text.length) {
      const id = text.charCodeAt(i + 1) - ID_BASE;
      if (c === OPEN) stack.push(id);
      else {
        const at = stack.lastIndexOf(id);
        if (at >= 0) stack.splice(at, 1);
      }
      i++;
      continue;
    }
    out.push({ ch: c, path: stack.slice() });
  }
  return out;
}

// Zeichenabgleich (längste gemeinsame Teilfolge): Index in b für jedes Zeichen von a, sonst -1
function alignChars(a, b) {
  const n = a.length;
  const m = b.length;
  if (n * m > 4_000_000) return null;
  const dp = new Uint16Array((n + 1) * (m + 1));
  const w = m + 1;
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = a[i] === b[j] ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
    }
  }
  const res = new Array(n).fill(-1);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { res[i] = j; i++; j++; } else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) i++; else j++;
  }
  return res;
}

// -- Beschreibung eines Elements ------------------------------------------------------------------------------------
// Wo liegt das Element? Pfad bis zu citation/bibliography/macro (für die Anzeige) und Makro-Name
export function context(el) {
  const chain = [];
  let macro = null;
  let area = null;
  for (let p = el; p && p.nodeType === 1; p = p.parentNode) {
    if (p.localName === 'macro') macro = p.getAttribute('name');
    if (p.localName === 'citation' || p.localName === 'bibliography') area = p.localName;
    chain.unshift(p);
  }
  return { macro, area, chain };
}

// An wie vielen Stellen in Belegen und Literaturverzeichnis ein Makro wirkt: Aufrufe aus anderen Makros zählen so
// oft, wie jene selbst verwendet werden (Sortierschlüssel nicht – sie geben nichts aus)
export function macroUses(doc, name, seen = new Set()) {
  if (seen.has(name)) return 0;
  seen.add(name);
  let n = 0;
  for (const call of doc.getElementsByTagNameNS(NS, 'text')) {
    if (call.getAttribute('macro') !== name) continue;
    const { macro } = context(call);
    n += macro ? macroUses(doc, macro, new Set(seen)) : 1;
  }
  return n;
}

// Aus welchen Teilen (citation, bibliography) ein Makro ausgegeben wird – auch über andere Makros: { name: Set }
export function macroAreas(doc) {
  const callees = {};
  for (const m of doc.getElementsByTagNameNS(NS, 'macro')) {
    callees[m.getAttribute('name')] = [...m.getElementsByTagNameNS(NS, 'text')].map(c => c.getAttribute('macro')).filter(Boolean);
  }
  const areas = {};
  const visit = (name, area, seen) => {
    if (seen.has(name) || !(name in callees)) return;
    seen.add(name);
    (areas[name] = areas[name] || new Set()).add(area);
    for (const c of callees[name]) visit(c, area, seen);
  };
  for (const area of ['citation', 'bibliography']) {
    const root = doc.getElementsByTagNameNS(NS, area)[0];
    if (!root) continue;
    const seen = new Set();
    for (const c of root.getElementsByTagNameNS(NS, 'text')) if (c.getAttribute('macro')) visit(c.getAttribute('macro'), area, seen);
  }
  return areas;
}

export const isShared = (areas, name) => !!areas[name] && areas[name].size === 2;

// Änderung nur im Text bzw. nur im Verzeichnis: Das Makro und alle gemeinsam genutzten Makros, über die dieser Teil
// es erreicht, bekommen für ihn eine Kopie („…-bibliography“ bzw. „…-citation“); seine Aufrufe (auch Sortierschlüssel)
// zeigen danach auf die Kopien, der andere Teil verwendet weiter die Originale.
// Rückgabe: Zuordnung Original-Element → Element in der Kopie, oder null, wenn das Makro nicht geteilt ist.
export function separateMacro(doc, name, area) {
  const areas = macroAreas(doc);
  if (!isShared(areas, name)) return null;
  const macros = {};
  for (const m of doc.getElementsByTagNameNS(NS, 'macro')) macros[m.getAttribute('name')] = m;
  const calls = () => [...doc.getElementsByTagNameNS(NS, 'text'), ...doc.getElementsByTagNameNS(NS, 'key')].filter(c => c.getAttribute('macro'));
  // Gemeinsam genutzte Aufrufer gehören dazu, sonst bliebe die Kopie über sie unerreichbar
  const copy = new Set([name]);
  for (let grew = true; grew;) {
    grew = false;
    for (const c of calls()) {
      const { macro: ctx } = context(c);
      if (copy.has(c.getAttribute('macro')) && ctx && isShared(areas, ctx) && !copy.has(ctx)) { copy.add(ctx); grew = true; }
    }
  }
  const suffix = area === 'bibliography' ? 'bibliography' : 'citation';
  const names = {};
  const map = new Map();
  const taken = new Set(Object.keys(macros));
  for (const n of copy) {
    const orig = macros[n];
    let nn = `${n}-${suffix}`;
    for (let i = 2; taken.has(nn); i++) nn = `${n}-${suffix}-${i}`;
    taken.add(nn);
    names[n] = nn;
    const dup = orig.cloneNode(true);
    dup.setAttribute('name', nn);
    insertAfter(orig, dup);
    const a = [orig, ...orig.getElementsByTagNameNS(NS, '*')];
    const b = [dup, ...dup.getElementsByTagNameNS(NS, '*')];
    a.forEach((x, i) => map.set(x, b[i]));
  }
  const copies = new Set(Object.values(names));
  const only = ctx => copies.has(ctx) || (areas[ctx] && areas[ctx].size === 1 && areas[ctx].has(area));
  for (const c of calls()) {
    const target = names[c.getAttribute('macro')];
    if (!target) continue;
    const { macro: ctx, area: a } = context(c);
    if (ctx ? only(ctx) : a === area) c.setAttribute('macro', target);
  }
  return map;
}

export function createElement(doc, tag, attrs = {}) {
  const el = doc.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== '') el.setAttribute(k, v);
  return el;
}

// Nächstes/vorheriges Geschwister-Element (Text und Kommentare zwischen den Elementen bleiben stehen)
export function siblingElement(el, dir) {
  let s = dir < 0 ? el.previousSibling : el.nextSibling;
  while (s && s.nodeType !== 1) s = dir < 0 ? s.previousSibling : s.nextSibling;
  return s;
}

// Verschieben: mit dem Nachbarn tauschen; am Rand einer Gruppe verlässt das Element sie (davor bzw. danach).
// Bedingungen, Bausteine, Datum, Namen und das Layout verlässt es nicht.
export function canMove(el, dir) {
  return !!siblingElement(el, dir) || el.parentNode.localName === 'group';
}

export function moveElement(el, dir) {
  const other = siblingElement(el, dir);
  const parent = el.parentNode;
  if (other) parent.insertBefore(el, dir < 0 ? other : other.nextSibling);
  else if (parent.localName === 'group') parent.parentNode.insertBefore(el, dir < 0 ? parent : parent.nextSibling);
  else return false;
  return true;
}

// Ganz nach vorne bzw. hinten: an den Anfang bzw. das Ende der äussersten Gruppe, in der das Element steht
function edgeBox(el) {
  let box = el.parentNode;
  while (box.localName === 'group' && box.parentNode.localName === 'group') box = box.parentNode;
  const kids = [...box.children];
  return { box, first: kids[0], last: kids[kids.length - 1] };
}

export function canMoveToEdge(el, dir) {
  const { first, last } = edgeBox(el);
  return (dir < 0 ? first : last) !== el;
}

export function moveToEdge(el, dir) {
  const { box, first, last } = edgeBox(el);
  if ((dir < 0 ? first : last) === el) return false;
  box.insertBefore(el, dir < 0 ? first : last.nextSibling);
  return true;
}

// Weg zu einem angeklickten Teil über die Aufrufe der Bausteine: Text bzw. Verzeichnis › … › Aufruf eines Bausteins ›
// … im Baustein › … › Teil. path: Elemente aus der Zuordnung (aussen → innen); passt er nicht zur Struktur: null.
export function pathChain(path) {
  if (!path || !path.length) return null;
  const last = path[path.length - 1];
  const ends = path.filter(p => p.localName === 'text' && p.getAttribute('macro'));
  if (ends[ends.length - 1] !== last) ends.push(last);
  const out = [];
  let macro = null;
  for (const end of ends) {
    const seg = [];
    let p = end;
    for (; p && p.nodeType === 1; p = p.parentNode) {
      seg.unshift(p);
      if (macro ? p.localName === 'macro' && p.getAttribute('name') === macro : p.localName === 'citation' || p.localName === 'bibliography') break;
    }
    if (!p || p.nodeType !== 1) return null;
    if (macro) seg.shift();  // das Makro selbst nicht – sein Aufruf steht schon davor
    out.push(...seg);
    macro = end.getAttribute('macro');
  }
  return out;
}

export function removeElement(el) {
  const parent = el.parentNode;
  // Einrückung davor mitnehmen, damit keine Leerzeilen zurückbleiben
  const prev = el.previousSibling;
  if (prev && prev.nodeType === 3 && /^\s*$/.test(prev.data)) parent.removeChild(prev);
  parent.removeChild(el);
}

export function insertAfter(ref, el) {
  const indent = ref.previousSibling && ref.previousSibling.nodeType === 3 ? ref.previousSibling.data : '';
  const parent = ref.parentNode;
  const next = ref.nextSibling;
  if (indent && /^\s*$/.test(indent)) parent.insertBefore(ref.ownerDocument.createTextNode(indent), next);
  parent.insertBefore(el, next);
}

// Stelle im XML-Text, an der ein Element beginnt (für den Code-Modus)
export function sourceRange(doc, el, original) {
  const MARK = 'data-zotivity-sel';
  el.setAttribute(MARK, '1');
  const xml = serializeStyle(doc, original);
  el.removeAttribute(MARK);
  const at = xml.indexOf(MARK + '="1"');
  if (at < 0) return null;
  const start = xml.lastIndexOf('<', at);
  const end = xml.indexOf('>', at) + 1;
  // Ohne das Hilfsattribut liegt das Tag-Ende entsprechend früher
  return { start, end: end - (MARK.length + 5) };
}
