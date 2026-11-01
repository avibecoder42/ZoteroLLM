// Wissenskorpora: Sammlungen und Bibliotheken aus Zotero (Abbild aller Bibliotheken) zu benannten Korpora bündeln.
// Ein Korpus bestimmt, was indexiert wird, und kann an Fragen und Forschungsstände angehängt werden.
// Einzelne Einträge kommen aus der Suche hinzu („lib:@KEY“).
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, confirmDialog, openModal, closeModal, loadCorpora, loadSetup, loadStatus, watchJob, runningJob, loadProjects,
  project, projectCorpora, submitIndexRun } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, textInput, notice, spinner, emptyState, checkbox, openMenu, paneProps, splitter } from '../ui/components.js';
import { fmtInt, fmtAgo, plural, debounce, nTexts, nIndexed, embedHint, refreshHint, openHint } from '../core/util.js';
import { navigate, viewHeader } from './shell.js';
import { startEmbedding } from './embedmodels.js';

const modelLabel = () => (state.status && state.status.embedding && (state.status.embedding.label || state.status.embedding.model)) || '';

function st() {
  return ui('corpora', { selected: null, draft: null, dirty: false, expanded: null, search: '', loadingTree: false, treeAt: null,
    saving: false, showOthers: false, preview: null, previewFor: '' });
}

// ------------------------------------------------------------------ Zotero-Baum
export async function loadTree(force = false) {
  const s = st();
  if (s.loadingTree || (state.tree && !force)) return;
  s.loadingTree = true;
  update();
  try {
    state.tree = await api.get('/api/zotero/tree');
    s.treeAt = Date.now() / 1000;
    if (force) {
      toast(state.tree.online ? t('Zotero gelesen: {n} Bibliotheken', { n: state.tree.libraries.length }) : t('Zotero ist nicht erreichbar – zuletzt bekannter Stand.'),
        state.tree.online ? 'success' : 'warning', 3000);
    }
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    s.loadingTree = false;
    update();
  }
}

function walk(nodes, fn, parents = []) {
  for (const n of nodes) { fn(n, parents); walk(n.children || [], fn, [...parents, n]); }
}

// Index: Knoten-ID → { node, parents (IDs), lib }
function treeIndex() {
  const idx = new Map();
  for (const lib of (state.tree && state.tree.libraries) || []) {
    idx.set(lib.id, { node: lib, parents: [], lib });
    walk(lib.collections, (n, parents) => idx.set(n.id, { node: n, parents: [lib.id, ...parents.map(p => p.id)], lib }));
  }
  return idx;
}

function ensureExpanded(sources) {
  const s = st();
  if (s.expanded) return;
  s.expanded = new Set(['users/0:*']);
  const idx = treeIndex();
  for (const src of sources || []) for (const p of (idx.get(src) || { parents: [] }).parents) s.expanded.add(p);
}

// ------------------------------------------------------------------ Auswahl & Entwurf
function selectCorpus(id) {
  const s = st();
  const c = state.corpora.find(x => x.id === id);
  s.selected = id;
  s.draft = c ? { name: c.name, description: c.description || '', sources: new Set(c.sources) } : { name: '', description: '', sources: new Set() };
  s.dirty = false;
  s.expanded = null;
  s.preview = null; s.previewFor = '';
  update();
}

async function guardDirty() {
  const s = st();
  if (!s.dirty) return true;
  return confirmDialog(t('Änderungen verwerfen?'), t('Der Wissenskorpus hat ungespeicherte Änderungen.'), { ok: t('Verwerfen'), danger: true });
}

async function choose(id) {
  if (st().selected === id) return;
  if (await guardDirty()) selectCorpus(id);
}

