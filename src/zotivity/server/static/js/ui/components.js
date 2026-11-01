// Wiederverwendbare Bedienelemente als reine Funktionen (Zustand liegt im Store).
import { h } from '../core/vdom.js';
import { state, update, ui } from '../core/store.js';
import { icon } from './icons.js';
import { t } from '../core/i18n.js';

export function btn(label, opts = {}) {
  const { icon: ic, onClick, kind = 'secondary', size = '', disabled = false, key, title, busy = false, why } = opts;
  const tip = disabled && why ? `${title || label}\n${why}` : title;
  return h('button', {
    key, type: 'button', class: ['btn', `btn-${kind}`, size && `btn-${size}`, !label && 'btn-icon'],
    disabled: disabled || busy, title: tip || undefined, 'aria-label': tip || label || undefined,
    onclick: e => { if (!disabled && !busy && onClick) onClick(e); },
  }, busy ? spinner(size === 'sm' ? 13 : 15) : ic && icon(ic, size === 'sm' ? 15 : 17), label && h('span', null, label));
}

export function iconBtn(ic, title, onClick, opts = {}) {
  return btn('', { icon: ic, title, onClick, kind: opts.kind || 'ghost', size: opts.size || 'sm', disabled: opts.disabled, key: opts.key });
}

export function spinner(size = 14) {
  return h('span', { class: 'spinner', style: { width: size + 'px', height: size + 'px' } });
}

// Fortschrittsring, der sich mit dem Anteil (0–1) füllt; ohne bekannten Anteil ein Ladekreisel
export function progressRing(fraction, size = 16, title) {
  if (fraction == null || !isFinite(fraction)) return spinner(size);
  const f = Math.max(0, Math.min(1, fraction));
  const r = 7;
  const c = 2 * Math.PI * r;
  return h('svg', { class: 'ring', viewBox: '0 0 18 18', width: size, height: size, role: 'img', 'aria-label': title || `${Math.round(f * 100)} %` },
    title ? h('title', null, title) : null,
    h('circle', { class: 'ring-track', cx: 9, cy: 9, r, fill: 'none', 'stroke-width': 2.5 }),
    h('circle', { class: 'ring-fill', cx: 9, cy: 9, r, fill: 'none', 'stroke-width': 2.5, 'stroke-linecap': 'round',
      'stroke-dasharray': `${(c * f).toFixed(2)} ${c.toFixed(2)}`, transform: 'rotate(-90 9 9)' }));
}

// Feld mit Beschriftung; Erklärungen hinter ⓘ (help) oder als Zeile darunter (hint)
export function field(label, control, opts = {}) {
  const { help, hint, key, error } = opts;
  return h('div', { key, class: ['field', error && 'field-error'] },
    label != null && h('div', { class: 'field-head' },
      h('label', { class: 'field-label' }, label),
      help && h('span', { class: 'field-info', tabindex: 0, role: 'img', 'aria-label': help, title: help }, icon('info', 13))),
    control,
    hint && h('div', { class: 'field-hint' }, hint),
    error && h('div', { class: 'field-errtext' }, error));
}

export function textInput(o) {
  return h('input', {
    key: o.key, class: ['input', o.class], type: o.type || 'text', value: o.value ?? '', placeholder: o.placeholder || '',
    disabled: o.disabled, spellcheck: o.spellcheck === true, autocomplete: 'off', id: o.id, 'aria-label': o.label,
    oninput: o.onInput && (e => o.onInput(e.target.value, e)),
    onchange: o.onChange && (e => o.onChange(e.target.value, e)),
    onkeydown: o.onKeyDown, ref: o.ref,
  });
}

export function textArea(o) {
  return h('textarea', {
    key: o.key, class: ['input', 'textarea', o.class], rows: o.rows || 3, value: o.value ?? '', placeholder: o.placeholder || '',
    disabled: o.disabled, 'aria-label': o.label, id: o.id, ref: o.ref,
    oninput: o.onInput && (e => o.onInput(e.target.value, e)),
    onchange: o.onChange && (e => o.onChange(e.target.value, e)), onkeydown: o.onKeyDown,
  });
}

export function select(o) {
  return h('div', { class: ['select-wrap', o.class], key: o.key },
    h('select', { class: 'input select', disabled: o.disabled, 'aria-label': o.label, onchange: e => o.onChange && o.onChange(e.target.value) },
      (o.options || []).map(opt => {
        const it = typeof opt === 'object' ? opt : { value: opt, label: opt };
        return h('option', { value: it.value, selected: String(it.value) === String(o.value ?? ''), disabled: it.disabled }, it.label);
      })),
    icon('chevronDown', 14, 'select-caret'));
}

