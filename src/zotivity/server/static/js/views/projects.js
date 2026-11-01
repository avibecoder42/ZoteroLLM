// Projekte: Anlegen, Wechseln, Umbenennen, als Datei exportieren/importieren, Duplizieren, Archivieren, Löschen.
import { h } from '../core/vdom.js';
import { state, update, toast, run, ui, openModal, closeModal, loadProjects, openProject, loadCorpora, openProjects,
  archivedProjects, loadSettings, loadStatus, loadSetup } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { field, textInput, textArea, checkbox, notice, select } from '../ui/components.js';
import { navigate } from './shell.js';
import { projectEmbeddingOptions } from './embedmodels.js';

export const COLORS = ['#4a43c4', '#0b7285', '#2f7d4f', '#a35c00', '#b3261e', '#7a3fb0', '#2563a8', '#6b5e4f'];

export function projectColor(p) {
  return (p && p.color) || COLORS[((p && p.id) || 0) % COLORS.length];
}

export function initials(name) {
  const words = String(name || '?').trim().split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w));
  return ((words[0] || '?')[0] + (words.length > 1 ? words[1][0] : (words[0] || '').slice(1, 2))).toUpperCase();
}

export function projectBadge(p, size = 30) {
  return h('span', { class: 'project-badge', style: { background: projectColor(p), width: size + 'px', height: size + 'px', fontSize: Math.round(size * 0.4) + 'px' } },
    initials(p ? p.name : '?'));
}

function projectForm(values, { title, ok, onSubmit, embeddingOptions = null }) {
  const pin = values.embedding;
  const v = { name: values.name || '', description: values.description || '', color: values.color || '',
    embedding: pin ? `${pin.provider}|${pin.model}` : '' };
  openModal({
    title,
    body: () => h('div', { class: 'stack' },
      field(t('Name'), textInput({ value: v.name, id: 'project-name', placeholder: t('z. B. „KI und Jugend“'), onInput: x => { v.name = x; },
        onKeyDown: e => { if (e.key === 'Enter') { v.name = e.target.value; onSubmit(v); } } })),
      field(t('Beschreibung (optional)'), textArea({ value: v.description, rows: 2, onInput: x => { v.description = x; } })),
      field(t('Farbe'), h('div', { class: 'swatches' }, COLORS.map(c => h('button', { key: c, type: 'button', title: c,
        class: ['swatch', (v.color || projectColor(values)) === c && 'active'], style: { background: c },
        onclick: () => { v.color = c; update(); } })))),
      embeddingOptions && field(t('Embedding-Modell des Projekts'), select({ value: v.embedding, options: embeddingOptions, label: t('Embedding-Modell'),
        onChange: x => { v.embedding = x; } }),
      { hint: t('Mit eigenem Modell schaltet Zotivity beim Öffnen des Projekts auf dieses Modell um. Jedes Modell hat seinen eigenen Index; noch nicht eingebettete Texte bettet die nächste Indexierung ein.') })),
    actions: [{ label: t('Abbrechen'), onClick: closeModal }, { label: ok, kind: 'primary', onClick: () => onSubmit(v) }],
  });
  requestAnimationFrame(() => document.getElementById('project-name')?.focus());
}

export function newProjectDialog() {
  projectForm({}, { title: t('Neues Projekt'), ok: t('Anlegen'), onSubmit: async v => {
    if (!v.name.trim()) { toast(t('Bitte einen Namen eingeben.'), 'warning'); return; }
    const p = await run(() => api.post('/api/projects', { name: v.name.trim(), description: v.description, color: v.color }));
    closeModal();
    await openProject(p.id);
    navigate('start');
    toast(t('Projekt „{name}“ angelegt. Lege jetzt einen Wissenskorpus an oder füge einen bestehenden hinzu.', { name: p.name }), 'success', 7000,
      { label: t('Zu den Korpora'), onClick: () => navigate('corpora') });
  } });
}

export async function editProjectDialog(p) {
  const embeddingOptions = await projectEmbeddingOptions(p.embedding).catch(() => null);
  projectForm(p, { title: t('Projekt bearbeiten'), ok: t('Speichern'), embeddingOptions, onSubmit: async v => {
    if (!v.name.trim()) { toast(t('Bitte einen Namen eingeben.'), 'warning'); return; }
    const body = { name: v.name.trim(), description: v.description, color: v.color };
    if (embeddingOptions) {
      const [provider, ...rest] = v.embedding.split('|');
      body.embedding = v.embedding ? { provider, model: rest.join('|') } : null;
    }
    const r = await run(() => api.put(`/api/projects/${p.id}`, body));
    closeModal();
    await loadProjects();
    if (r.embedding_switched) await embeddingSwitched(r.embedding_switched);
  } });
}

