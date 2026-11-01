// Übernommen aus LLMplot 4 (src/llmplot/web/js/core/vdom.js); einzige Änderung: applyValue schützt Eingaben.
// Kleiner virtueller DOM mit Schlüsselabgleich. Fokus, Auswahl und Scrollpositionen bleiben erhalten,
// weil vorhandene Elemente wiederverwendet statt neu erzeugt werden.
const SVG_NS = 'http://www.w3.org/2000/svg';
const SKIP = new Set(['key', 'ref', 'html', 'value', 'checked']);

export function h(tag, props, ...children) {
  props = props || {};
  const c = [];
  flatten(children, c);
  return { t: tag, p: props, c, k: props.key };
}

function flatten(list, out) {
  for (const item of list) {
    if (item == null || item === false || item === true) continue;
    if (Array.isArray(item)) flatten(item, out);
    else if (typeof item === 'object') out.push(item);
    else out.push({ t: '#text', v: String(item), p: {}, c: [] });
  }
}

function dispatch(e) {
  const handler = this.__h && this.__h[e.type];
  if (handler) handler(e);
}

function classValue(v) {
  if (!v) return '';
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.filter(Boolean).map(classValue).join(' ');
  return Object.keys(v).filter(k => v[k]).join(' ');
}

function setProp(el, key, prev, next, svg) {
  if (key.startsWith('on') && key.length > 2) {
    const name = key.slice(2).toLowerCase();
    el.__h = el.__h || {};
    if (next) {
      if (!el.__h[name]) el.addEventListener(name, dispatch, name === 'wheel' ? { passive: false } : false);
      el.__h[name] = next;
    } else if (el.__h[name]) {
      el.removeEventListener(name, dispatch);
      delete el.__h[name];
    }
    return;
  }
  if (key === 'class' || key === 'className') {
    const v = classValue(next);
    if (svg) el.setAttribute('class', v); else if (el.className !== v) el.className = v;
    return;
  }
  if (key === 'style') {
    if (typeof next === 'string') { el.style.cssText = next; return; }
    const old = typeof prev === 'object' && prev ? prev : {};
    const neu = next || {};
    for (const k in old) if (!(k in neu)) { if (k.startsWith('--')) el.style.removeProperty(k); else el.style[k] = ''; }
    for (const k in neu) {
      const v = neu[k] == null ? '' : String(neu[k]);
      if (k.startsWith('--')) el.style.setProperty(k, v); else if (el.style[k] !== v) el.style[k] = v;
    }
    return;
  }
  if (['disabled', 'selected', 'indeterminate', 'readOnly', 'multiple', 'hidden', 'open', 'draggable', 'spellcheck'].includes(key)) {
    if (key === 'draggable' || key === 'spellcheck') { el.setAttribute(key, next ? 'true' : 'false'); return; }
    el[key] = !!next;
    return;
  }
  if (next == null || next === false) el.removeAttribute(key);
  else el.setAttribute(key, next === true ? '' : String(next));
}

function applyProps(el, prev, next, svg) {
  for (const key in prev) if (!SKIP.has(key) && !(key in next)) setProp(el, key, prev[key], null, svg);
  for (const key in next) if (!SKIP.has(key) && prev[key] !== next[key]) setProp(el, key, prev[key], next[key], svg);
}

function applyValue(el, p) {
  if ('value' in p) {
    const v = p.value == null ? '' : String(p.value);
    // Ein Feld, in dem gerade getippt wird, nicht mit dem unveränderten alten Wert überschreiben (z. B. beim
    // regelmässigen Neuzeichnen). Ändert sich der Wert im Programm (Auswahl, Leeren nach dem Senden), gilt er.
    const typing = el === document.activeElement && el.__v === v;
    if (!typing && el.value !== v) el.value = v;
    el.__v = v;
  }
  if ('checked' in p) el.checked = !!p.checked;
}

function create(v, svg) {
  if (v.t === '#text') { v.el = document.createTextNode(v.v); return v.el; }
  const isSvg = svg || v.t === 'svg';
  const el = isSvg ? document.createElementNS(SVG_NS, v.t) : document.createElement(v.t);
  v.el = el;
  applyProps(el, {}, v.p, isSvg);
  if (v.p.html != null) el.innerHTML = v.p.html;
  else for (const child of v.c) el.appendChild(create(child, isSvg && v.t !== 'foreignObject'));
  applyValue(el, v.p);
  if (v.p.ref) v.p.ref(el);
  return el;
}

function patch(parent, old, neu, svg) {
  if (old.t !== neu.t || old.k !== neu.k) {
    const el = create(neu, svg);
    parent.replaceChild(el, old.el);
    return;
  }
  if (neu.t === '#text') {
    neu.el = old.el;
    if (old.v !== neu.v) old.el.nodeValue = neu.v;
    return;
  }
  const el = (neu.el = old.el);
  const isSvg = svg || neu.t === 'svg';
  applyProps(el, old.p, neu.p, isSvg);
  if (neu.p.html != null) {
    if (old.p.html !== neu.p.html) el.innerHTML = neu.p.html;
  } else {
    if (old.p.html != null) { el.innerHTML = ''; old.c = []; }
    patchChildren(el, old.c, neu.c, isSvg && neu.t !== 'foreignObject');
  }
  applyValue(el, neu.p);
  if (neu.p.ref) neu.p.ref(el);
}

function patchChildren(el, oldC, newC, svg) {
  const byKey = new Map();
  for (const c of oldC) if (c.k != null) byKey.set(c.k, c);
  const used = new Set();
  for (let i = 0; i < newC.length; i++) {
    const nc = newC[i];
    let oc = null;
    if (nc.k != null) oc = byKey.get(nc.k) || null;
    else if (oldC[i] && oldC[i].k == null && !used.has(oldC[i])) oc = oldC[i];
    if (oc && !used.has(oc) && oc.el && oc.el.parentNode === el) {
      used.add(oc);
      patch(el, oc, nc, svg);
      const ref = el.childNodes[i];
      if (nc.el !== ref) el.insertBefore(nc.el, ref || null);
    } else {
      const node = create(nc, svg);
      el.insertBefore(node, el.childNodes[i] || null);
    }
  }
  for (const oc of oldC) if (!used.has(oc) && oc.el && oc.el.parentNode === el) el.removeChild(oc.el);
}

export function render(vnode, container) {
  const old = container.__vnode;
  if (!old || !old.el || old.el.parentNode !== container) {
    container.textContent = '';
    container.appendChild(create(vnode, false));
  } else {
    patch(container, old, vnode, false);
  }
  container.__vnode = vnode;
}