export function toggle(o) {
  return h('label', { class: ['toggle', o.disabled && 'disabled'], key: o.key, title: o.title },
    h('input', { type: 'checkbox', checked: !!o.checked, disabled: o.disabled, onchange: e => o.onChange && o.onChange(e.target.checked) }),
    h('span', { class: 'toggle-track' }, h('span', { class: 'toggle-thumb' })),
    o.label && h('span', { class: 'toggle-label' }, o.label));
}

export function checkbox(o) {
  return h('label', { class: ['checkbox', o.disabled && 'disabled', o.indeterminate && 'is-indeterminate', o.class], key: o.key, title: o.title,
    onclick: e => e.stopPropagation() },
  h('input', { type: 'checkbox', checked: !!o.checked, disabled: o.disabled, onchange: e => o.onChange && o.onChange(e.target.checked) }),
  h('span', { class: 'checkbox-box' }, icon(o.indeterminate ? 'minus' : 'check', 12)),
  o.label && h('span', { class: 'checkbox-label' }, o.label));
}

export function segmented(o) {
  return h('div', { class: ['segmented', o.size && `segmented-${o.size}`, o.class], role: 'radiogroup', key: o.key },
    (o.options || []).map(opt => h('button', {
      type: 'button', class: ['seg', String(opt.value) === String(o.value) && 'active'], role: 'radio',
      'aria-checked': String(opt.value) === String(o.value) ? 'true' : 'false', title: opt.title || undefined, disabled: o.disabled || opt.disabled,
      onclick: () => o.onChange && o.onChange(opt.value),
    }, opt.icon && icon(opt.icon, 15), opt.label && h('span', null, opt.label), opt.badge && h('span', { class: 'seg-badge' }, opt.badge))));
}

export function numberInput(o) {
  const clamp = v => {
    let n = Number(v);
    if (!isFinite(n)) return null;
    if (o.min != null) n = Math.max(o.min, n);
    if (o.max != null) n = Math.min(o.max, n);
    return n;
  };
  const commit = v => { if (v === '' && o.nullable) { o.onChange(null); return; } const n = clamp(v); if (n != null) o.onChange(o.int ? Math.round(n) : n); };
  const step = o.step || 1;
  return h('div', { class: ['number', o.class], key: o.key },
    h('button', { type: 'button', class: 'number-step', tabindex: -1, disabled: o.disabled, 'aria-label': '−',
      onclick: () => commit((Number(o.value) || 0) - step) }, icon('minus', 13)),
    h('input', { class: 'input number-input', type: 'number', value: o.value ?? '', min: o.min, max: o.max, step: o.int ? 1 : 'any',
      placeholder: o.placeholder || '', disabled: o.disabled, onchange: e => commit(e.target.value), 'aria-label': o.label,
      onwheel: e => { if (document.activeElement === e.currentTarget) e.currentTarget.blur(); } }),
    h('button', { type: 'button', class: 'number-step', tabindex: -1, disabled: o.disabled, 'aria-label': '+',
      onclick: () => commit((Number(o.value) || 0) + step) }, icon('plus', 13)));
}

export function badge(text, kind = 'neutral', title) {
  return h('span', { class: `badge badge-${kind}`, title }, text);
}

// Ausgeblendete Hinweise (×): dauerhaft (localStorage) oder bis zum Neustart (session); im Speicher als Rückfall.
// Der Schlüssel enthält, was den Hinweis ausmacht (z. B. Modell und Zahl der Texte) – ändert sich die Lage, erscheint
// er wieder.
const DISMISSED = 'zllm.dismissed';
const dismissedNow = new Set();
const dismissStore = session => { try { return session ? window.sessionStorage : window.localStorage; } catch { return null; } };

export function isDismissed(key, session = false) {
  if (dismissedNow.has(key)) return true;
  try { return JSON.parse(dismissStore(session).getItem(DISMISSED) || '[]').includes(key); } catch { return false; }
}

export function dismissNotice(key, session = false) {
  dismissedNow.add(key);
  try {
    const store = dismissStore(session);
    const list = JSON.parse(store.getItem(DISMISSED) || '[]').filter(k => k !== key);
    store.setItem(DISMISSED, JSON.stringify([...list, key].slice(-200)));
  } catch { /* privat: nur im Speicher */ }
}

