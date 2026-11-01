// Projekte: Liste, neues Projekt; Tabs „Projekt“ (Fragestellung, Kriterien, Reviewende, Ziel in Zotero) und „Datenbanken“.
// Der Entwurf des Formulars gilt auch für den Tab „Ordner“ (folders.js) und wird automatisch gespeichert.
import { h } from '../../core/vdom.js';
import { update, ui, run, toast, confirmDialog } from '../../core/store.js';
import * as api from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { fmtDate } from '../../core/util.js';
import { btn, iconBtn, card, field, textInput, textArea, select, segmented, checkbox, notice, emptyState, badge } from '../../ui/components.js';
import { icon } from '../../ui/icons.js';
import { R, rs, enc, loadProjects, openProject, closeProject, summaryLine, busy, isBusy, aiInfo, aiEstimate, tokenText,
  noteUsage, zotivityProject, assignProject, saveLater, savePending, saveState, loadInfo, targetName } from './common.js';
import { navigate } from '../shell.js';

// ------------------------------------------------------------------ Liste
export function projectList() {
  const s = rs();
  if (s.projects == null) {
    loadProjects().catch(err => toast(err.message, 'error'));
    return h('div', { class: 'center-pad muted' }, t('Lade Projekte …'));
  }
  if (!zotivityProject()) return emptyState('search', t('Kein Projekt geöffnet'), t('Eine Recherche gehört zu einem Projekt – zuerst unter Einrichtung ein Projekt öffnen oder anlegen.'));
  const create = () => busy('create', async () => {
    const p = await api.post(`${R}/projects`, { title: zotivityProject().name || t('Neue Recherche'), settings: { zotllm_project: zotivityProject().id } });
    loadInfo().catch(() => {});
    await loadProjects();
    openProject(p.id, 'project');
  });
  const tile = (p, extra) => h('div', { key: p.id, class: 'row' },
    h('button', { type: 'button', class: 'rs-project-tile grow', onclick: () => openProject(p.id) },
      h('div', { class: 'grow' }, h('b', null, p.title),
        p.question && h('div', { class: 'muted small rs-clamp' }, p.question),
        h('div', { class: 'small' }, summaryLine(p.summary))),
      h('div', { class: 'muted small nowrap' }, fmtDate(p.updated_at))), extra);
  return h('div', { class: 'view-body scroll' },
    h('div', { class: 'rs-narrow stack' },
      h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('Recherchen in „{p}“', { p: zotivityProject().name })),
        btn(t('Neue Recherche'), { kind: 'primary', icon: 'plus', onClick: create, busy: isBusy('create') })),
      s.projects.length ? s.projects.map(p => tile(p))
        : emptyState('search', t('Noch keine Recherche'), t('Eine Recherche hält Fragestellung, Kriterien, Suchstrings, Treffer und Entscheide zusammen.'),
          btn(t('Neue Recherche'), { kind: 'primary', icon: 'plus', onClick: create })),
      // Recherchen ohne (gültiges) Projekt, z. B. nach dem Löschen eines Projekts: nie still verloren, hier zuordnen
      (s.unassigned || []).length ? h('div', { class: 'stack-sm' }, h('h3', null, t('Ohne Projekt')),
        s.unassigned.map(p => tile(p, btn(t('Diesem Projekt zuordnen'), { size: 'sm', icon: 'plus', busy: isBusy(`assign${p.id}`),
          onClick: () => busy(`assign${p.id}`, () => assignProject(p.id)) })))) : null));
}

// ------------------------------------------------------------------ Formular
const FIELDS = ['title', 'question', 'description', 'criteria_in', 'criteria_out', 'target_library', 'target_name', 'zotero_backend', 'folder_map'];

