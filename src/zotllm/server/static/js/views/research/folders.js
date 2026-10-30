// Tab „Ordner“: Zielbibliothek in Zotero und die Ordner, in die das Screening aufnimmt (beliebig viele bis 20, feste
// Nummern; Kürzel 1–9). Ordner mit aufgenommenen Treffern werden vor dem Löschen geleert (Treffer verschieben). Sammlungen wählt man im
// Baum wie in ZotLLM (eigene Bibliothek und Gruppen, mit Suchfeld). Auf Wunsch schlägt das Sprachmodell Unterordner vor;
// angelegt wird in Zotero nur nach ausdrücklicher Bestätigung und nur unter einer gewählten Sammlung.
import { h } from '../../core/vdom.js';
import { update, toast, openModal, closeModal, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { icon } from '../../ui/icons.js';
import { btn, iconBtn, card, field, textInput, select, segmented, checkbox, notice, badge, spinner } from '../../ui/components.js';
import { R, rs, enc, busy, isBusy, aiInfo, tokenText, noteUsage, invalidate, refreshSummary, folderLabel } from './common.js';
import { draft, draftBar, saveDraft, zoteroLibraries, collectionPaths, estimateLine } from './project.js';

const norm = p => String(p || '').split('/').map(x => x.trim()).filter(Boolean).join('/');
const isGroup = lib => String(lib).startsWith('groups/');
const crumbs = p => norm(p).split('/').join(' › ');

// Sammlungen einer Bibliothek als Baum (einmal laden, bis Zotero sich ändert)
function treeOf(backend, lib) {
  const z = zoteroLibraries(backend);
  z.trees = z.trees || {};
  if (lib && z.trees[lib] === undefined) {
    z.trees[lib] = null;
    api.get(`${R}/zotero/tree?backend=${enc(backend)}&lib=${enc(lib)}`).then(r => { z.trees[lib] = r.collections; })
      .catch(err => { z.trees[lib] = { error: err.message }; }).finally(update);
  }
  return z.trees[lib];
}

function forget(backend, lib) {
  const z = zoteroLibraries(backend);
  if (z.trees) delete z.trees[lib];
  delete z.collections[lib];
}

const matches = (n, q) => n.name.toLowerCase().includes(q) || (n.children || []).some(k => matches(k, q));

// ------------------------------------------------------------------ Sammlung wählen (Baum wie in ZotLLM)
export function pickCollection({ backend, lib, path = '', title, onPick, onCancel, hint }) {
  const z = zoteroLibraries(backend);
  const prefixes = norm(path).split('/').filter(Boolean).map((_, i, a) => `${lib}:${a.slice(0, i + 1).join('/')}`);
  const d = { lib: path ? lib : '', path: norm(path), filter: '', open: new Set([lib, ...prefixes]), newName: '', isNew: false };
  const libName = l => ((z.libraries || []).find(x => x.lib === l) || {}).name || l;
  const toggle = key => { d.open.has(key) ? d.open.delete(key) : d.open.add(key); update(); };
  const select = (l, p, isNew = false) => { d.lib = l; d.path = p; d.isNew = isNew; update(); };
  const apply = () => {
    if (!d.lib || !d.path) return;
    closeModal();
    onPick({ lib: d.lib, libName: libName(d.lib), path: d.path, isNew: d.isNew });
  };
  const cancel = () => { closeModal(); if (onCancel) onCancel(); };
  const addNew = () => {
    const name = d.newName.replace(/\//g, ' ').trim();
    if (!name || !d.lib) return;
    select(d.lib, d.path ? `${d.path}/${name}` : name, true);
    d.newName = '';
  };

  const colNode = (n, depth, l, q) => {
    if (q && !matches(n, q)) return null;
    const key = `${l.lib}:${n.path}`;
    const kids = n.children || [];
    const open = q ? true : d.open.has(key);
    const sel = d.lib === l.lib && d.path === n.path;
    return h('div', { key, class: 'tree-node' },
      h('div', { class: ['tree-row', 'rs-tree-pick', sel && 'is-selected'], style: { paddingLeft: `${8 + depth * 18}px` },
        onclick: () => select(l.lib, n.path), ondblclick: () => { select(l.lib, n.path); apply(); } },
      kids.length ? h('button', { type: 'button', class: 'tree-twisty', title: open ? t('Zuklappen') : t('Aufklappen'),
        onclick: e => { e.stopPropagation(); toggle(key); } }, icon(open ? 'chevronDown' : 'chevronRight', 14))
        : h('span', { class: 'tree-twisty' }),
      icon('folder', 15, 'tree-icon'), h('span', { class: 'tree-name' }, n.name)),
      open && kids.length ? h('div', { class: 'tree-children' }, kids.map(k => colNode(k, depth + 1, l, q))) : null);
  };

  const libNode = (l, q) => {
    const loaded = z.trees && Array.isArray(z.trees[l.lib]);
    if (q && !loaded) return null;  // gesucht wird in den schon geladenen Bibliotheken
    const open = d.open.has(l.lib) || !!q;
    const tree = open ? treeOf(backend, l.lib) : undefined;
    const rows = Array.isArray(tree) ? tree.map(n => colNode(n, 1, l, q)).filter(Boolean) : [];
    if (q && !rows.length) return null;
    return h('div', { key: l.lib, class: 'tree-node' },
      h('div', { class: ['tree-row', 'tree-lib', 'rs-tree-pick', isGroup(l.lib) ? 'tree-lib-group' : 'tree-lib-user'], style: { paddingLeft: '8px' },
        onclick: () => toggle(l.lib) },
      h('button', { type: 'button', class: 'tree-twisty' }, icon(open ? 'chevronDown' : 'chevronRight', 14)),
      icon(isGroup(l.lib) ? 'users' : 'user', 15, 'tree-icon'), h('span', { class: 'tree-name' }, l.name),
      l.lib === lib ? h('span', { class: 'tree-hint' }, t('Zielbibliothek')) : null),
      open ? (tree == null ? h('div', { class: 'muted small rs-tree-note' }, spinner(12), ' ', t('Lade Sammlungen …'))
        : tree.error ? h('div', { class: 'danger-text small rs-tree-note' }, tree.error)
          : h('div', { class: 'tree-children' }, rows.length ? rows : h('div', { class: 'muted small rs-tree-note' }, t('Keine Sammlungen.'))))
        : null);
  };

  openModal({
    title: title || t('Sammlung wählen'), cls: 'modal-wide', onClose: onCancel,
    body: () => {
      const libs = z.libraries;
      if (!libs) return h('div', { class: 'muted' }, spinner(13), ' ', t('Lade Bibliotheken …'));
      const q = d.filter.trim().toLowerCase();
      const user = libs.filter(l => !isGroup(l.lib));
      const groups = libs.filter(l => isGroup(l.lib));
      return h('div', { class: 'stack-sm' },
        hint ? h('p', { class: 'muted small' }, hint) : null,
        h('div', { class: 'tree-search rs-tree-search' }, icon('search', 14),
          h('input', { class: 'input input-sm', value: d.filter, placeholder: t('Sammlung suchen …'), oninput: e => { d.filter = e.target.value; update(); } })),
        h('div', { class: 'tree rs-tree' },
          user.length ? h('div', { class: 'tree-group-label tree-group-user' }, icon('user', 13), t('Eigene Bibliothek')) : null,
          user.map(l => libNode(l, q)),
          groups.length ? h('div', { class: 'tree-group-label tree-group-groups' }, icon('users', 13), t('Gruppen ({n})', { n: groups.length })) : null,
          groups.map(l => libNode(l, q)),
          q && !libs.some(l => z.trees && Array.isArray(z.trees[l.lib])) ? h('div', { class: 'muted small rs-tree-note' }, t('Zum Suchen zuerst eine Bibliothek aufklappen.')) : null),
        h('div', { class: 'row wrap small' }, h('span', { class: 'muted' }, t('Gewählt:')),
          d.path ? [h('b', { key: 'p' }, `${libName(d.lib)} › ${crumbs(d.path)}`), d.isNew ? badge(t('neu'), 'info') : null]
            : h('span', { class: 'muted' }, t('noch nichts – eine Sammlung anklicken'))),
        d.lib ? h('div', { class: 'row' },
          h('div', { class: 'grow' }, textInput({ value: d.newName, placeholder: d.path ? t('Neue Untersammlung in „{p}“', { p: d.path.split('/').pop() }) : t('Neue Sammlung'),
            onInput: v => { d.newName = v; update(); }, onKeyDown: e => { if (e.key === 'Enter') addNew(); } })),
          btn(t('Vormerken'), { size: 'sm', icon: 'plus', disabled: !d.newName.trim(), onClick: addNew,
            title: t('Wird erst nach deiner Bestätigung in Zotero angelegt (unter Ordner oder bei der Übergabe).') })) : null,
        d.lib && lib && d.lib !== lib ? notice('warning', t('Andere Bibliothek: Die Zielbibliothek des Projekts wechselt zu „{n}“. Die übrigen Ordner beziehen sich dann ebenfalls auf diese Bibliothek.', { n: libName(d.lib) })) : null);
    },
    actions: () => [{ label: t('Abbrechen'), onClick: cancel },
      { label: t('Übernehmen'), kind: 'primary', disabled: !d.path, onClick: apply }],
  });
}

// ------------------------------------------------------------------ Neue Sammlungen anlegen (nach Bestätigung)
async function createNow(paths) {
  const s = rs();
  const p = s.project;
  const ok = await confirmDialog(t('Sammlungen in Zotero anlegen?'), h('div', { class: 'stack-sm' },
    h('p', null, t('In „{lib}“ werden diese Sammlungen angelegt ({how}):', { lib: p.target_name || p.target_library,
      how: p.zotero_backend === 'local' ? t('Zotero auf diesem Computer') : t('über zotero.org, Sync danach') })),
    h('ul', null, paths.map(x => h('li', { key: x }, crumbs(x)))),
    isGroup(p.target_library) ? h('p', { class: 'muted small' }, t('Das ist eine Gruppe: Alle Mitglieder sehen die neuen Sammlungen nach dem Sync.')) : null),
  { ok: t('Anlegen') });
  if (!ok) return;
  const r = await busy('create-collections', () => api.post(`${R}/projects/${s.pid}/zotero/collections`, { paths, confirm: true }));
  if (!r) return;
  forget(p.zotero_backend || 'web', p.target_library);
  toast(r.created.length ? t('Angelegt: {list}', { list: r.created.map(crumbs).join(', ') }) : t('Alle Sammlungen gab es schon.'), 'success', 6000);
  update();
}

// ------------------------------------------------------------------ KI-Vorschlag für Unterordner
function commonParent(paths) {
  const parts = paths.map(p => norm(p).split('/'));
  if (!parts.length) return '';
  if (parts.length === 1) return parts[0].join('/');
  const out = [];
  for (let i = 0; parts.every(x => x.length > i && x[i] === parts[0][i]); i += 1) out.push(parts[0][i]);
  return out.join('/');
}

function aiFoldersDialog(x = null) {
  const s = rs();
  const st = draft();
  const d = st.d;
  const backend = d.zotero_backend || 'web';
  x = x || { parent: commonParent(d.folder_map.map(f => f.path).filter(Boolean)), result: null, picked: new Set() };
  const free = () => Math.max(0, maxFolders() - d.folder_map.length);  // wie viele Ordner noch angelegt werden können
  const ask = async () => {
    const r = await busy('ai-folders', () => api.post(`${R}/projects/${s.pid}/ai/folders`, { parent: x.parent, lib: d.target_library, backend }));
    if (r) { x.result = r; x.picked = new Set(r.folders.map(f => f.name)); noteUsage(r); update(); }
  };
  const chooseParent = () => pickCollection({ backend, lib: d.target_library, path: x.parent, title: t('Unter welcher Sammlung?'),
    hint: t('Die vorgeschlagenen Ordner kommen unter diese Sammlung – nie auf die oberste Ebene der Bibliothek.'),
    onPick: r => {
      if (r.lib !== d.target_library) { d.target_library = r.lib; d.target_name = r.libName; st.dirty = true; }
      x.parent = r.path; x.result = null;
      aiFoldersDialog(x);
    },
    onCancel: () => aiFoldersDialog(x) });
  const adopt = () => {
    const chosen = x.result.folders.filter(f => x.picked.has(f.name)).slice(0, free());
    chosen.forEach(f => d.folder_map.push({ slot: nextSlot(d), label: f.name, path: `${x.parent}/${f.name}` }));
    st.dirty = true;
    closeModal();
    toast(t('{n} Ordner übernommen – noch speichern. In Zotero angelegt wird erst nach deiner Bestätigung.', { n: chosen.length }), 'success', 6000);
  };
  const libName = d.target_name || d.target_library;
  openModal({
    title: t('KI-Vorschlag für Unterordner'), cls: 'modal-wide',
    body: () => h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, t('Das Sprachmodell schlägt 3–6 thematische Ordner vor, passend zu Fragestellung und Kriterien und – falls es schon welche gibt – zu den Titeln aufgenommener Arbeiten. Übernommene kommen als neue Ordner dazu; in Zotero wird nichts angelegt, bevor du es bestätigst.')),
      field(t('Unter dieser Sammlung'), h('div', { class: 'row' },
        h('div', { class: 'grow' }, x.parent ? h('b', null, `${libName} › ${crumbs(x.parent)}`) : h('span', { class: 'muted' }, t('noch keine gewählt'))),
        btn(t('Wählen …'), { size: 'sm', kind: 'ghost', icon: 'folder', onClick: chooseParent }))),
      x.parent && !x.result ? estimateLine('folders', { parent: x.parent }, x.parent) : null,
      x.result ? h('div', { class: 'stack-sm' },
        x.result.existing && x.result.existing.length ? h('div', { class: 'muted small' }, t('Schon vorhanden: {list}', { list: x.result.existing.join(', ') })) : null,
        x.result.folders.length ? x.result.folders.map(f => h('div', { key: f.name, class: 'rs-ai-folder' },
          checkbox({ checked: x.picked.has(f.name), label: f.name, onChange: v => { v ? x.picked.add(f.name) : x.picked.delete(f.name); update(); } }),
          h('div', { class: 'muted small' }, f.description))) : h('div', { class: 'muted small' }, t('Kein brauchbarer Vorschlag.')),
        x.result.note ? h('div', { class: 'muted small' }, x.result.note) : null,
        x.result.used ? h('div', { class: 'muted small' }, t('Verbrauch: {u}', { u: tokenText(x.result.used, false) })) : null,
        x.picked.size > free() ? notice('warning', t('Höchstens {m} Ordner – übernommen werden die ersten {n}.', { m: maxFolders(), n: free() })) : null)
        : null),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      x.result ? { label: t('Neu vorschlagen'), icon: 'refresh', disabled: isBusy('ai-folders'), onClick: ask } : null,
      x.result ? { label: t('Als neue Ordner übernehmen ({n})', { n: Math.min(x.picked.size, free()) }), kind: 'primary',
        disabled: !x.picked.size || !free(), onClick: adopt }
        : { label: t('Vorschlag holen'), kind: 'primary', icon: 'ai', disabled: !x.parent || isBusy('ai-folders'), busy: isBusy('ai-folders'), onClick: ask },
    ].filter(Boolean),
  });
}