// opts.dismiss: Schlüssel → Hinweis mit × zum Ausblenden; opts.session: nur bis zum nächsten Programmstart
export function notice(kind, text, extra, opts = {}) {
  if (opts.dismiss && isDismissed(opts.dismiss, opts.session)) return null;
  const ic = { error: 'alert', warning: 'alert', success: 'check', info: 'info' }[kind] || 'info';
  return h('div', { class: ['notice', `notice-${kind}`, opts.dismiss && 'notice-dismissible'], role: kind === 'error' ? 'alert' : 'note' },
    icon(ic, 16), h('div', { class: 'notice-body' }, text, extra),
    opts.dismiss && h('button', { type: 'button', class: 'notice-close', title: t('Hinweis ausblenden'), 'aria-label': t('Hinweis ausblenden'),
      onclick: e => { e.stopPropagation(); dismissNotice(opts.dismiss, opts.session); update(); } }, icon('x', 13)));
}

export function progress(done, total, label) {
  const pct = total ? Math.min(100, Math.round((100 * done) / total)) : null;
  return h('div', { class: 'progress' },
    h('div', { class: 'progress-bar' }, h('div', { class: 'progress-fill', style: { width: (pct ?? 30) + '%' }, 'data-indeterminate': pct == null ? 'true' : null })),
    label && h('div', { class: 'progress-label' }, label));
}

export function card(title, ic, body, opts = {}) {
  return h('section', { class: ['card', opts.class], key: opts.key },
    title && h('div', { class: 'card-head' }, h('h3', null, ic && icon(ic, 16), title), opts.actions && h('div', { class: 'card-actions' }, opts.actions)),
    body);
}

// Karte zum Auf- und Zuklappen (Zustand bleibt beim Neuzeichnen); zugeklappt nur eine Zeile Zusammenfassung
export function foldCard(id, title, ic, summary, body, opts = {}) {
  const st = ui('fold:' + id, { open: !!opts.open });
  const toggle = () => { st.open = !st.open; update(); };
  return card(h('button', { type: 'button', class: 'fold-card-toggle', 'aria-expanded': st.open ? 'true' : 'false', onclick: toggle },
    icon(st.open ? 'chevronDown' : 'chevronRight', 14), h('span', null, title)), ic,
  st.open ? (typeof body === 'function' ? body() : body) : (summary ? h('p', { class: 'muted small fold-card-summary' }, summary) : null),
  { actions: opts.actions, class: [st.open ? 'fold-card open' : 'fold-card', opts.class].filter(Boolean).join(' ') });
}

// Aufklappbarer Abschnitt; Zustand bleibt beim Neuzeichnen erhalten
export function section(id, title, body, opts = {}) {
  const st = ui('sec:' + id, { open: opts.open !== false });
  return h('section', { class: ['fold', st.open && 'open'], key: id },
    h('button', { type: 'button', class: 'fold-head', onclick: () => { st.open = !st.open; update(); } },
      icon(st.open ? 'chevronDown' : 'chevronRight', 14), h('span', null, title), opts.count != null && h('span', { class: 'fold-count' }, opts.count)),
    st.open && h('div', { class: 'fold-body' }, typeof body === 'function' ? body() : body));
}

export function emptyState(ic, title, text, actions) {
  return h('div', { class: 'empty-state' },
    h('div', { class: 'empty-icon' }, icon(ic, 26)), h('h2', null, title), text && h('p', null, text),
    actions && h('div', { class: 'row center' }, actions));
}

// ------------------------------------------------------------------ Seitenleisten mit verschiebbarer Breite
// Die Leiste bekommt paneProps(id, Standardbreite) und als letztes Kind splitter(id, …). Die Breite wird je Leiste
// gemerkt; Doppelklick auf die Trennlinie stellt die Standardbreite wieder her, Pfeiltasten verschieben sie fein.
const paneWidths = {};

export function paneWidth(id, def) {
  if (!(id in paneWidths)) {
    let saved = 0;
    try { saved = Number(localStorage.getItem('zllm.pane.' + id)) || 0; } catch { /* privat */ }
    paneWidths[id] = saved > 0 ? saved : def;
  }
  return paneWidths[id];
}

// Standardbreite: Zahl (px) oder CSS-Wert wie clamp(…) – dann passt sich die Leiste dem Fenster an, bis man sie zieht
const widthCss = w => (typeof w === 'number' ? `${w}px` : w);