export function draft() {
  const s = rs();
  const st = ui('rs-project', { pid: null, d: null, dirty: false });
  if (st.pid !== s.pid || !st.d) {
    const p = s.project;
    st.pid = s.pid;
    st.d = Object.fromEntries(FIELDS.map(k => [k, JSON.parse(JSON.stringify(p[k] ?? ''))]));
    st.d.folder_map = (p.folder_map || []).map(f => ({ slot: Number(f.slot), label: f.label || '', path: f.path || '' }))
      .sort((a, b) => a.slot - b.slot);
    st.dirty = false;
  }
  return st;
}

export function zoteroLibraries(backend) {
  const s = rs();
  const z = s.zotero[backend] || (s.zotero[backend] = { libraries: null, collections: {}, error: null });
  if (z.libraries == null && !z.loading) {
    z.loading = true;
    api.get(`${R}/zotero/libraries?backend=${enc(backend)}`).then(r => { z.libraries = r.libraries; z.error = null; })
      .catch(err => { z.libraries = []; z.error = err.message; }).finally(() => { z.loading = false; update(); });
  }
  return z;
}

export function collectionPaths(backend, lib) {
  const z = zoteroLibraries(backend);
  if (!lib) return [];
  if (z.collections[lib] === undefined) {
    z.collections[lib] = null;
    api.get(`${R}/zotero/collections?backend=${enc(backend)}&lib=${enc(lib)}`).then(r => { z.collections[lib] = r.paths; })
      .catch(err => { z.collections[lib] = []; z.error = err.message; }).finally(update);
  }
  return z.collections[lib] || [];
}

// Entwurf speichern; „Projekt“ und „Ordner“ teilen ihn sich (auch nach dem Verschieben aus einem gelöschten Ordner)
export async function saveDraft(opts) {
  const s = rs();
  const pid = s.pid;
  const st = draft();
  const d = st.d;
  const titleChanged = d.title !== (s.project && s.project.title);
  const p = await api.put(`${R}/projects/${pid}`, { ...d, folder_map: d.folder_map.filter(f => f.path || f.label) }, opts);
  if (rs().pid !== pid) return;
  s.project = p;
  st.dirty = savePending('project');
  if (titleChanged) loadProjects().catch(() => {});
}

// Nach jeder Änderung am Entwurf: speichert kurz darauf von selbst
export function touchDraft() {
  draft().dirty = true;
  saveLater('project', saveDraft);
  update();
}

export function draftBar({ withDelete = false } = {}) {
  const s = rs();
  const remove = async () => {
    if (!(await confirmDialog(t('Projekt löschen?'), t('„{t}“ mit allen Suchstrings, Treffern und Entscheiden löschen? In Zotero bleibt alles, wie es ist.', { t: s.project.title }), { ok: t('Löschen'), danger: true }))) return;
    await run(() => api.del(`${R}/projects/${s.pid}`));
    closeProject();
  };
  return h('div', { class: 'row rs-draft-bar' },
    withDelete ? btn(t('Projekt löschen'), { kind: 'ghost', icon: 'trash', onClick: remove }) : null,
    h('span', { class: 'spacer' }),
    saveState());
}

// ------------------------------------------------------------------ Ziel in Zotero
const isGroup = lib => String(lib).startsWith('groups/');