// ------------------------------------------------------------------ Ordner hinzufügen und löschen
const maxFolders = () => (rs().info && rs().info.max_folders) || 20;

// Nächste freie Nummer: weder im Entwurf noch von schon aufgenommenen Treffern belegt
function nextSlot(d) {
  const used = new Set([...d.folder_map.map(f => Number(f.slot)), ...Object.keys((rs().project.summary || {}).by_folder || {}).map(Number)]);
  let n = 1;
  while (used.has(n)) n += 1;
  return n;
}

function addFolder() {
  const st = draft();
  const d = st.d;
  if (d.folder_map.length >= maxFolders()) return;
  d.folder_map.push({ slot: nextSlot(d), label: '', path: '' });
  st.dirty = true;
  update();
  requestAnimationFrame(() => { const el = [...document.querySelectorAll('.rs-folder-row input')].slice(-2)[0]; if (el) el.focus(); });
}

// Löschen: leer → sofort (Speichern nötig); mit aufgenommenen Treffern → erst in einen anderen Ordner verschieben
function removeFolder(i) {
  const s = rs();
  const st = draft();
  const d = st.d;
  const f = d.folder_map[i];
  const n = Number(((s.project.summary || {}).by_folder || {})[f.slot] || 0);
  if (!n) {
    d.folder_map.splice(i, 1);
    st.dirty = true;
    update();
    return;
  }
  const others = (s.project.folder_map || []).filter(o => Number(o.slot) !== Number(f.slot));
  const x = { to: others.length ? String(others[0].slot) : '' };
  openModal({
    title: t('Ordner {n} löschen', { n: f.slot }),
    body: () => h('div', { class: 'stack' },
      h('p', null, t('In „{l}“ sind {k} Treffer aufgenommen. Wohin sollen sie?', { l: folderLabel(s.project, f.slot), k: n })),
      others.length ? field(t('Verschieben nach'), select({ value: x.to, options: others.map(o => ({ value: String(o.slot), label: `${o.slot} · ${folderLabel(s.project, o.slot)}` })),
        onChange: v => { x.to = v; update(); } }))
        : notice('warning', t('Es gibt noch keinen anderen gespeicherten Ordner. Lege zuerst einen an und speichere.')),
      h('p', { class: 'muted small' }, t('Die Treffer bleiben aufgenommen und kommen in den gewählten Ordner; „rückgängig“ im Screening nimmt die Verschiebung als Ganzes zurück. Danach wird der Ordner entfernt und das Projekt gespeichert.'))),
    actions: () => [{ label: t('Abbrechen'), onClick: closeModal },
      { label: t('Verschieben und löschen'), kind: 'danger', disabled: !x.to, busy: isBusy('move-folder'), onClick: async () => {
        const r = await busy('move-folder', () => api.post(`${R}/projects/${s.pid}/folders/move`, { from_slot: Number(f.slot), to_slot: Number(x.to) }));
        if (!r) return;
        closeModal();
        const j = d.folder_map.findIndex(o => o.slot === f.slot);
        if (j >= 0) d.folder_map.splice(j, 1);
        st.dirty = true;
        await saveDraft();
        invalidate('queue', 'pool', 'plan');
        refreshSummary();
        toast(t('{k} Treffer nach Ordner {to} verschoben, Ordner {n} gelöscht.', { k: r.moved, to: x.to, n: f.slot }), 'success', 5000);
      } }],
  });
}