export function paneProps(id, def) {
  return { 'data-pane': id, style: { width: widthCss(paneWidth(id, def)) } };
}

export function splitter(id, { def, min = 180, max = 640, side = 'left' } = {}) {
  const clamp = w => Math.round(Math.max(min, Math.min(max, window.innerWidth * 0.55, w)));
  const apply = (pane, w) => { paneWidths[id] = w; pane.style.width = widthCss(w); };
  const save = () => {
    try {
      if (typeof paneWidths[id] === 'number') localStorage.setItem('zllm.pane.' + id, String(paneWidths[id]));
      else localStorage.removeItem('zllm.pane.' + id);
    } catch { /* privat */ }
  };
  return h('div', {
    class: ['splitter', `splitter-${side}`], role: 'separator', 'aria-orientation': 'vertical', tabindex: 0,
    'aria-label': t('Breite der Leiste'), title: t('Breite ändern: ziehen · Doppelklick: Standardbreite'),
    onpointerdown: e => {
      if (e.button !== 0) return;
      e.preventDefault();
      const handle = e.currentTarget;
      const pane = handle.parentElement;
      const startX = e.clientX;
      const startW = pane.getBoundingClientRect().width;
      handle.setPointerCapture(e.pointerId);
      handle.classList.add('dragging');
      document.body.classList.add('resizing');
      const move = ev => apply(pane, clamp(startW + (side === 'left' ? ev.clientX - startX : startX - ev.clientX)));
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        handle.classList.remove('dragging');
        document.body.classList.remove('resizing');
        save();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    },
    ondblclick: e => { apply(e.currentTarget.parentElement, def); save(); },
    onkeydown: e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const grow = (e.key === 'ArrowRight') === (side === 'left');
      const pane = e.currentTarget.parentElement;
      apply(pane, clamp(pane.getBoundingClientRect().width + (grow ? 16 : -16)));
      save();
    },
  });
}

// ------------------------------------------------------------------ Menü & Combobox
export function openMenu(x, y, items, opts = {}) { state.menu = { x, y, items, ...opts }; update(); }
export function closeMenu() { if (state.menu) { state.menu = null; update(); } }

// Eingabefeld mit aufklappbarer, durchsuchbarer Liste (z. B. Modelle eines Anbieters). Eigene Werte sind erlaubt.
export function combo(o) {
  const openList = (input, query) => {
    const q = (query || '').trim().toLowerCase();
    const items = (o.options || []).filter(v => !q || v.toLowerCase().includes(q)).slice(0, 400);
    if (!items.length) { closeMenu(); return; }
    const r = input.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12;
    const up = below < 220 && r.top > below;
    const maxHeight = Math.max(160, Math.min(380, up ? r.top - 16 : below));
    const height = Math.min(maxHeight, items.length * 31 + 12);
    openMenu(r.left, up ? r.top - height - 4 : r.bottom + 4, items.map(v => ({
      label: v, icon: v === o.value ? 'check' : null, hint: o.hints && o.hints[v],
      // Das Feld behält beim Auswählen den Fokus – Wert direkt setzen, damit es nicht den getippten Text zeigt
      onClick: () => { input.value = o.clearOnSelect ? '' : v; if (o.clearOnSelect) input.blur(); o.onChange(v); },
    })), { width: Math.max(r.width, 260), maxHeight, scroll: true });
  };
  return h('div', { class: 'combo', key: o.key },
    h('input', { class: 'input', value: o.value || '', placeholder: o.placeholder || '', spellcheck: false, autocomplete: 'off', 'aria-label': o.label,
      disabled: o.disabled,
      onfocus: e => { if (o.openOnFocus) openList(e.target, ''); },
      oninput: e => openList(e.target, e.target.value),
      onkeydown: e => { if (e.key === 'ArrowDown') { e.preventDefault(); openList(e.target, ''); } if (e.key === 'Escape') closeMenu(); },
      onchange: e => { const v = e.target.value.trim(); if (v && v !== o.value) o.onChange(v); } }),
    h('button', { type: 'button', class: 'combo-toggle', title: o.title || t('Liste anzeigen'), disabled: o.disabled || !(o.options || []).length,
      onclick: e => { const input = e.currentTarget.previousElementSibling; if (state.menu) closeMenu(); else openList(input, ''); } },
    icon('chevronDown', 14)));
}