function targetCard() {
  const s = rs();
  const st = draft();
  const d = st.d;
  const set = (k, v) => { d[k] = v; touchDraft(); };
  const backend = d.zotero_backend || 'local';
  const z = zoteroLibraries(backend);
  const libs = z.libraries || [];
  const hasWebKey = !!(s.info && s.info.keys && s.info.keys['zotero-web']);
  const reload = () => { delete s.zotero[backend]; update(); };
  return card(t('Ziel in Zotero'), 'zotero', h('div', { class: 'stack' },
    hasWebKey || backend === 'web' ? field(t('Zugang'), segmented({ value: backend, options: [
      { value: 'local', label: t('Zotero auf diesem Computer') }, { value: 'web', label: t('Zotero-Server (Web-API)') }],
    onChange: v => set('zotero_backend', v) }), { hint: backend === 'local'
      ? t('Lokale API von Zotero: Zotero muss laufen; Schreiben braucht eine Freigabe in Zotero (unter Übergabe).')
      : t('Schreibt über zotero.org; die Zotero-App übernimmt die Einträge beim nächsten Sync.') }) : null,
    z.error ? notice('warning', z.error, backend === 'web' ? h('div', { class: 'notice-actions' },
      btn(t('Schlüssel eingeben'), { size: 'sm', onClick: () => { ui('settings', {}).tab = 'zotero'; navigate('settings'); } }),
      btn(t('Zotero auf diesem Computer'), { size: 'sm', kind: 'ghost', onClick: () => set('zotero_backend', 'local') })) : null) : null,
    h('div', { class: 'row rs-target-row' },
      h('div', { class: 'grow' }, field(t('Zielbibliothek'), select({ value: d.target_library, options: [
        ...(libs.some(l => l.lib === d.target_library) ? [] : [{ value: d.target_library, label: targetName(d) }]),
        ...libs.map(l => ({ value: l.lib, label: isGroup(l.lib) ? t('Gruppe: {n}', { n: l.name }) : l.name }))],
      onChange: v => { d.target_name = (libs.find(l => l.lib === v) || {}).name || v; set('target_library', v); } }),
      { hint: z.libraries == null ? t('Lade Bibliotheken …') : t('Eigene Bibliothek oder eine Gruppe. Der Pool gleicht damit ab, die Ordner beziehen sich darauf.') })),
      iconBtn('refresh', t('Bibliotheken neu laden'), reload))));
}

// ------------------------------------------------------------------ Reviewende und Vorgehen beim Sichten
function selectionCard() {
  const s = rs();
  const x = ui(`rs-selection-${s.pid}`);
  const settings = s.project.settings || {};
  if (!x.names) { x.names = [0, 1, 2].map(i => (settings.reviewers || [])[i] || ''); x.note = settings.selection_note || ''; }
  const save = () => saveLater('selection', async opts => {
    const p = await api.put(`${R}/projects/${s.pid}`, { settings: { reviewers: x.names, selection_note: x.note,
      current_reviewer: settings.current_reviewer || x.names.find(n => n.trim()) || '' } }, opts);
    if (rs().pid === s.pid) s.project.settings = p.settings;
  });
  return card(t('Auswahlprozess'), 'users', h('div', { class: 'stack' },
    field(t('Reviewende (bis zu drei)'), h('div', { class: 'rs-reviewers' }, x.names.map((n, i) => textInput({ key: i, value: n, placeholder: t('Name {n}', { n: i + 1 }),
      onInput: v => { x.names[i] = v; save(); update(); } }))),
    { hint: t('Im Screening wählst du, wer gerade entscheidet. Die Namen stehen mit den Zahlen im Protokoll. Je Treffer zählt der Entscheid einer Person: Das ist kein unabhängiges Doppel-Screening.') }),
    field(t('Vorgehen (optional)'), textArea({ value: x.note, rows: 2, placeholder: t('z. B. Unklare Fälle wurden zu zweit besprochen.'), onInput: v => { x.note = v; save(); update(); } }),
      { hint: t('Für Protokoll und Bericht: wie gesichtet wurde und wie Uneinigkeit gelöst wurde.') })));
}