// Kennzahlen für die aktuelle (ungespeicherte) Auswahl – wie viele Texte stecken darin, wie viele sind zu indexieren?
const refreshPreview = debounce(async () => {
  const s = st();
  if (!s.draft) return;
  const key = [...s.draft.sources].sort().join('|');
  if (key === s.previewFor) return;
  s.previewFor = key;
  if (!s.draft.sources.size) { s.preview = null; update(); return; }
  try { s.preview = await api.post('/api/corpora/preview', { sources: [...s.draft.sources] }); } catch { s.preview = null; }
  update();
}, 350);

function toggleSource(id, on) {
  const s = st();
  const idx = treeIndex();
  if (on) {
    s.draft.sources.add(id);
    // Untergeordnete Auswahl ist jetzt überflüssig
    for (const other of [...s.draft.sources]) if (other !== id && (idx.get(other) || { parents: [] }).parents.includes(id)) s.draft.sources.delete(other);
  } else {
    s.draft.sources.delete(id);
  }
  s.dirty = true;
  refreshPreview();
  update();
}

async function save() {
  const s = st();
  const d = s.draft;
  if (!d.name.trim()) { toast(t('Bitte einen Namen für den Wissenskorpus eingeben.'), 'warning'); document.getElementById('corpus-name')?.focus(); return; }
  if (!d.sources.size) { toast(t('Bitte mindestens eine Sammlung oder Bibliothek anhaken.'), 'warning'); return; }
  s.saving = true; update();
  try {
    const body = { name: d.name.trim(), description: d.description, sources: [...d.sources] };
    const saved = await run(() => s.selected === 'new' ? api.post('/api/corpora', { ...body, project_id: state.projectId }) : api.put(`/api/corpora/${s.selected}`, body));
    await Promise.all([loadCorpora(), loadProjects()]);
    selectCorpus(saved.id);
    loadSetup(); loadStatus();
    const pending = saved.stats.pending || !saved.synced;
    toast(t('„{name}“ gespeichert.', { name: saved.name }), 'success', 6000, pending ? { label: t('Jetzt indexieren'), onClick: () => indexCorpus(saved) } : null);
  } finally {
    s.saving = false; update();
  }
}

// Kleiner Dialog: ganz löschen oder (falls im Projekt) nur aus dem Projekt entfernen
async function removeCorpus(c) {
  const s = st();
  if (s.selected === c.id && !await guardDirty()) return;
  const inProject = c.project_ids.includes(state.projectId);
  const others = c.project_ids.filter(id => id !== state.projectId).map(id => (state.projects.find(p => p.id === id) || {}).name).filter(Boolean);
  const text = (others.length ? t('Der Korpus wird auch in {names} verwendet und dort ebenfalls entfernt. ', { names: others.map(n => `„${n}“`).join(', ') }) : '')
    + t('Indexierte Texte bleiben erhalten, solange sie zu einem anderen Korpus gehören; Zotero wird nicht verändert.');
  const del = async () => {
    closeModal();
    await run(() => api.del(`/api/corpora/${c.id}`));
    if (st().selected === c.id) { st().selected = null; st().draft = null; st().dirty = false; }
    await Promise.all([loadCorpora(), loadProjects()]);
    loadSetup(); loadStatus();
    toast(t('„{name}“ gelöscht.', { name: c.name }), 'success');
  };
  openModal({
    title: t('„{name}“ löschen?', { name: c.name }),
    body: () => h('div', { class: 'stack' }, h('p', null, text),
      inProject && h('p', { class: 'muted small' }, t('Soll der Korpus nur aus diesem Projekt verschwinden, wähle „Nur aus dem Projekt entfernen“ – er bleibt dann erhalten und lässt sich später wieder hinzufügen.'))),
    actions: [
      { label: t('Abbrechen'), onClick: closeModal },
      inProject && { label: t('Nur aus dem Projekt entfernen'), onClick: () => { closeModal(); assignToProject(c, false); } },
      { label: t('Löschen'), kind: 'danger', icon: 'trash', onClick: del },
    ].filter(Boolean),
  });
}