// Mehrfachauswahl: Knopf mit den gewählten Einträgen als Chips, Liste mit Häkchen bleibt beim Anklicken offen
export function multiSelect(o) {
  const chosen = (o.options || []).filter(x => (o.values || []).includes(x.value));
  const open = e => {
    const r = e.currentTarget.getBoundingClientRect();
    const sel = new Set(o.values || []);
    const toggle = v => { if (sel.has(v)) sel.delete(v); else sel.add(v); o.onChange((o.options || []).map(x => x.value).filter(x => sel.has(x))); };
    openMenu(r.left, r.bottom + 4, () => [
      ...(o.options || []).map(x => ({ label: x.label, hint: x.hint, keep: true, checked: sel.has(x.value), onClick: () => toggle(x.value) })),
      ...(o.options || []).length > 1 ? ['-', { label: sel.size === (o.options || []).length ? t('Keinen auswählen') : t('Alle auswählen'), keep: true,
        onClick: () => { const all = sel.size !== o.options.length; sel.clear(); if (all) o.options.forEach(x => sel.add(x.value)); o.onChange([...sel]); } }] : [],
    ], { width: Math.max(r.width, 280), maxHeight: 340, scroll: true });
  };
  return h('button', { type: 'button', class: ['multi', o.class, !chosen.length && 'empty'], disabled: o.disabled, key: o.key,
    'aria-label': o.label, onclick: open },
  chosen.length ? h('span', { class: 'multi-chips' }, chosen.map(x => h('span', { key: x.value, class: 'chip chip-accent' }, h('span', null, x.label))))
    : h('span', { class: 'multi-placeholder' }, o.placeholder || t('Auswählen …')),
  icon('chevronDown', 14, 'multi-caret'));
}

// Schwebendes Element (Menü, Belegvorschau) in das Fenster schieben; die Lage wird in pos (x/y) gespeichert
export function fitToWindow(el, pos, { flipAbove = null } = {}) {
  if (!el.isConnected || pos.placed) return;
  const r = el.getBoundingClientRect();
  let { x, y } = pos;
  if (r.right > window.innerWidth - 8) x = Math.max(8, window.innerWidth - r.width - 8);
  if (r.bottom > window.innerHeight - 8) y = flipAbove != null ? Math.max(8, flipAbove - r.height) : Math.max(8, window.innerHeight - r.height - 8);
  pos.x = x;
  pos.y = y;
  pos.placed = true;
  el.style.left = x + 'px';
  el.style.top = y + 'px';
}

export function renderMenu() {
  const m = state.menu;
  if (!m) return null;
  const items = typeof m.items === 'function' ? m.items() : m.items;
  return h('div', { class: 'menu-backdrop', onmousedown: closeMenu },
    h('div', { class: ['menu', m.scroll && 'menu-scroll'], onmousedown: e => e.stopPropagation(),
      style: { left: m.x + 'px', top: m.y + 'px', ...(m.width ? { width: m.width + 'px' } : {}), ...(m.maxHeight ? { maxHeight: m.maxHeight + 'px' } : {}) },
      // Ragt das Menü über den Rand, wird es einmal verschoben und die neue Lage gemerkt. Sonst setzte jedes
      // Neuzeichnen (z. B. die Statusabfrage alle 4 s) es auf die alte Lage zurück – das Menü flackerte.
      ref: el => { if (!m.placed) requestAnimationFrame(() => fitToWindow(el, m)); } },
    items.filter(Boolean).map((item, i) => item === '-' ? h('div', { class: 'menu-sep', key: 's' + i }) :
      item.heading ? h('div', { class: 'menu-heading', key: 'h' + i }, item.heading) :
        h('button', { key: i, type: 'button', class: ['menu-item', item.danger && 'danger', item.active && 'active'], disabled: item.disabled,
          onmousedown: e => e.preventDefault(), onclick: () => { if (!item.keep) closeMenu(); item.onClick && item.onClick(); if (item.keep) update(); } },
        'checked' in item ? h('span', { class: ['menu-check', item.checked && 'on'] }, icon('check', 11))
          : item.swatch ? h('span', { class: 'menu-swatch', style: { background: item.swatch } })
            : item.icon ? icon(item.icon, 15) : h('span', { class: 'menu-spacer' }),
        h('span', { class: 'menu-label' }, item.label, item.hint && h('span', { class: 'menu-hint' }, item.hint))))));
}
