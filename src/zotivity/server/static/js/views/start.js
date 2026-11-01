// Projekte: Projektspalte links (Anlegen und Importieren oben, Kacheln untereinander, darunter das Archiv), rechts
// die Übersicht des aktiven Projekts. Ein Klick auf ein Projekt öffnet es und hebt es hervor – die Reihenfolge bleibt.
// Die Einrichtung (das Technische) steht in setup.js; hier der Arbeitsablauf des Projekts.
import { h } from '../core/vdom.js';
import { state, update, ui, project, projectCorpora, openProject, openProjects, archivedProjects } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, notice, openMenu, paneProps, splitter } from '../ui/components.js';
import { navigate } from './shell.js';
import { rs, openProject as openResearch, summaryLine } from './research/common.js';
import { fmtAgo, fmtInt, plural, nIndexed } from '../core/util.js';
import { projectBadge, projectColor, newProjectDialog, importProject, editProjectDialog, exportProject, projectMenuItems,
  archivedMenuItems, archiveProject, moveProject } from './projects.js';

// ------------------------------------------------------------------ Projektspalte
function tileCounts(p) {
  return [plural(p.corpus_ids.length, t('Korpus'), t('Korpora')), plural(p.chats, t('Chat'), t('Chats')),
    plural(p.reviews, t('Forschungsstand'), t('Forschungsstände'))].join(' · ');
}

function menuAt(e, items) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4, items);
}

// Anordnen durch Ziehen (Zeigerereignisse statt HTML-Drag&Drop – verlässlich im Programmfenster): ab 6 px Bewegung
// wird gezogen; eine Linie über bzw. unter der Zielkachel zeigt, wohin das Projekt kommt. Am Rand der Liste scrollt sie.
const drag = { id: null, over: null, after: false };
let suppressClick = false;

function startReorder(e, p) {
  if (e.button !== 0 || (e.target.closest && e.target.closest('button'))) return;
  const startY = e.clientY;
  let active = false;
  const move = ev => {
    if (!active) {
      if (Math.abs(ev.clientY - startY) < 6) return;
      active = true;
      drag.id = p.id;
      document.body.classList.add('reordering');
    }
    const list = document.querySelector('.project-list');
    if (list) {
      const lr = list.getBoundingClientRect();
      if (ev.clientY < lr.top + 28) list.scrollTop -= 14;
      else if (ev.clientY > lr.bottom - 28) list.scrollTop += 14;
    }
    const tile = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.project-tile[data-pid]');
    let over = null, after = false;
    if (tile && Number(tile.dataset.pid) !== p.id) {
      const r = tile.getBoundingClientRect();
      over = Number(tile.dataset.pid);
      after = ev.clientY > r.top + r.height / 2;
    }
    if (over !== drag.over || after !== drag.after) { drag.over = over; drag.after = after; update(); }
  };
  const end = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', end);
    window.removeEventListener('pointercancel', end);
    if (!active) return;
    document.body.classList.remove('reordering');
    const { over, after } = drag;
    drag.id = null; drag.over = null;
    suppressClick = true;  // der Klick nach dem Loslassen öffnet kein Projekt
    setTimeout(() => { suppressClick = false; }, 0);
    if (over != null) moveProject(p.id, over, after); else update();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', end);
  window.addEventListener('pointercancel', end);
}

function projectTile(p) {
  const active = p.id === state.projectId;
  const dropping = drag.over === p.id && drag.id !== p.id;
  return h('div', { key: p.id, class: ['project-tile', active && 'active', drag.id === p.id && 'dragging', dropping && (drag.after ? 'drop-after' : 'drop-before')],
    role: 'button', tabindex: 0, 'aria-current': active ? 'true' : null, 'data-pid': p.id,
    style: { '--pc': projectColor(p) }, title: `${p.name}${p.description ? `\n${p.description}` : ''}\n${t('Ziehen, um die Reihenfolge zu ändern')}`,
    onpointerdown: e => startReorder(e, p),
    onclick: () => { if (!active && !suppressClick) openProject(p.id); },
    onkeydown: e => { if (e.key === 'Enter' && !active) openProject(p.id); } },
  projectBadge(p, 34),
  h('div', { class: 'project-tile-text' },
    h('div', { class: 'project-tile-name' }, p.name),
    h('div', { class: 'project-tile-meta' }, tileCounts(p)),
    h('div', { class: 'project-tile-date' }, fmtAgo(p.activity_at))),
  iconBtn('more', t('Projekt-Aktionen'), e => { e.stopPropagation(); menuAt(e, projectMenuItems(p)); }));
}