function corpusMenu(e, c) {
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  const inProject = c.project_ids.includes(state.projectId);
  openMenu(r.left, r.bottom + 4, [
    inProject ? { label: t('Aus diesem Projekt entfernen'), icon: 'minus', onClick: () => assignToProject(c, false) }
      : { label: t('Zu diesem Projekt hinzufügen'), icon: 'plus', onClick: () => assignToProject(c, true) },
    { label: runningJob('index') ? t('Indexieren (in die Warteschlange)') : t('Indexieren'), icon: 'play', onClick: () => indexCorpus(c) },
    '-',
    { label: t('Korpus löschen …'), icon: 'trash', danger: true, onClick: () => removeCorpus(c) }]);
}

async function assignToProject(c, assigned) {
  await run(() => api.put(`/api/projects/${state.projectId}/corpora/${c.id}`, { assigned }));
  await Promise.all([loadProjects(), loadCorpora()]);
  toast(assigned ? t('„{name}“ gehört jetzt zu diesem Projekt.', { name: c.name }) : t('„{name}“ aus dem Projekt entfernt (der Korpus selbst bleibt bestehen).', { name: c.name }), 'success');
}

// Läuft schon eine Indexierung, wartet dieser Lauf in der Warteschlange (Ansicht Index)
export async function indexCorpus(c) {
  const job = await submitIndexRun(`/api/corpora/${c.id}/index`, {});
  if (job === false) return;  // Rückfrage zu Dubletten abgebrochen
  Object.assign(ui('index', {}), { corpus: c.id, corpusFor: state.projectId });  // rechts diesen Korpus zeigen
  navigate('index');
  if (job) watchJob(job.id).then(() => { loadCorpora(); loadSetup(); });  // Ergebnis meldet store.js
}

async function syncLibraries() {
  try {
    const job = await api.post('/api/library/sync', {});
    state.jobs[job.id] = job; update();
    await watchJob(job.id);
  } catch (err) { toast(err.message, 'error'); return; }
  st().previewFor = ''; refreshPreview(); loadCorpora();
}

// ------------------------------------------------------------------ Darstellung
function corpusItem(c, inProject) {
  const s = st();
  const x = c.stats;
  const pct = x.documents ? Math.round(100 * nIndexed(x) / x.documents) : 0;
  return h('div', { key: c.id, class: ['side-item', 'corpus-item', s.selected === c.id && 'active', !inProject && 'foreign'], role: 'button', tabindex: 0, onclick: () => choose(c.id) },
    h('div', { class: 'side-item-text' },
      h('div', { class: 'side-item-title', title: c.name }, c.name),
      h('div', { class: 'side-item-sub' }, c.sources_info.map(i => i.label).join(', ')),
      inProject && h('div', { class: 'mini-progress', title: t('{n} % indexiert', { n: pct }) }, h('i', { style: { width: pct + '%' } })),
      inProject ? h('div', { class: 'side-item-sub' }, !c.synced ? t('noch nicht abgeglichen')
        : t('{a} von {b} Texten indexiert', { a: fmtInt(nIndexed(x)), b: fmtInt(x.documents) })
          + (x.refresh ? ` (${t('davon {n} zu aktualisieren', { n: fmtInt(x.refresh) })})` : '')
          + (x.to_embed ? ` · ${t('{n} einzubetten', { n: fmtInt(x.to_embed) })}` : '') + (x.pending ? ` · ${t('{n} offen', { n: fmtInt(x.pending) })}` : ''))
        : h('div', { class: 'side-item-sub' }, c.project_ids.length ? t('in {names}', { names: c.project_ids.map(id => (state.projects.find(p => p.id === id) || {}).name).filter(Boolean).join(', ') }) : t('in keinem Projekt'))),
    !inProject && iconBtn('plus', t('Zu diesem Projekt hinzufügen'), e => { e.stopPropagation(); assignToProject(c, true); }),
    iconBtn('more', t('Weitere Aktionen'), e => corpusMenu(e, c)));
}

