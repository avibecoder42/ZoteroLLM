// Einrichtung: das Technische, einmal je Computer (Zotero, Sprachmodell, Embedding, auf Wunsch Schreibzugriff, Plugin,
// Schlüssel für Datenbanken). Steht unter Einstellungen → Einrichtung; dorthin führt der erste Start. Den Arbeitsablauf
// zeigt die Anleitung (guide.js); wenn später etwas fehlt, meldet das die Statusleiste oder die Stelle, die es braucht.
import { h } from '../core/vdom.js';
import { state, openModal, closeModal, loadSetup, loadStatus, ui } from '../core/store.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, notice, spinner } from '../ui/components.js';
import { navigate } from './shell.js';
import { authorizeZotero, savePlugin } from './settings.js';

const STEP_ICONS = { zotero: 'zotero', llm: 'ai', embedding: 'index', write: 'edit', plugin: 'plug', databases: 'key' };
// Wofür es den Schritt braucht – fehlt er, geht das Übrige trotzdem
const STEP_WHY = {
  zotero: () => t('Für Korpora, Indexieren und die Übergabe aus der Recherche. Die Suche in Fachdatenbanken geht auch ohne.'),
  llm: () => t('Für Fragen, Forschungsstand und KI-Vorschläge. Suchen und Recherche gehen auch ohne.'),
  embedding: () => t('Für die Bedeutungssuche in den Korpora.'),
};

export function zoteroHelp() {
  openModal({
    title: t('Zotero mit Zotivity verbinden'),
    body: () => h('div', { class: 'stack' },
      h('p', null, t('Zotivity liest deine Bibliothek über die lokale Schnittstelle von Zotero. Sie ist anfangs ausgeschaltet:')),
      h('ol', { class: 'steps-list' },
        h('li', null, t('Zotero öffnen.')),
        h('li', null, h('b', null, t('Bearbeiten → Einstellungen')), ' ', t('(macOS: Zotero → Einstellungen) wählen.')),
        h('li', null, t('Bereich „Erweitert“ öffnen.')),
        h('li', null, t('Häkchen bei „Anderen Anwendungen auf diesem Computer erlauben, mit Zotero zu kommunizieren“ setzen.'))),
      notice('info', t('Zotero muss geöffnet sein, solange Zotivity abgleicht oder indexiert. Fragen funktionieren auch ohne Zotero.'))),
    actions: [{ label: t('Erneut prüfen'), kind: 'primary', icon: 'refresh', onClick: async () => { closeModal(); await loadStatus(); await loadSetup(); } }],
  });
}

function toSettings(tab) {
  ui('settings', {}).tab = tab;
  navigate('settings');
}

function stepAction(step) {
  switch (step.id) {
    case 'zotero': return step.done ? null : btn(t('Anleitung'), { size: 'sm', icon: 'help', onClick: zoteroHelp });
    case 'llm': return btn(t('Anbieter wählen'), { size: 'sm', kind: step.done ? 'ghost' : 'primary', onClick: () => toSettings('models') });
    case 'embedding': return btn(t('Embedding-Modell'), { size: 'sm', kind: step.done ? 'ghost' : 'primary', onClick: () => toSettings('embedding') });
    case 'write': return step.done ? null : btn(t('Freigeben'), { size: 'sm', onClick: authorizeZotero });
    case 'plugin': return step.done ? null : btn(t('Plugin speichern'), { size: 'sm', icon: 'download', onClick: savePlugin });
    case 'databases': return btn(t('Schlüssel'), { size: 'sm', kind: 'ghost', onClick: () => toSettings('databases') });
    default: return null;
  }
}

export function setupCard() {
  const s = state.setup;
  if (!s) return h('div', { class: 'card' }, spinner(16));
  const steps = s.steps.filter(x => x.group === 'technical');
  const required = steps.filter(x => !x.optional);
  const done = required.filter(x => x.done).length;
  let firstOpen = true;
  return h('section', { class: 'card setup-card' },
    h('div', { class: 'card-head' },
      h('h3', null, icon('check', 16), s.ready ? t('Alles eingerichtet') : t('Einrichtung')),
      h('span', { class: 'muted small' }, t('{a} von {b} erledigt', { a: done, b: required.length })),
      h('div', { class: 'card-actions' }, iconBtn('refresh', t('Neu prüfen'), () => { loadStatus(); loadSetup(); }))),
    h('div', { class: 'setup-progress' }, h('div', { style: { width: `${Math.round(100 * done / required.length)}%` } })),
    h('ol', { class: 'setup-steps' }, steps.map(step => {
      const current = !step.done && !step.optional && firstOpen;
      if (current) firstOpen = false;
      return h('li', { key: step.id, class: ['setup-step', step.done && 'done', current && 'current', step.optional && 'optional'] },
        h('div', { class: 'setup-mark' }, step.done ? icon('check', 15) : icon(STEP_ICONS[step.id], 15)),
        h('div', { class: 'setup-text' },
          h('div', { class: 'setup-title' }, step.title, step.optional && h('span', { class: 'badge badge-neutral' }, t('optional'))),
          h('div', { class: 'setup-detail' }, step.detail),
          !step.done && STEP_WHY[step.id] ? h('div', { class: 'setup-detail' }, STEP_WHY[step.id]()) : null),
        h('div', { class: 'setup-action' }, stepAction(step)));
    })));
}