// Archivierte Projekte: blass, nicht zu öffnen; ein Klick zeigt die Aktionen (zurückholen, exportieren, löschen)
function archivedTile(p) {
  return h('div', { key: `a${p.id}`, class: 'project-tile archived', role: 'button', tabindex: 0,
    style: { '--pc': projectColor(p) }, title: t('{name} – archiviert. Klicken für Aktionen.', { name: p.name }),
    onclick: e => menuAt(e, archivedMenuItems(p)),
    onkeydown: e => { if (e.key === 'Enter') menuAt(e, archivedMenuItems(p)); } },
  projectBadge(p, 28),
  h('div', { class: 'project-tile-text' },
    h('div', { class: 'project-tile-name' }, p.name),
    h('div', { class: 'project-tile-meta' }, tileCounts(p)),
    h('div', { class: 'project-tile-date' }, t('archiviert {ago}', { ago: fmtAgo(p.archived_at) }))),
  iconBtn('unarchive', t('Aus dem Archiv holen'), e => { e.stopPropagation(); archiveProject(p, false); }));
}

function projectColumn() {
  const nav = ui('projectsNav', { archiveOpen: false });
  const open = openProjects();
  const archived = archivedProjects();
  return h('aside', { class: 'project-column', ...paneProps('start', 290) },
    h('div', { class: 'project-column-head' },
      h('div', { class: 'eyebrow' }, t('Projekte')),
      h('span', { class: 'muted small' }, fmtInt(open.length))),
    h('div', { class: 'project-column-actions' },
      btn(t('Neues Projekt'), { kind: 'secondary', icon: 'plus', onClick: newProjectDialog }),
      btn(t('Importieren'), { kind: 'ghost', icon: 'download', title: t('Projekt aus einer .zoty-Datei laden'), onClick: importProject })),
    // scrollt bei vielen Projekten für sich; Kopf und Knöpfe bleiben stehen
    h('div', { class: 'project-list' },
      open.map(projectTile),
      archived.length ? h('button', { key: 'archive', type: 'button', class: 'archive-toggle', 'aria-expanded': nav.archiveOpen ? 'true' : 'false',
        title: nav.archiveOpen ? t('Archiv zuklappen') : t('Archivierte Projekte zeigen'),
        onclick: () => { nav.archiveOpen = !nav.archiveOpen; update(); } },
      icon(nav.archiveOpen ? 'chevronDown' : 'chevronRight', 14), icon('archive', 15), h('span', { class: 'grow' }, t('Archiv')),
      h('span', { class: 'muted small' }, fmtInt(archived.length))) : null,
      archived.length && nav.archiveOpen ? archived.map(archivedTile) : null),
    h('p', { class: 'muted small project-column-hint' }, t('Ein Projekt bündelt Korpora, Chats und Forschungsstände. Alles wird laufend gespeichert. Die Reihenfolge lässt sich durch Ziehen ändern.')),
    splitter('start', { def: 290, min: 220, max: 520 }));
}

// ------------------------------------------------------------------ Übersicht des aktiven Projekts
function actionCard(ic, title, text, onClick, primary = false) {
  return h('button', { type: 'button', class: ['start-card', primary && 'primary'], onclick: onClick },
    h('div', { class: 'start-card-icon' }, icon(ic, 22)),
    h('div', { class: 'start-card-title' }, title),
    h('div', { class: 'start-card-text' }, text));
}