// ------------------------------------------------------------------ Tab
export function foldersTab() {
  const s = rs();
  const st = draft();
  const d = st.d;
  const set = (k, v) => { d[k] = v; st.dirty = true; update(); };
  const backend = d.zotero_backend || 'web';
  const z = zoteroLibraries(backend);
  const libs = z.libraries || [];
  const known = new Set(collectionPaths(backend, d.target_library));
  const loaded = Array.isArray(z.collections[d.target_library]);
  const isFresh = f => norm(f.path) && loaded && !known.has(norm(f.path));
  const fresh = d.folder_map.filter(isFresh);
  const listId = `rs-paths-${s.pid}`;
  const setFolder = (i, patch) => { Object.assign(d.folder_map[i], patch); st.dirty = true; update(); };
  const byFolder = (s.project.summary || {}).by_folder || {};
  const pick = i => pickCollection({ backend, lib: d.target_library, path: d.folder_map[i].path, title: t('Sammlung für Ordner {n}', { n: d.folder_map[i].slot }),
    onPick: r => {
      if (r.lib !== d.target_library) { d.target_library = r.lib; d.target_name = r.libName; }
      setFolder(i, { path: r.path, label: d.folder_map[i].label || r.path.split('/').pop() });
    } });
  return h('div', { class: 'view-body scroll' },
    h('div', { class: 'rs-narrow stack-lg' },
      card(t('Ziel in Zotero'), 'zotero', h('div', { class: 'stack' },
        field(t('Zugang'), segmented({ value: backend, options: [
          { value: 'web', label: t('Zotero-Server (Web-API)') }, { value: 'local', label: t('Zotero auf diesem Computer') }],
        onChange: v => set('zotero_backend', v) }), { hint: backend === 'local'
          ? t('Lokale API von Zotero: Zotero muss laufen; Schreiben braucht eine Freigabe in Zotero (unter Übergabe).')
          : t('Schreibt über zotero.org; die Zotero-App übernimmt die Einträge beim nächsten Sync.') }),
        z.error && notice('warning', z.error),
        field(t('Zielbibliothek'), select({ value: d.target_library, options: [
          ...(libs.some(l => l.lib === d.target_library) ? [] : [{ value: d.target_library, label: d.target_name || d.target_library }]),
          ...libs.map(l => ({ value: l.lib, label: isGroup(l.lib) ? t('Gruppe: {n}', { n: l.name }) : l.name }))],
        onChange: v => { set('target_library', v); d.target_name = (libs.find(l => l.lib === v) || {}).name || v; } }),
        { hint: z.libraries == null ? t('Lade Bibliotheken …') : t('Eigene Bibliothek oder eine Gruppe. Die Ordner unten beziehen sich auf diese Bibliothek.') }))),
      card(t('Ordner'), 'folder', h('div', { class: 'stack' },
        h('p', { class: 'muted small' }, t('Im Screening nimmst du Treffer in einen dieser Ordner auf (Kürzel: Zifferntasten 1–9 für die Ordner 1–9). Bei der Übergabe landen sie in der zugeordneten Sammlung.')),
        h('datalist', { id: listId }, [...known].map(p => h('option', { value: p }))),
        d.folder_map.length ? null : h('div', { class: 'muted small' }, t('Noch keine Ordner. Mit „Ordner hinzufügen“ anlegen oder per KI-Vorschlag.')),
        h('div', { class: 'rs-folders' }, d.folder_map.map((f, i) => h('div', { class: 'rs-folder-row', key: f.slot },
          h('span', { class: 'rs-folder-no', title: byFolder[f.slot] ? t('{k} Treffer aufgenommen', { k: byFolder[f.slot] }) : '' },
            t('Ordner {n}', { n: f.slot }), byFolder[f.slot] ? h('span', { class: 'muted' }, ` (${byFolder[f.slot]})`) : null),
          textInput({ value: f.label, placeholder: t('Thema, z. B. Rollen'), onInput: v => setFolder(i, { label: v }) }),
          h('div', { class: 'rs-folder-path' },
            h('input', { class: 'input', value: f.path, list: listId, placeholder: t('Sammlung, z. B. test/Rollen'),
              oninput: e => setFolder(i, { path: e.target.value }) }),
            isFresh(f) ? badge(t('neu'), 'info', t('Gibt es in Zotero noch nicht – wird nach deiner Bestätigung angelegt (hier oder bei der Übergabe).')) : null,
            btn(t('Wählen …'), { size: 'sm', kind: 'ghost', icon: 'folder', onClick: () => pick(i) }),
            iconBtn('trash', byFolder[f.slot] ? t('Ordner löschen (aufgenommene Treffer zuerst verschieben)') : t('Ordner löschen'), () => removeFolder(i)))))),
        h('div', { class: 'field-hint' }, t('Pfad mit „/“ für Untersammlungen. Fehlt eine Sammlung, legt die App sie erst nach deiner Bestätigung an.')),
        h('div', { class: 'row wrap' },
          btn(t('Ordner hinzufügen'), { size: 'sm', icon: 'plus', onClick: addFolder, disabled: d.folder_map.length >= maxFolders(),
            title: d.folder_map.length >= maxFolders() ? t('Höchstens {m} Ordner', { m: maxFolders() }) : '' }),
          fresh.length ? btn(t('{n} neue Sammlungen jetzt anlegen …', { n: fresh.length }), { size: 'sm', icon: 'plus', disabled: st.dirty,
            busy: isBusy('create-collections'), title: st.dirty ? t('Zuerst speichern') : t('Legt die mit „neu“ markierten Sammlungen in Zotero an – nach Rückfrage.'),
            onClick: () => createNow(fresh.map(f => norm(f.path))) }) : null)),
      { actions: [aiInfo().available ? btn(t('KI-Vorschlag für Unterordner …'), { size: 'sm', icon: 'ai', onClick: () => aiFoldersDialog(),
        title: t('Schlägt 3–6 thematische Ordner unter einer gewählten Sammlung vor ({m}).', { m: aiInfo().label }) }) : null] }),
      draftBar()));
}