// Das Projekt hat ein eigenes Embedding-Modell und es wurde aktiviert
export async function embeddingSwitched(sw) {
  await loadSettings();
  loadStatus(); loadSetup();
  ui('embmodels').data = null;
  toast(t('Embedding-Modell des Projekts aktiviert: {m}', { m: sw.model }), 'info', 6000);
}

export async function exportProject(p) {
  const saved = await run(() => api.saveUrl(`${p.name.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'projekt'}.zoty`, `/api/projects/${p.id}/export`));
  if (saved) toast(typeof saved === 'string' ? t('Gespeichert: {path}', { path: saved }) : t('Projektdatei gespeichert.'), 'success', 5000);
}

export function importProject() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.zoty,.zllm,application/zip';  // .zllm: Projektdateien aus Versionen bis 1.0.1
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    let r;
    try {
      const res = await fetch('/api/projects/import', { method: 'POST', headers: { 'X-Zotivity': '1', 'Content-Type': 'application/zip' }, body: file });
      r = await res.json();
      if (!res.ok) throw new Error(r.detail || res.statusText);
    } catch (err) { toast(t('Import fehlgeschlagen: {e}', { e: err.message }), 'error', 9000); return; }
    await loadCorpora();
    await openProject(r.project_id);
    navigate('start');
    openModal({
      title: t('Projekt „{name}“ importiert', { name: r.name }),
      body: () => h('div', { class: 'stack' },
        h('ul', null,
          h('li', null, t('{a} Korpora neu angelegt, {b} vorhandene verwendet', { a: r.corpora_created, b: r.corpora_reused })),
          h('li', null, t('{c} Chats, {r} Forschungsstände, {s} Auswertungsblätter', { c: r.chats, r: r.reviews, s: r.sheets }))),
        r.missing_sources.length ? notice('warning', h('span', null, t('Diese Sammlungen gibt es in deinem Zotero nicht – die Korpora finden dafür nichts:'),
          h('ul', null, r.missing_sources.map(m => h('li', { key: m }, m))))) : null,
        !r.checked ? notice('info', t('Zotero war nicht erreichbar; ob alle Sammlungen vorhanden sind, zeigt sich beim nächsten Abgleich.')) : null,
        notice('info', t('Der Index wird nicht mitgeliefert. Neue Texte erscheinen nach „Index → Alle Korpora indexieren“.'))),
      actions: [{ label: t('OK'), kind: 'primary', onClick: closeModal }],
    });
  };
  input.click();
}

export async function duplicateProject(p) {
  const r = await run(() => api.post(`/api/projects/${p.id}/duplicate`));
  await openProject(r.project_id);
  toast(t('Kopie „{name}“ angelegt.', { name: r.name }), 'success');
}

// Reihenfolge von Hand: fromId vor (after = false) bzw. hinter toId setzen. Sofort anzeigen, dann speichern.
export async function moveProject(fromId, toId, after) {
  const ids = openProjects().map(p => p.id).filter(id => id !== fromId);
  const i = ids.indexOf(toId);
  if (i < 0 || fromId === toId) return;
  ids.splice(after ? i + 1 : i, 0, fromId);
  const byId = new Map(state.projects.map(p => [p.id, p]));
  state.projects = [...ids.map(id => byId.get(id)), ...archivedProjects()];
  update();
  try { await run(() => api.post('/api/projects/reorder', { ids })); } finally { await loadProjects(); }
}

// Zuletzt geöffnetes offenes Projekt ausser p (Ersatz, wenn das aktive Projekt archiviert oder gelöscht wird)
function nextOpenProject(p) {
  return openProjects().filter(x => x.id !== p.id).sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0))[0] || null;
}

// Archivieren: Projekt verschwindet aus Liste und Umschalter, bleibt aber vollständig erhalten (zurückholbar)
export async function archiveProject(p, archived = true) {
  const next = archived ? nextOpenProject(p) : null;
  if (archived && !next) { toast(t('Das letzte offene Projekt kann nicht archiviert werden.'), 'warning'); return; }
  await run(() => api.post(`/api/projects/${p.id}/archive`, { archived }));
  if (archived && state.projectId === p.id) await openProject(next.id);
  else await loadProjects();
  if (archived) {
    toast(t('Projekt „{name}“ archiviert. Unter „Projekt → Archiv“ lässt es sich jederzeit zurückholen.', { name: p.name }), 'success', 7000,
      { label: t('Rückgängig'), onClick: () => archiveProject(p, false) });
  } else {
    toast(t('Projekt „{name}“ aus dem Archiv geholt.', { name: p.name }), 'success', 6000,
      { label: t('Öffnen'), onClick: async () => { await openProject(p.id); navigate('start'); } });
  }
}