function corporaOverview() {
  const corpora = projectCorpora();
  if (!corpora.length) {
    return notice('info', t('Diesem Projekt ist noch kein Wissenskorpus zugeordnet – Fragen und Forschungsstand finden sonst nichts.'),
      h('div', { class: 'notice-actions' }, btn(t('Korpus anlegen oder hinzufügen'), { size: 'sm', kind: 'primary', icon: 'plus', onClick: () => navigate('corpora') })));
  }
  return h('div', { class: 'recent-list' }, corpora.map(c => {
    const x = c.stats;
    const pct = x.documents ? Math.round(100 * nIndexed(x) / x.documents) : 0;
    return h('button', { key: c.id, type: 'button', class: 'recent-item corpus-row', onclick: () => { ui('corporaNav', {}).open = c.id; navigate('corpora'); } },
      icon('corpus', 16), h('span', { class: 'recent-name' }, c.name),
      h('span', { class: 'mini-progress inline', title: t('{p} % indexiert', { p: pct }) }, h('i', { style: { width: pct + '%' } })),
      h('span', { class: ['recent-date', x.to_embed && 'warn-text'], title: x.to_embed === 1 ? t('1 Text ist gelesen, aber für das aktive Embedding-Modell noch nicht eingebettet.')
        : x.to_embed ? t('{n} Texte sind gelesen, aber für das aktive Embedding-Modell noch nicht eingebettet.', { n: fmtInt(x.to_embed) }) : null },
        x.to_embed ? t('{a}/{b} Texte · {e} einzubetten', { a: fmtInt(nIndexed(x)), b: fmtInt(x.documents), e: fmtInt(x.to_embed) })
          : t('{a}/{b} Texte', { a: fmtInt(nIndexed(x)), b: fmtInt(x.documents) })));
  }));
}

function recentList(items, ic, empty, onOpen) {
  if (!items || !items.length) return h('p', { class: 'muted' }, empty);
  return h('div', { class: 'recent-list' }, items.map(x => h('button', { key: x.id, type: 'button', class: 'recent-item', title: x.title, onclick: () => onOpen(x) },
    icon(ic, 16), h('span', { class: 'recent-name' }, x.title), h('span', { class: 'recent-date' }, fmtAgo(x.updated_at)))));
}

// Recherchen des Projekts (Modul „Recherche“) mit Stand des Screenings
function researchList(items) {
  if (!items || !items.length) return h('p', { class: 'muted' }, t('Noch keine Recherche in diesem Projekt.'));
  return h('div', { class: 'recent-list' }, items.map(x => h('button', { key: x.id, type: 'button', class: 'recent-item', title: summaryLine(x.summary),
    onclick: () => { rs().projects = null; openResearch(x.id); navigate('research'); } },
  icon('litsearch', 16), h('span', { class: 'recent-name' }, x.title),
  h('span', { class: 'recent-date' }, t('gesichtet {a}/{b}', { a: fmtInt(x.summary.screened || 0), b: fmtInt(x.summary.visible || 0) })))));
}

// Unverbindlicher nächster Schritt; den ganzen Ablauf zeigt die Anleitung
function nextStep(st) {
  const corpora = projectCorpora();
  const research = st.research || [];
  const status = state.status;
  let text;
  let action = null;
  const open = corpora.reduce((a, c) => a + (c.stats.documents - nIndexed(c.stats)), 0);
  if (!corpora.length && !research.length) {
    text = t('Neues Vorhaben: neue Literatur in Fachdatenbanken suchen oder eine vorhandene Sammlung aus Zotero als Korpus aufnehmen.');
    action = [btn(t('Zur Recherche'), { size: 'sm', onClick: () => navigate('research') }), btn(t('Zu den Korpora'), { size: 'sm', onClick: () => navigate('corpora') })];
  } else if (!corpora.length) {
    const chosen = research.reduce((a, r) => a + ((r.summary || {}).included || 0), 0);
    text = chosen ? t('Die Recherche hat {n} Texte ausgewählt. Nach der Übergabe an Zotero lässt sich ihre Sammlung als Wissenskorpus aufnehmen.', { n: fmtInt(chosen) })
      : t('Die Recherche läuft. Sobald Texte in Zotero liegen, lassen sie sich als Wissenskorpus aufnehmen.');
    action = chosen ? btn(t('Zu den Korpora'), { size: 'sm', onClick: () => navigate('corpora') }) : btn(t('Zur Recherche'), { size: 'sm', onClick: () => navigate('research') });
  } else if (open > 0) {
    text = status && !status.zotero.local_api ? t('{n} Texte warten aufs Indexieren. Dafür muss Zotero laufen.', { n: fmtInt(open) }) : t('{n} Texte warten aufs Indexieren.', { n: fmtInt(open) });
    action = btn(t('Zum Index'), { size: 'sm', onClick: () => navigate('index') });
  } else if (status && !status.llm.key) {
    text = t('Die Texte sind durchsuchbar. Für Fragen und Forschungsstand fehlt noch ein Sprachmodell.');
    action = btn(t('Sprachmodell einrichten'), { size: 'sm', onClick: () => { ui('settings', {}).tab = 'models'; navigate('settings'); } });
  } else {
    text = t('Die Texte sind bereit: Stelle eine Frage oder beginne einen Forschungsstand.');
  }
  return h('div', { class: 'next-step' }, icon('arrowRight', 16), h('b', null, t('Nächster Schritt')), h('span', { class: 'grow' }, text), action,
    h('button', { type: 'button', class: 'rs-link small', onclick: () => navigate('guide') }, t('Anleitung')));
}

