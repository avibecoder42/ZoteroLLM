// Anleitung: der Arbeitsablauf in vier Schritten, je mit Links in die Ansichten und dem Stand im aktiven Projekt. Das
// Technische steht unter Einstellungen → Einrichtung; wer diese Seite gesehen hat, kommt beim nächsten Start nicht mehr
// dorthin, sondern ins letzte Projekt.
import { h } from '../core/vdom.js';
import { state, update, ui, project, projectCorpora } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { fmtInt, nIndexed, plural } from '../core/util.js';
import { icon } from '../ui/icons.js';
import { btn, badge } from '../ui/components.js';
import { navigate, viewHeader } from './shell.js';
import { newProjectDialog } from './projects.js';

const toSettings = tab => { ui('settings', {}).tab = tab; navigate('settings'); };
const link = (label, go, kind = 'ghost') => btn(label, { size: 'sm', kind, onClick: go });

// Recherchen des aktiven Projekts mit ihrem Stand (neu geholt beim Öffnen der Anleitung, siehe navigate)
function researchOf(p) {
  const g = ui('guide', { for: null, research: null });
  const key = p ? p.id : null;
  if (p && g.for !== key) {
    g.for = key;
    api.get('/api/research/projects').then(r => { g.research = r.projects.filter(x => (x.settings || {}).zotllm_project === p.id); })
      .catch(() => { g.research = []; }).finally(update);
  }
  return p ? g.research : [];
}

function step(n, o) {
  return h('li', { key: n, class: ['setup-step', 'guide-step', o.done && 'done', o.current && 'current', o.optional && 'optional'] },
    h('div', { class: 'setup-mark' }, o.done ? icon('check', 15) : String(n)),
    h('div', { class: 'setup-text' },
      h('div', { class: 'setup-title' }, h('button', { type: 'button', class: 'guide-title', onclick: o.go }, o.title), o.optional ? badge(t('optional'), 'neutral') : null),
      h('div', { class: 'guide-what' }, o.text),
      o.status ? h('div', { class: 'setup-detail' }, o.status) : null,
      o.hint ? h('div', { class: 'setup-detail warn-text' }, o.hint) : null),
    h('div', { class: 'setup-action guide-links' }, o.links));
}

export function guideView() {
  if (state.setup && state.setup.first_run) {
    state.setup.first_run = false;
    api.post('/api/setup/done').catch(() => {});
  }
  const p = project();
  const research = researchOf(p) || [];
  const corpora = p ? projectCorpora() : [];
  const docs = corpora.reduce((a, c) => a + c.stats.documents, 0);
  const indexed = corpora.reduce((a, c) => a + nIndexed(c.stats), 0);
  const chosen = research.reduce((a, r) => a + ((r.summary || {}).included || 0), 0);
  const worked = p ? (p.chats || 0) + (p.reviews || 0) : 0;
  const status = state.status;
  const done = { project: !!p, corpus: corpora.length > 0 && docs > 0 && indexed >= docs, work: worked > 0 };
  const current = !done.project ? 1 : !done.corpus ? 3 : !done.work ? 4 : 0;
  return h('div', { class: 'view-wrap' },
    viewHeader(t('Anleitung'), t('Vom Projekt bis zum fertigen Text')),
    h('div', { class: 'view-body scroll' }, h('div', { class: 'guide-inner stack-lg' },
      h('ol', { class: 'setup-steps' },
        step(1, { title: t('Projekt anlegen'), done: done.project, current: current === 1, go: () => navigate('start'),
          text: t('Ein Projekt bündelt Recherchen, Korpora, Fragen und Forschungsstände zu einem Vorhaben.'),
          status: p ? t('Aktiv: {name}', { name: p.name }) : t('Noch kein Projekt.'),
          links: [link(t('Neues Projekt'), newProjectDialog, p ? 'ghost' : 'primary'), link(t('Zur Projektseite'), () => navigate('start'))] }),
        step(2, { title: t('Recherche'), optional: true, done: chosen > 0, go: () => navigate('research'),
          text: t('Neue Literatur in Fachdatenbanken suchen, sichten und nach Zotero übernehmen. Schon eine Sammlung in Zotero? Weiter bei Schritt 3.'),
          status: !p || research.length === 0 ? t('Noch keine Recherche in diesem Projekt.')
            : `${plural(research.length, t('Recherche'), t('Recherchen'))} · ${t('ausgewählt {n}', { n: fmtInt(chosen) })}`,
          links: [link(t('Zur Recherche'), () => navigate('research'))] }),
        step(3, { title: t('Korpus anlegen und indexieren'), done: done.corpus, current: current === 3, go: () => navigate('corpora'),
          text: t('Die Sammlungen aus Zotero wählen, mit denen du arbeiten willst. Zotivity liest die Texte ein; das läuft im Hintergrund.'),
          status: corpora.length ? `${plural(corpora.length, t('Korpus'), t('Korpora'))} · ${t('{a} von {b} Texten indexiert', { a: fmtInt(indexed), b: fmtInt(docs) })}` : t('Noch kein Korpus in diesem Projekt.'),
          hint: status && !status.zotero.local_api && !done.corpus ? t('Dafür muss Zotero laufen.') : null,
          links: [link(t('Zu den Korpora'), () => navigate('corpora')), link(t('Zum Index'), () => navigate('index'))] }),
        step(4, { title: t('Mit den Korpora arbeiten'), done: done.work, current: current === 4, go: () => navigate('ask'),
          text: t('Fragen an die eigenen Texte stellen oder einen belegten Forschungsstand schreiben.'),
          status: p ? `${plural(p.chats || 0, t('Chat'), t('Chats'))} · ${plural(p.reviews || 0, t('Forschungsstand'), t('Forschungsstände'))}` : null,
          hint: status && !status.llm.key ? t('Dafür fehlt noch ein Sprachmodell.') : null,
          links: [link(t('Fragen'), () => navigate('ask')), link(t('Forschungsstand'), () => navigate('review'))] })),
      h('div', { class: 'guide-more' },
        h('div', { class: 'row wrap' }, icon('search', 15), h('span', { class: 'grow' }, t('Jederzeit: Suchen durchsucht die eigene Bibliothek und alle Gruppen, auch ohne Sprachmodell.')),
          link(t('Suchen'), () => navigate('search'))),
        h('div', { class: 'row wrap' }, icon('settings', 15), h('span', { class: 'grow' }, t('Das Technische (Zotero, Sprachmodell, Embedding, Schlüssel) steht unter Einstellungen.')),
          link(t('Einrichtung'), () => toSettings('setup')))))));
}