export function projectTab() {
  const st = draft();
  const d = st.d;
  const set = (k, v) => { d[k] = v; touchDraft(); };
  return h('div', { class: 'view-body scroll' },
    h('div', { class: 'rs-narrow stack-lg' },
      card(t('Fragestellung'), 'edit', h('div', { class: 'stack' },
        field(t('Titel'), textInput({ value: d.title, onInput: v => set('title', v), class: 'input-title' })),
        field(t('Fragestellung'), textArea({ value: d.question, rows: 3, onInput: v => set('question', v) })),
        field(t('Kurzbeschreibung'), textArea({ value: d.description, rows: 4, onInput: v => set('description', v),
          placeholder: t('z. B. aus dem Antrag') })),
        h('div', { class: 'field-row' },
          field(t('Einschlusskriterien'), textArea({ value: d.criteria_in, rows: 5, onInput: v => set('criteria_in', v) }),
            { hint: t('Eine Zeile je Kriterium.') }),
          field(t('Ausschlusskriterien'), textArea({ value: d.criteria_out, rows: 5, onInput: v => set('criteria_out', v) }),
            { hint: t('Eine Zeile je Grund – im Screening als Ausschlussgründe zur Wahl.') })))),
      selectionCard(),
      targetCard(),
      h('p', { class: 'muted small' }, t('Weiter: Datenbanken wählen, Suchstrategie aufbauen. Änderungen werden automatisch gespeichert.')),
      draftBar({ withDelete: true })));
}

export function databasesTab() {
  return h('div', { class: 'view-body scroll' },
    h('div', { class: 'rs-narrow stack-lg' }, databasesCard() || h('div', { class: 'muted' }, t('Lade …'))));
}

// ------------------------------------------------------------------ Datenbanken
// Disziplinen wählen → Vorschlag; die Auswahl trifft die Nutzerin bzw. der Nutzer. Gespeichert wird sofort.
// Dazu auf Wunsch ein KI-Vorschlag aus der Fragestellung (Claude oder Gemini): je Datenbank ein Satz Begründung, übernommen wird
// nur, was angeklickt wird.
const ACCESS_ORDER = ['live', 'license', 'export', 'never'];
const ACCESS_KIND = { live: 'success', license: 'warning', export: 'info', never: 'danger' };

async function saveSettings(patch) {
  const s = rs();
  const p = await run(() => api.put(`${R}/projects/${s.pid}`, { settings: patch }));
  s.project.settings = p.settings;
  ui('rs-strategy', {}).sourcesChanged = true;  // Suchstrings für die gewählten Quellen neu erzeugen; die Blöcke bleiben
  update();
}

function suggestionFor(disciplines) {
  const st = ui('rs-dbs', { key: null, list: [] });
  const key = disciplines.slice().sort().join(',');
  if (st.key !== key) {
    st.key = key;
    api.get(`${R}/sources/suggest?disciplines=${enc(key)}`).then(r => { st.list = r.sources; update(); }).catch(() => {});
  }
  return st.list;
}

// KI-Vorschlag: gilt für das Projekt, bis er verworfen wird (nicht gespeichert – beim Neuladen der Seite weg)
function aiSourcesBox(chosen, disciplines) {
  const s = rs();
  const info = s.info;
  const st = ui('rs-dbs-ai', { pid: null, result: null });
  if (st.pid !== s.pid) { st.pid = s.pid; st.result = null; }
  const r = st.result;
  if (!r) return null;
  const label = id => (info.catalog.find(c => c.id === id) || {}).label || id;
  const newDisc = r.disciplines.filter(d => !disciplines.includes(d));
  const newSources = r.sources.filter(x => !chosen.has(x.id)).map(x => x.id);
  const adopt = (sources, discs) => saveSettings({ sources: [...new Set([...chosen, ...sources])], disciplines: [...new Set([...disciplines, ...discs])] });
  return notice('info', h('div', { class: 'stack-sm' },
    h('b', null, t('KI-Vorschlag aus der Fragestellung ({m})', { m: r.model || r.label })),
    r.disciplines.length ? h('div', { class: 'row wrap small' }, t('Disziplinen: {d}', { d: r.disciplines.map(d => info.disciplines[d] || d).join(', ') }),
      newDisc.length ? btn(t('übernehmen'), { size: 'sm', kind: 'ghost', onClick: () => adopt([], newDisc) }) : badge(t('gewählt'), 'success')) : null,
    h('div', { class: 'rs-ai-sources' }, r.sources.map(x => h('div', { key: x.id, class: 'rs-ai-source' },
      h('div', null, h('b', { class: 'small' }, label(x.id)), ' ', badge(info.access[x.access] || x.access, ACCESS_KIND[x.access] || 'neutral'),
        x.access === 'live' && !x.in_app ? [' ', badge(t('noch nicht eingebaut'), 'neutral')] : null,
        h('div', { class: 'small' }, x.reason)),
      chosen.has(x.id) ? badge(t('gewählt'), 'success')
        : btn(t('übernehmen'), { size: 'sm', kind: 'ghost', icon: 'plus', onClick: () => adopt([x.id], []) })))),
    r.note ? h('div', { class: 'muted small' }, r.note) : null,
    r.used ? h('div', { class: 'muted small' }, t('Verbrauch: {u}', { u: tokenText(r.used, false) })) : null,
    h('div', { class: 'notice-actions' },
      newSources.length || newDisc.length ? btn(t('Alle übernehmen'), { size: 'sm', icon: 'plus', onClick: () => adopt(newSources, newDisc) }) : null,
      btn(t('Verwerfen'), { size: 'sm', kind: 'ghost', onClick: () => { st.result = null; update(); } }))));
}