export async function deleteProject(p) {
  if (state.projects.length <= 1) { toast(t('Das letzte Projekt kann nicht gelöscht werden.'), 'warning'); return; }
  if (!p.archived_at && !nextOpenProject(p)) { toast(t('Das letzte offene Projekt kann nicht gelöscht werden.'), 'warning'); return; }
  const exclusive = p.corpus_ids.filter(id => { const c = state.corpora.find(x => x.id === id); return c && c.project_ids.length === 1; });
  const opts = { corpora: false };
  openModal({
    title: t('Projekt „{name}“ löschen?', { name: p.name }),
    body: () => h('div', { class: 'stack' },
      h('p', null, t('Gelöscht werden {c} Chats und {r} Forschungsstände dieses Projekts. Der Index und Zotero bleiben unverändert.', { c: p.chats, r: p.reviews })),
      exclusive.length ? checkbox({ checked: opts.corpora, onChange: x => { opts.corpora = x; update(); },
        label: exclusive.length === 1 ? t('Auch die Korpus-Definition löschen, die nur in diesem Projekt verwendet wird')
          : t('Auch die {n} Korpus-Definitionen löschen, die nur in diesem Projekt verwendet werden', { n: exclusive.length }) }) : null,
      h('p', { class: 'muted small' }, t('Tipp: Vorher „Als Datei exportieren“, dann lässt sich das Projekt später wieder importieren.'))),
    actions: [{ label: t('Abbrechen'), onClick: closeModal }, { label: t('Löschen'), kind: 'danger', onClick: async () => {
      closeModal();
      await run(() => api.del(`/api/projects/${p.id}?delete_corpora=${opts.corpora}`));
      const wasActive = state.projectId === p.id;
      const next = nextOpenProject(p);
      await loadCorpora();
      if (wasActive && next) await openProject(next.id);
      else await loadProjects();
      toast(t('Projekt gelöscht.'), 'success');
    } }],
  });
}

export function projectMenuItems(p) {
  const open = openProjects();
  const i = open.findIndex(x => x.id === p.id);
  return [
    state.projectId !== p.id && { label: t('Öffnen'), icon: 'chevronRight', onClick: () => openProject(p.id) },
    { label: t('Bearbeiten …'), icon: 'edit', onClick: () => editProjectDialog(p) },
    i > 0 && { label: t('Nach oben'), icon: 'chevronUp', onClick: () => moveProject(p.id, open[i - 1].id, false) },
    i >= 0 && i < open.length - 1 && { label: t('Nach unten'), icon: 'chevronDown', onClick: () => moveProject(p.id, open[i + 1].id, true) },
    { label: t('Als Datei exportieren …'), icon: 'download', onClick: () => exportProject(p) },
    { label: t('Duplizieren'), icon: 'copy', onClick: () => duplicateProject(p) },
    { label: t('Archivieren'), icon: 'archive', onClick: () => archiveProject(p) },
    '-',
    { label: t('Löschen …'), icon: 'trash', danger: true, onClick: () => deleteProject(p) },
  ];
}

export function archivedMenuItems(p) {
  return [
    { heading: t('Archiviertes Projekt') },
    { label: t('Aus dem Archiv holen'), icon: 'unarchive', onClick: () => archiveProject(p, false) },
    { label: t('Zurückholen und öffnen'), icon: 'chevronRight', onClick: async () => {
      await run(() => api.post(`/api/projects/${p.id}/archive`, { archived: false }));
      await openProject(p.id);
      navigate('start');
    } },
    { label: t('Als Datei exportieren …'), icon: 'download', onClick: () => exportProject(p) },
    '-',
    { label: t('Löschen …'), icon: 'trash', danger: true, onClick: () => deleteProject(p) },
  ];
}

// Umschalter oben in der Navigationsleiste (auch Strg+P); archivierte Projekte nur als Verweis aufs Archiv
export function switcherItems() {
  const archived = archivedProjects().length;
  return [
    { heading: t('Projekt wechseln') },
    ...openProjects().map(p => ({ label: p.name, swatch: projectColor(p), active: p.id === state.projectId,
      hint: p.id === state.projectId ? t('aktiv') : '', onClick: () => openProject(p.id) })),
    '-',
    { label: t('Neues Projekt …'), icon: 'plus', onClick: newProjectDialog },
    { label: t('Projekt importieren …'), icon: 'download', onClick: importProject },
    { label: t('Alle Projekte'), icon: 'home', onClick: () => navigate('start') },
    archived && { label: t('Archiv ({n})', { n: archived }), icon: 'archive', onClick: () => { ui('projectsNav', {}).archiveOpen = true; navigate('start'); } },
  ];
}

export { icon };