function projectOverview(st) {
  const p = project();
  if (!p) return null;
  const ready = state.setup && state.setup.ready && projectCorpora().length > 0;
  return h('div', { class: 'stack-lg' },
    h('div', { class: 'project-hero', style: { '--pc': projectColor(p) } }, projectBadge(p, 52),
      h('div', { class: 'grow' }, h('div', { class: 'eyebrow' }, t('Aktives Projekt')), h('h1', null, p.name),
        p.description ? h('p', null, p.description) : h('p', { class: 'muted' }, t('Ohne Beschreibung'))),
      h('div', { class: 'row' },
        btn(t('Bearbeiten'), { size: 'sm', kind: 'ghost', icon: 'edit', onClick: () => editProjectDialog(p) }),
        btn(t('Als Datei speichern'), { size: 'sm', kind: 'ghost', icon: 'download', title: t('Projekt als .zoty-Datei exportieren (Sicherung, anderer Rechner)'), onClick: () => exportProject(p) }),
        btn(t('Archivieren'), { size: 'sm', kind: 'ghost', icon: 'archive', title: t('Projekt ins Archiv verschieben – es lässt sich jederzeit zurückholen'), onClick: () => archiveProject(p) }))),
    st.research ? nextStep(st) : null,
    h('div', { class: 'start-cards' },
      actionCard('litsearch', t('Recherche'), t('Neue Literatur in Fachdatenbanken suchen, sichten und nach Zotero übernehmen.'), () => navigate('research')),
      actionCard('corpus', t('Wissenskorpora'), t('Sammlungen aus Zotero für dieses Projekt bündeln.'), () => navigate('corpora')),
      actionCard('chat', t('Frage stellen'), t('Antworten aus den Korpora dieses Projekts, jede Aussage mit Quelle.'), () => navigate('ask'), ready),
      actionCard('review', t('Forschungsstand'), t('Suchstrategie, Texte auswerten, Synthese schreiben und prüfen.'), () => navigate('review')),
      actionCard('search', t('Suchen'), t('Bibliothek und Gruppen durchsuchen – ohne Sprachmodell.'), () => navigate('search'))),
    h('div', { class: 'start-columns' },
      h('section', { class: 'start-section' }, h('h2', null, t('Recherchen')), researchList(st.research)),
      h('section', { class: 'start-section' }, h('h2', null, t('Korpora des Projekts')), corporaOverview()),
      h('section', { class: 'start-section' }, h('h2', null, t('Letzte Fragen')),
        recentList(st.chats, 'chat', t('Noch keine Fragen in diesem Projekt.'), c => { ui('ask').openChat = c.id; navigate('ask'); })),
      h('section', { class: 'start-section' }, h('h2', null, t('Forschungsstände')),
        recentList(st.reviews, 'review', t('Noch kein Forschungsstand in diesem Projekt.'), r => { ui('review').openId = r.id; navigate('review'); }))));
}

export function startView() {
  const st = ui('start', { chats: null, reviews: null, loading: false, forSig: null });
  // Neu laden, sobald sich Chats oder Forschungsstände des Projekts ändern (Anzahl oder letzte Aktivität) –
  // sonst fehlte eine eben gestellte Frage, bis man das Projekt wechselte
  const p = project();
  const sig = p ? `${p.id}:${p.chats}:${p.reviews}:${p.activity_at}` : null;
  if (sig && st.forSig !== sig && !st.loading) {
    st.loading = true;
    const pid = p.id;
    Promise.all([api.get(`/api/chats?project=${pid}`), api.get(`/api/reviews?project=${pid}`),
      api.get('/api/research/projects').catch(() => ({ projects: [] }))]).then(([c, r, rp]) => {
      st.chats = c.chats.slice(0, 6); st.reviews = r.reviews.slice(0, 6);
      st.research = rp.projects.filter(x => (x.settings || {}).zotllm_project === pid);
      st.forSig = sig; st.loading = false; update();
    }).catch(() => { st.loading = false; });
  }
  return h('div', { class: 'start' },
    projectColumn(),
    h('div', { class: 'start-main' }, h('div', { class: 'start-inner' }, projectOverview(st))));
}