function corpusList() {
  const s = st();
  const mine = projectCorpora();
  const others = state.corpora.filter(c => !mine.includes(c));
  const p = project();
  return h('aside', { class: 'side-list corpus-list', ...paneProps('corpora', 270) },
    btn(t('Neuer Korpus'), { kind: 'primary', icon: 'plus', onClick: async () => { if (await guardDirty()) selectCorpus('new'); requestAnimationFrame(() => document.getElementById('corpus-name')?.focus()); } }),
    h('div', { class: 'side-items' },
      h('div', { class: 'side-group-label' }, t('In „{name}“', { name: p ? p.name : t('diesem Projekt') })),
      s.selected === 'new' && h('div', { class: 'side-item active', key: 'new' }, h('div', { class: 'side-item-text' },
        h('div', { class: 'side-item-title' }, (s.draft && s.draft.name) || t('Neuer Korpus')), h('div', { class: 'side-item-sub' }, t('noch nicht gespeichert')))),
      mine.map(c => corpusItem(c, true)),
      !mine.length && s.selected !== 'new' ? h('p', { class: 'muted small pad-x' }, t('Noch kein Korpus in diesem Projekt.')) : null,
      others.length ? h('details', { class: 'side-group', open: s.showOthers, ontoggle: e => { s.showOthers = e.target.open; } },
        h('summary', { class: 'side-group-label' }, t('Weitere Korpora ({n})', { n: others.length })),
        others.map(c => corpusItem(c, false))) : null),
    splitter('corpora', { def: 270, max: 520 }));
}

function stat(v, label, kind, title, sub = null) {
  return h('div', { class: ['stat', kind && `stat-${kind}`], title }, h('div', { class: 'stat-v' }, v), h('div', { class: 'stat-l' }, label),
    sub && h('div', { class: 'stat-sub' }, sub));
}

function statsRow(c) {
  const s = st();
  // Gespeicherter Stand oder Vorschau der aktuellen Auswahl
  const usePreview = s.dirty || !c;
  if (usePreview && !s.preview) {
    if (s.draft && s.draft.sources.size) refreshPreview();
    return null;
  }
  const x = usePreview ? s.preview.stats : c.stats;
  const unsynced = usePreview ? s.preview.unsynced : (c.synced ? [] : c.libraries);
  const names = (state.tree && state.tree.libraries) || [];
  const libName = lib => (names.find(l => l.lib === lib) || { name: lib }).name;
  return h('div', { class: 'stack-sm' },
    h('div', { class: 'corpus-stats' },
      stat(unsynced.length ? '–' : fmtInt(x.items), t('Einträge'), null, t('Einträge in den gewählten Sammlungen (ohne Notizen)')),
      stat(unsynced.length ? '–' : fmtInt(x.documents), t('Texte (PDF u. a.)'), null, t('Dateien mit Text, die indexiert werden können')),
      // Texte = indexiert + einzubetten + offen + ohne Text/Fehler; „zu aktualisieren“ ist ein Teil von „indexiert“
      stat(fmtInt(nIndexed(x)), t('indexiert'), 'ok', x.refresh ? `${t('mit {m} durchsuchbar', { m: modelLabel() })}. ${refreshHint()}` : t('mit {m} durchsuchbar', { m: modelLabel() }),
        x.refresh ? [icon('refresh', 11), ' ', t('davon {n} zu aktualisieren', { n: fmtInt(x.refresh) })] : null),
      x.to_embed ? stat(fmtInt(x.to_embed), t('einzubetten'), 'warn', `${t('Text gelesen, für {m} noch nicht eingebettet', { m: modelLabel() })}. ${embedHint()}`) : null,
      stat(unsynced.length ? '–' : fmtInt(x.pending), t('offen'), x.pending ? 'warn' : null, openHint(modelLabel())),
      stat(fmtInt(x.no_text + x.error), t('ohne Text / Fehler'), x.no_text + x.error ? 'err' : null),
      stat(fmtInt(x.embedded), t('Abschnitte durchsuchbar'))),
    usePreview && h('div', { class: 'muted small' }, t('Vorschau für die aktuelle Auswahl (noch nicht gespeichert).')),
    unsynced.length ? notice('info', t('Für {libs} gibt es noch keinen Abgleich mit Zotero – die Anzahl der Texte erscheint danach.', { libs: unsynced.map(libName).join(', ') }),
      h('div', { class: 'notice-actions' }, btn(t('Jetzt abgleichen'), { size: 'sm', icon: 'refresh', disabled: !!runningJob('catalog'), why: t('Abgleich läuft bereits.'), onClick: syncLibraries }))) : null);
}