async function askAiSources() {
  const s = rs();
  const st = ui('rs-dbs-ai', {});
  const r = await busy('ai-sources', () => api.post(`${R}/projects/${s.pid}/ai/sources`, {}));
  if (r) { st.pid = s.pid; st.result = r; noteUsage(r); update(); }
}

// Geschätzter Verbrauch eines KI-Vorschlags aus dem Projekttext (neu geschätzt, wenn sich der Text ändert)
const projectKey = p => [p.title, p.question, p.description, p.criteria_in, p.criteria_out].join('\u0001');
export function estimateLine(kind, body = {}, key = '') {
  if (!aiInfo().available) return null;
  const e = aiEstimate(kind, body, `${projectKey(rs().project)}|${key}`);
  return h('div', { class: 'muted small rs-ai-est' }, e ? t('Geschätzt: {u}', { u: tokenText(e) }) : t('Schätze Token …'));
}

function databasesCard() {
  const s = rs();
  const info = s.info;
  if (!info || !info.catalog) return null;
  const settings = s.project.settings || {};
  const chosen = new Set(settings.sources || []);
  const disciplines = settings.disciplines || [];
  const suggested = disciplines.length ? suggestionFor(disciplines) : [];
  const toggleSource = (id, on) => {
    const next = new Set(chosen);
    on ? next.add(id) : next.delete(id);
    saveSettings({ sources: [...next] });
  };
  const toggleDiscipline = d => {
    const next = disciplines.includes(d) ? disciplines.filter(x => x !== d) : [...disciplines, d];
    saveSettings({ disciplines: next });
  };
  const missing = suggested.filter(id => !chosen.has(id));
  const fits = c => !disciplines.length || c.disciplines.some(d => disciplines.includes(d)) || chosen.has(c.id);
  const st = ui('rs-dbs', { all: false });
  const rows = info.catalog.filter(c => st.all || fits(c));
  const keyHint = c => (c.key && c.key_ok === false
    ? h('div', { class: 'warn-text small' }, t('Schlüssel fehlt.'), ' ',
      h('button', { type: 'button', class: 'rs-link small', onclick: () => { ui('settings', {}).tab = 'databases'; navigate('settings'); } }, t('In den Einstellungen eingeben')))
    : null);
  const aiButton = aiInfo().available
    ? btn(t('KI-Vorschlag aus der Fragestellung'), { size: 'sm', icon: 'ai', busy: isBusy('ai-sources'), onClick: askAiSources,
      disabled: !((s.project.question || s.project.description || '').trim()),
      title: t('Sendet Titel, Fragestellung, Kurzbeschreibung und Kriterien an {m} ({v}). Übernommen wird nur, was du anklickst.',
        { m: aiInfo().label, v: aiInfo().vendor }) })
    : h('span', { class: 'muted small', title: aiInfo().message || '' }, t('KI-Vorschlag: unter Einstellungen › Sprachmodelle einen Schlüssel speichern'));
  return card(t('Datenbanken'), 'library', h('div', { class: 'stack' },
    aiInfo().available ? h('div', { class: 'row' }, h('span', { class: 'spacer' }), estimateLine('sources')) : null,
    h('p', { class: 'muted small' }, t('Disziplinen wählen – die App schlägt passende Datenbanken vor; welche du durchsuchst, entscheidest du. Direkt in der App laufen die offenen Datenbanken; aus den anderen importierst du RIS-Dateien (unter Suche & Import).')),
    field(t('Disziplinen'), h('div', { class: 'chips' }, Object.entries(info.disciplines).map(([id, label]) =>
      h('button', { type: 'button', key: id, class: ['chip', disciplines.includes(id) && 'chip-accent'], onclick: () => toggleDiscipline(id) },
        h('span', null, label))))),
    aiSourcesBox(chosen, disciplines),
    missing.length ? notice('info', h('div', null,
      t('Vorschlag für diese Disziplinen: {list}.', { list: missing.map(id => (info.catalog.find(c => c.id === id) || {}).label || id).join(', ') }),
      h('div', { class: 'notice-actions' }, btn(t('Vorschlag übernehmen'), { size: 'sm', icon: 'plus',
        onClick: () => saveSettings({ sources: [...new Set([...chosen, ...missing])] }) })))) : null,
    ACCESS_ORDER.map(access => {
      const list = rows.filter(c => c.access === access);
      if (!list.length) return null;
      if (access === 'never') {  // nur zur Information: nicht wählbar
        return h('div', { key: access, class: 'stack-sm' },
          h('div', { class: 'row' }, badge(info.access[access], ACCESS_KIND[access]), h('span', { class: 'muted small' }, t('nur zur Information – die App fragt sie nicht ab'))),
          h('div', { class: 'rs-dbs' }, list.map(c => h('div', { key: c.id, class: 'rs-db rs-db-never' },
            h('div', { class: 'row' }, icon('x', 14), h('span', null, c.label)),
            h('div', { class: 'muted small' }, c.note, c.terms ? [' ', h('a', { href: c.terms, target: '_blank', rel: 'noopener' }, t('Bedingungen'))] : null)))));
      }
      return h('div', { key: access, class: 'stack-sm' },
        h('div', { class: 'row' }, badge(info.access[access], ACCESS_KIND[access]),
          access === 'export' ? h('span', { class: 'muted small' }, t('in der Datenbank suchen und als RIS exportieren, unter Suche & Import importieren')) : null),
        h('div', { class: 'rs-dbs' }, list.map(c => h('div', { key: c.id, class: ['rs-db', chosen.has(c.id) && 'on'] },
          checkbox({ checked: chosen.has(c.id), label: c.label, onChange: v => toggleSource(c.id, v) }),
          h('div', { class: 'rs-db-meta' },
            suggested.includes(c.id) && badge(t('Vorschlag'), 'accent'),
            access === 'live' && !c.in_app && badge(t('noch nicht eingebaut'), 'neutral'),
            c.boolean && c.boolean !== 'ja' && h('span', { class: 'muted small' }, t('Boolesch: {b}', { b: c.boolean })),
            h('span', { class: 'muted small' }, c.disciplines.includes('multi') ? info.disciplines.multi
              : c.disciplines.map(d => info.disciplines[d]).join(', '))),
          h('div', { class: 'muted small' }, c.note, c.terms ? [' ', h('a', { href: c.terms, target: '_blank', rel: 'noopener' }, t('Bedingungen'))] : null),
          keyHint(c)))));
    }),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'rs-link small', onclick: () => { st.all = !st.all; update(); } },
        st.all ? t('Nur passende Datenbanken zeigen') : t('Alle Datenbanken zeigen')))),
  { actions: aiButton });
}