function corpusHeader() {
  const s = st();
  const c = state.corpora.find(x => x.id === s.selected);
  const d = s.draft;
  const x = c && c.stats;
  return h('div', { class: 'corpus-head card' },
    h('div', { class: 'row' },
      h('div', { class: 'grow stack-sm' },
        textInput({ id: 'corpus-name', class: 'input-title', value: d.name, placeholder: t('Name des Wissenskorpus, z. B. „KI und Jugend“'),
          onInput: v => { d.name = v; if (!s.dirty) { s.dirty = true; update(); } } }),
        textInput({ value: d.description, placeholder: t('Beschreibung (optional)'), onInput: v => { d.description = v; if (!s.dirty) { s.dirty = true; update(); } } })),
      h('div', { class: 'row' },
        s.dirty && c && btn(t('Verwerfen'), { kind: 'ghost', onClick: () => selectCorpus(c.id) }),
        btn(s.selected === 'new' ? t('Korpus anlegen') : t('Speichern'), { kind: s.dirty ? 'primary' : 'secondary', icon: 'check', busy: s.saving, disabled: !s.dirty, onClick: save }),
        c && iconBtn('more', t('Weitere Aktionen'), e => corpusMenu(e, c)))),
    c && !c.project_ids.includes(state.projectId) && notice('info', t('Dieser Korpus gehört nicht zum aktiven Projekt.'),
      h('div', { class: 'notice-actions' }, btn(t('Zu diesem Projekt hinzufügen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => assignToProject(c, true) }))),
    // Ausgewählte Quellen
    h('div', { class: 'chips' }, d.sources.size ? [...d.sources].map(id => {
      const info = (c ? c.sources_info.find(i => i.id === id) : null) || describe(id);
      const ic = info.kind === 'library' ? 'library' : info.kind === 'item' ? 'file' : 'folder';
      return h('span', { class: ['chip', info.kind === 'library' && 'chip-lib', info.kind === 'item' && 'chip-item'], key: id, title: info.path },
        icon(ic, 13), h('span', null, info.label),
        h('button', { class: 'chip-x', title: t('Entfernen'), onclick: () => toggleSource(id, false) }, icon('x', 11)));
    }) : h('span', { class: 'muted small' }, t('Noch nichts ausgewählt – unten Sammlungen oder ganze Bibliotheken anhaken, einzelne Einträge über „Suchen“ hinzufügen.'))),
    statsRow(c),
    c && !s.dirty && x.to_embed ? notice('warning', x.to_embed === 1
      ? t('1 Text dieses Korpus ist gelesen, aber für {m} noch nicht eingebettet – die Bedeutungssuche findet ihn noch nicht.', { m: modelLabel() })
      : t('{t} dieses Korpus sind gelesen, aber für {m} noch nicht eingebettet – die Bedeutungssuche findet sie noch nicht.', { t: nTexts(x.to_embed), m: modelLabel() }),
      h('div', { class: 'notice-actions' }, btn(t('Jetzt einbetten'), { size: 'sm', kind: 'primary', icon: 'play', onClick: () => startEmbedding(c.id) })),
      { dismiss: `toembed:${c.id}:${modelLabel()}:${x.documents}` }) : null,
    c && !s.dirty && h('div', { class: 'corpus-actions' },
      btn(c.synced ? t('Indexieren') : t('Abgleichen und indexieren'), { kind: !c.synced || x.pending ? 'primary' : 'secondary', icon: 'play', onClick: () => indexCorpus(c) }),
      btn(t('Fragen stellen'), { icon: 'chat', disabled: !x.embedded, why: x.to_embed ? t('Erst für {m} einbetten', { m: modelLabel() }) : t('Noch keine Texte indexiert'), onClick: () => { ui('ask', {}).corpora = [c.id]; navigate('ask'); } }),
      btn(t('Forschungsstand'), { icon: 'review', disabled: !x.embedded, why: x.to_embed ? t('Erst für {m} einbetten', { m: modelLabel() }) : t('Noch keine Texte indexiert'), onClick: () => { ui('review', {}).presetCorpus = c.id; ui('review', {}).openId = 'new'; navigate('review'); } }),
      btn(t('Texte ansehen'), { icon: 'file', kind: 'ghost', onClick: () => { Object.assign(ui('index', {}), { corpus: c.id, corpusFor: state.projectId }); navigate('index'); } })));
}

function describe(id) {
  const e = treeIndex().get(id);
  if (!e) return { id, label: id, path: id, kind: id.endsWith(':*') ? 'library' : id.includes(':@') ? 'item' : 'collection' };
  if (e.node === e.lib) return { id, label: e.lib.name, path: t('ganze Bibliothek'), kind: 'library' };
  return { id, label: e.node.name, path: e.lib.name, kind: 'collection' };
}

function matches(node, q) {
  if (!q) return true;
  if (node.name.toLowerCase().includes(q)) return true;
  return (node.children || node.collections || []).some(n => matches(n, q));
}

function treeNode(node, depth, lib, inherited) {
  const s = st();
  const q = s.search.trim().toLowerCase();
  if (!matches(node, q)) return null;
  const kids = node.children || node.collections || [];
  const open = q ? true : s.expanded.has(node.id);
  const selected = s.draft.sources.has(node.id);
  const covered = inherited && !selected;
  const isLib = node === lib;
  return h('div', { key: node.id, class: 'tree-node' },
    h('div', { class: ['tree-row', isLib && 'tree-lib', isLib && (lib.type === 'group' ? 'tree-lib-group' : 'tree-lib-user'), (selected || covered) && 'is-selected'],
      style: { paddingLeft: (8 + depth * 18) + 'px' } },
    kids.length ? h('button', { class: 'tree-twisty', title: open ? t('Zuklappen') : t('Aufklappen'),
      onclick: () => { if (open) s.expanded.delete(node.id); else s.expanded.add(node.id); update(); } }, icon(open ? 'chevronDown' : 'chevronRight', 14))
      : h('span', { class: 'tree-twisty' }),
    checkbox({ checked: selected || covered, disabled: covered, title: covered ? t('Über die übergeordnete Auswahl enthalten') : isLib ? t('Ganze Bibliothek') : t('Sammlung inkl. Untersammlungen'),
      onChange: v => toggleSource(node.id, v) }),
    icon(isLib ? (lib.type === 'group' ? 'users' : 'user') : 'folder', 15, 'tree-icon'),
    h('span', { class: 'tree-name', onclick: () => { if (kids.length) { if (open) s.expanded.delete(node.id); else s.expanded.add(node.id); update(); } } }, node.name),
    isLib && h('span', { class: 'tree-hint' }, t('ganze Bibliothek')),
    node.num_items != null && h('span', { class: 'tree-count', title: t('Einträge direkt darin') }, fmtInt(node.num_items))),
    open && kids.length ? h('div', { class: 'tree-children' }, kids.map(k => treeNode(k, depth + 1, lib, inherited || selected))) : null);
}

function treePanel() {
  const s = st();
  const tree = state.tree;
  if (!tree) { loadTree(); }
  if (!tree || (s.loadingTree && !tree)) {
    return h('section', { class: 'card tree-card' }, h('div', { class: 'row muted' }, spinner(16), t('Lese Bibliotheken und Sammlungen aus Zotero …')));
  }
  ensureExpanded(s.draft ? [...s.draft.sources] : []);
  const user = tree.libraries.filter(l => l.type === 'user');
  const groups = tree.libraries.filter(l => l.type === 'group');
  return h('section', { class: 'card tree-card' },
    h('div', { class: 'card-head tree-head' },
      h('h3', null, icon('zotero', 16), t('Zotero-Bibliothek')),
      h('div', { class: 'tree-search' }, icon('search', 14), h('input', { class: 'input input-sm', value: s.search, placeholder: t('Sammlung suchen …'),
        oninput: e => { s.search = e.target.value; update(); } })),
      h('div', { class: 'card-actions' },
        iconBtn('expand', t('Alle aufklappen'), () => { tree.libraries.forEach(l => { s.expanded.add(l.id); walk(l.collections, n => s.expanded.add(n.id)); }); update(); }),
        iconBtn('collapse', t('Alle zuklappen'), () => { s.expanded = new Set(); update(); }),
        btn(s.loadingTree ? t('Lese …') : t('Aktualisieren'), { size: 'sm', kind: 'ghost', icon: 'refresh', busy: s.loadingTree, onClick: () => loadTree(true) }))),
    !tree.online && notice('warning', t('Zotero ist nicht erreichbar – angezeigt wird der zuletzt bekannte Stand. Zum Abgleichen und Indexieren muss Zotero geöffnet sein.'), null,
      { dismiss: 'zotero-offline', session: true }),
    h('div', { class: 'tree' },
      user.length ? h('div', { class: 'tree-group-label tree-group-user' }, icon('user', 13), t('Eigene Bibliothek')) : null,
      user.map(l => treeNode(l, 0, l, false)),
      groups.length ? h('div', { class: 'tree-group-label tree-group-groups' }, icon('users', 13), t('Gruppen ({n})', { n: groups.length })) : null,
      groups.map(l => treeNode(l, 0, l, false))),
    h('div', { class: 'muted small' }, t('Eine angehakte Sammlung schliesst ihre Untersammlungen ein.'), ' ', s.treeAt ? t('Stand: {ago}.', { ago: fmtAgo(s.treeAt) }) : ''));
}

export function corporaView() {
  const s = st();
  const nav = state.ui.corporaNav;
  if (nav && nav.open != null) { const id = nav.open; nav.open = null; if (state.corpora.find(c => c.id === id)) selectCorpus(id); }
  const mine = projectCorpora();
  if (s.selected === null && mine.length) selectCorpus(mine[0].id);
  if (s.selected !== null && s.selected !== 'new' && !state.corpora.find(c => c.id === s.selected)) { s.selected = null; s.draft = null; }
  const hasEditor = s.selected !== null && s.draft;
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Wissenskorpora'), t('Bestimme, welche Sammlungen aus Zotero durchsucht und indexiert werden')),
    h('div', { class: 'two-col' },
      corpusList(),
      h('div', { class: ['col-main', hasEditor ? 'col-fill' : 'scroll'] }, hasEditor
        ? h('div', { class: 'corpus-editor' }, corpusHeader(), treePanel())
        : emptyState('corpus', t('Noch kein Wissenskorpus in diesem Projekt'),
          t('Ein Wissenskorpus bündelt Sammlungen aus deiner Zotero-Bibliothek oder aus Gruppen. Zotivity indexiert genau diese Texte; bei Fragen und beim Forschungsstand wählst du die Korpora des Projekts aus. Korpora aus anderen Projekten lassen sich links unter „Weitere Korpora“ hinzufügen.'),
          btn(t('Ersten Korpus anlegen'), { kind: 'primary', icon: 'plus', onClick: () => { selectCorpus('new'); requestAnimationFrame(() => document.getElementById('corpus-name')?.focus()); } })))));
}

export { plural };
