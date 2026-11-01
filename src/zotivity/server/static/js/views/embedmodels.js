// Eingebaute Embedding-Modelle (llama.cpp): Katalog als Tabelle mit Stärken, Zeit pro 100 Seiten und Speicherbedarf,
// Download per Knopf (mit Fortschritt, Abbrechen, Fortsetzen), Kurztest, Löschen, Namenssuche auf Hugging Face,
// Übernahme eines bestehenden Index (z. B. aus Ollama) und Vergleich zweier Modelle mit derselben Frage.
import { h } from '../core/vdom.js';
import { state, update, ui, toast, run, openModal, closeModal, confirmDialog, saveSettings, loadSettings, loadStatus, loadSetup,
  watchJob, project, providerLabel, runningJob, submitIndexRun, setEmbeddingChangeHandler, resetEmbeddingViews } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { icon } from '../ui/icons.js';
import { btn, iconBtn, card, foldCard, notice, spinner, progress, field, textInput, textArea, select, segmented, numberInput, badge, openMenu } from '../ui/components.js';
import { fmtInt, fmtNum, fmtBytes, fmtDate, fmtDuration, nTexts, nIndexed, embedHint } from '../core/util.js';

const ms = () => ui('embmodels', { data: null, loading: false, error: null, open: {}, jobOf: {}, q: '', searching: false, results: null,
  searchError: null, adopt: null, spaces: null, cmp: { query: '', a: '', b: '', scope: 'project', busy: false, result: null } });
const watched = new Set();

export async function loadLocalModels(force = false) {
  const s = ms();
  if (s.loading || (s.data && !force)) return s.data;
  s.loading = true;
  try {
    s.data = await api.get('/api/embedding/local');
    s.error = null;
    for (const m of s.data.models) if (m.job && !watched.has(m.job.id)) watchModelJob(m.job, m.name);
  } catch (err) { s.error = err.message; }
  s.loading = false;
  update();
  return s.data;
}

function refreshAll() {
  const s = ms();
  s.spaces = null; s.adopt = null;
  ui('settings').spaces = null;
  loadLocalModels(true); loadStatus(); loadSetup();
}

// ------------------------------------------------------------------ Aufträge (Download, Kurztest, Übernahme)
function watchModelJob(job, name) {
  if (watched.has(job.id)) return;
  watched.add(job.id);
  state.jobs[job.id] = job;
  watchJob(job.id, () => update()).then(done => {
    watched.delete(job.id);
    const test = done.counters && done.counters.test;
    if (done.status === 'done' && done.kind === 'model-download') {
      toast(test ? t('{m} ist bereit. Kurztest: {a} von {b} Testfragen richtig, ≈ {min} pro 100 Seiten.', { m: name, a: test.top1, b: test.queries, min: fmtMinutes(test.minutes_per_100_pages) })
        : t('{m} ist heruntergeladen.', { m: name }), 'success', 9000);
      // Das aktive Modell war bisher nicht verfügbar: jetzt erklären, was mit den Texten zu tun ist
      const e = state.settings && state.settings.embedding;
      if (e && e.provider === 'builtin' && done.counters && e.model === done.counters.model) {
        setTimeout(() => afterEmbeddingSwitch({ provider: '', model: '' }, e), 1500);
      }
    } else if (done.status === 'done' && done.kind === 'model-test' && test) {
      toast(t('Kurztest {m}: {a} von {b} Testfragen richtig, {tps} Tokens/s (≈ {min} pro 100 Seiten).', { m: name, a: test.top1, b: test.queries, tps: fmtInt(test.tok_per_s), min: fmtMinutes(test.minutes_per_100_pages) }),
        test.ok ? 'success' : 'warning', 9000);
    } else if (done.status === 'error') {
      toast(done.error, 'error', 12000);
    } else if (done.status === 'cancelled' && done.kind === 'model-download') {
      toast(t('Download angehalten – „Fortsetzen“ lädt den Rest.'), 'info', 6000);
    }
    refreshAll();
  });
}

async function startDownload(m) {
  const d = ms().data;
  if (d && d.disk && d.disk.free_bytes < m.bytes - m.partial_bytes + 2e8) {
    toast(t('Zu wenig Speicherplatz: {m} braucht {a}, frei sind {b}.', { m: m.name, a: fmtBytes(m.bytes), b: fmtBytes(d.disk.free_bytes) }), 'error', 9000);
    return;
  }
  const job = await run(() => api.post(`/api/embedding/local/${m.id}/download`));
  ms().jobOf[m.id] = job.id;
  watchModelJob(job, m.name);
  update();
}

async function startTest(m) {
  const job = await run(() => api.post(`/api/embedding/local/${m.id}/test`));
  ms().jobOf[m.id] = job.id;
  watchModelJob(job, m.name);
  update();
}

async function useModel(m, dims = null) {
  await run(() => api.post(`/api/embedding/local/${m.id}/use`, { dimensions: dims }));
  await loadSettings();  // meldet den Wechsel (Dialog: übernehmen bzw. einbetten)
  refreshAll();
}

// ------------------------------------------------------------------ Nach einem Wechsel des Embedding-Modells
const modelLabel = e => {
  if (!e) return '';
  const d = ms().data;
  const m = e.provider === 'builtin' && d && d.models.find(x => x.id === e.model);
  return m ? m.name : e.model;
};

// Texte, die schon gelesen sind, für das aktive Modell einbetten – nur einbetten: kein Abgleich, nichts wird neu gelesen
// Läuft schon eine Indexierung, wartet das Einbetten in der Warteschlange (Hinweis kommt aus store.js)
export async function startEmbedding(corpusId = null) {
  const job = await submitIndexRun('/api/index/run', { sync: false, embed_only: true, ...(corpusId ? { corpus_id: corpusId } : {}) });
  if (!job) return;
  toast(t('Einbetten läuft – den Fortschritt zeigt die Ansicht Index.'), 'info', 5000, { label: t('Anzeigen'), onClick: () => { state.view = 'index'; update(); } });
}

const fmtEta = s => (s == null ? null : s < 60 ? t('< 1 min') : fmtDuration(s));

// Je Index (Embedding-Raum) nur einmal erklären: Meldet sich derselbe Wechsel ein zweites Mal (nach einem Download,
// aus einem zweiten Fenster …), erscheint der Dialog nicht erneut. Die Hinweise in Index und Fragen bleiben.
const EXPLAINED_KEY = 'zllm.embExplained';
let explained = null;
function wasExplained(space) {
  let v = explained;
  try { v = localStorage.getItem(EXPLAINED_KEY) ?? v; } catch { /* privat */ }
  return !!space && v === space;
}
function markExplained(space) {
  explained = space || null;
  try { localStorage.setItem(EXPLAINED_KEY, space || ''); } catch { /* privat */ }
}

const sameEmbedding = (a, b) => !!a && !!b && ['provider', 'model', 'dimensions', 'query_prefix', 'document_prefix'].every(k => a[k] === b[k]);

let explaining = false;  // zwei gleichzeitige Meldungen (Einstellung + Präfixe) ergeben nur einen Dialog

async function afterEmbeddingSwitch(prev, next, { force = false, prevLabel = null } = {}) {
  if ((!force && sameEmbedding(prev, next)) || explaining) return;
  explaining = true;
  try {
    let o;
    try { o = await api.get('/api/index/overview'); } catch { return; }
    if (!o.model || !o.model.ok) return;  // Modell nicht bereit (z. B. nicht heruntergeladen): das zeigt die Einstellung selbst
    if (wasExplained(o.model.space)) return;
    markExplained(o.model.space);
    let adopt = [];
    try { adopt = (await api.get('/api/embedding/adopt')).candidates; } catch { /* ohne Übernahme */ }
    if (adopt.length) { offerAdopt(adopt[0], o.model.label || modelLabel(next)); return; }
    explainCoverage(o, prevLabel ?? (prev && prev.model ? modelLabel(prev) : ''));
  } finally {
    explaining = false;
  }
}
setEmbeddingChangeHandler(afterEmbeddingSwitch);

// Was fehlt dem aktiven Modell noch? Nach einem Wechsel oder einer Übernahme (adopted: Ergebnis der Übernahme)
function explainCoverage(o, prevLabel, adopted = null) {
  const label = (o.model && o.model.label) || '';
  const x = o.stats;
  if (!x || !x.to_embed) {
    toast(adopted ? t('Index übernommen: {n} Abschnitte (Übereinstimmung {c}).', { n: fmtInt(adopted.moved), c: fmtNum(adopted.cos_mean, 3) })
      : x && nIndexed(x) ? t('{m} ist aktiv – alle gelesenen Texte sind damit bereits durchsuchbar.', { m: label })
        : t('{m} ist jetzt das Embedding-Modell.', { m: label }), 'success', adopted ? 9000 : 6000);
    return;
  }
  const eta = fmtEta(o.embed_estimate);
  const what = { m: label, t: nTexts(x.to_embed), c: fmtInt(x.to_embed_chunks), eta: eta ? ` – ${t('etwa {d}', { d: eta })}` : '' };
  openModal({
    title: adopted ? t('Index übernommen') : t('Neues Embedding-Modell: {m}', { m: label }),
    body: () => h('div', { class: 'stack' },
      adopted && h('p', null, t('{n} Abschnitte wurden übernommen (Übereinstimmung {c}).', { n: fmtInt(adopted.moved), c: fmtNum(adopted.cos_mean, 3) })),
      h('p', null, adopted
        ? t('Noch nicht im Index von {m}: {t} ({c} Abschnitte){eta}. Sie wurden mit einem anderen Modell indexiert und müssen für {m} eingebettet werden.', what)
        : t('Die Texte sind schon gelesen, müssen aber für {m} eingebettet werden: {t} ({c} Abschnitte){eta}.', what)),
      h('p', { class: 'muted small' }, embedHint(), ' ', t('Bis dahin findet die Bedeutungssuche diese Texte nicht (die Stichwortsuche schon).'),
        prevLabel ? ' ' + t('Der Index von {p} bleibt erhalten; ein Zurückwechseln geht sofort.', { p: prevLabel }) : '')),
    actions: [{ label: t('Später'), onClick: closeModal },
      { label: t('Jetzt einbetten'), kind: 'primary', icon: 'play', onClick: () => { closeModal(); startEmbedding(); } }],
  });
}

// Hinweis für Fragen und Forschungsstand: deckt das aktive Modell die Korpora nur teilweise ab?
export function coverageNotice(corpora) {
  const s = ms();
  const sum = k => corpora.reduce((a, c) => a + ((c.stats && c.stats[k]) || 0), 0);
  const toEmbed = sum('to_embed');
  if (!toEmbed) return null;
  const indexed = sum('indexed') + sum('refresh');  // wie nIndexed: Texte, die auf erneutes Lesen warten, sind durchsuchbar
  const label = (state.status && state.status.embedding && state.status.embedding.label) || modelLabel(state.settings && state.settings.embedding);
  if (s.spaces === null) { s.spaces = false; api.get('/api/embedding/spaces').then(r => { s.spaces = r; update(); }).catch(() => {}); }
  // Zurück zum Modell mit dem grössten anderen Index
  const other = s.spaces ? s.spaces.spaces.filter(x => x.space !== s.spaces.active && x.n > 0).sort((a, b) => b.n - a.n)[0] : null;
  const text = indexed + toEmbed === 1
    ? t('Mit {m} ist der Text noch nicht durchsuchbar – die Bedeutungssuche findet ihn noch nicht (die Stichwortsuche schon).', { m: label })
    : !indexed ? t('Mit {m} ist noch keiner der {b} Texte durchsuchbar – die Bedeutungssuche findet sie noch nicht (die Stichwortsuche schon).', { m: label, b: fmtInt(toEmbed) })
    : t('Mit {m} sind erst {a} von {b} Texten durchsuchbar – die Bedeutungssuche findet den Rest noch nicht (die Stichwortsuche schon).',
      { m: label, a: fmtInt(indexed), b: fmtInt(indexed + toEmbed) });
  // Ausblendbar; erscheint wieder bei einem anderen Modell oder wenn neue Texte dazukommen
  return notice('warning', h('span', { title: embedHint() }, text),
  h('div', { class: 'notice-actions' },
    btn(t('Jetzt einbetten'), { size: 'sm', kind: 'primary', icon: 'play', onClick: () => startEmbedding() }),
    other && btn(t('Zurück zu {m}', { m: other.label || other.model }), { size: 'sm', onClick: () => activateSpace(other.space) })),
  { dismiss: `coverage:${label}:${indexed + toEmbed}` });
}

export async function activateSpace(space) {
  await run(() => api.post('/api/embedding/spaces/activate', { space }));
  await loadSettings();  // meldet den Wechsel
}

function offerAdopt(c, name) {
  openModal({
    title: t('Bestehenden Index übernehmen?'),
    body: () => h('div', { class: 'stack' },
      h('p', null, t('Für {m} gibt es bereits einen Index aus {p} mit {n} Abschnitten.', { m: name, p: providerLabel(c.provider), n: fmtInt(c.vectors) })),
      h('p', null, t('Zotivity bettet zuerst 24 Stichproben neu ein und vergleicht sie mit dem bestehenden Index. Stimmen die Vektoren überein, wird er übernommen – das spart das Neu-Einbetten der ganzen Bibliothek. Sonst bettet die nächste Indexierung alle Texte neu ein.'))),
    actions: [{ label: t('Neu einbetten'), onClick: closeModal },
      { label: t('Prüfen und übernehmen'), kind: 'primary', onClick: () => { closeModal(); adoptIndex(c.space); } }],
  });
}

async function adoptIndex(space) {
  const job = await run(() => api.post('/api/embedding/adopt', { space }));
  state.jobs[job.id] = job;
  toast(t('Index wird geprüft …'), 'info', 3000);
  const done = await watchJob(job.id);
  const r = done.counters && done.counters.result;
  if (done.status === 'done' && r && r.adopted) {
    // Gleich sagen, was der übernommene Index nicht enthält (z. B. Texte, die mit einem anderen Modell indexiert wurden)
    let o = null;
    try { o = await api.get('/api/index/overview'); } catch { /* dann nur die Meldung */ }
    if (o && o.model) markExplained(o.model.space);
    if (o && o.model && o.model.ok) explainCoverage(o, '', r);
    else toast(t('Index übernommen: {n} Abschnitte (Übereinstimmung {c}).', { n: fmtInt(r.moved), c: fmtNum(r.cos_mean, 3) }), 'success', 9000);
  } else if (done.status === 'done' && r) {
    toast(t('Die Vektoren stimmen nicht genug überein (Übereinstimmung {c}). Die nächste Indexierung bettet die Texte neu ein.', { c: r.cos_mean != null ? fmtNum(r.cos_mean, 3) : '–' }), 'warning', 12000);
  } else if (done.status === 'error') {
    toast(done.error, 'error', 12000);
  }
  refreshAll();
}

async function deleteModel(m) {
  const vectors = m.index && m.index.vectors;
  if (!await confirmDialog(t('{m} löschen?', { m: m.name }),
    t('Die Modelldatei ({s}) wird gelöscht. Ein Index dieses Modells bleibt erhalten, bis du ihn unter „Gespeicherte Indizes“ löschst – nach erneutem Herunterladen ist er sofort wieder nutzbar.', { s: fmtBytes(m.bytes) })
    + (vectors ? ' ' + t('({n} Abschnitte eingebettet)', { n: fmtInt(vectors) }) : ''), { ok: t('Löschen'), danger: true })) return;
  await run(() => api.del(`/api/embedding/local/${m.id}`));
  refreshAll();
}

function modelMenu(e, m) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.right - 260, r.bottom + 4, [
    m.installed && { label: t('Kurztest'), icon: 'play', onClick: () => startTest(m) },
    m.model_url && { label: t('Modellbeschreibung öffnen'), icon: 'external', onClick: () => api.openExternal(m.model_url) },
    { label: t('Datei auf Hugging Face'), icon: 'external', onClick: () => api.openExternal(`https://huggingface.co/${m.repo}/tree/${m.revision}`) },
    m.partial_bytes > 0 && { label: t('Angefangenen Download verwerfen'), icon: 'x', onClick: async () => { await run(() => api.del(`/api/embedding/local/${m.id}/partial`)); refreshAll(); } },
    m.installed && !m.active && '-',
    m.installed && !m.active && { label: t('Modelldatei löschen'), icon: 'trash', danger: true, onClick: () => deleteModel(m) },
    m.user && !m.active && { label: t('Aus der Liste entfernen'), icon: 'trash', danger: true, onClick: async () => {
      if (!await confirmDialog(t('{m} entfernen?', { m: m.name }), t('Das eigene Modell wird aus der Liste entfernt und seine Datei gelöscht.'), { ok: t('Entfernen'), danger: true })) return;
      await run(() => api.del(`/api/embedding/user/${m.id}`)); refreshAll();
    } },
  ].filter(Boolean), { width: 260 });
}

// ------------------------------------------------------------------ Darstellung
const fmtMinutes = min => (min == null ? '–' : min < 1 ? t('< 1 min') : min < 90 ? `${fmtNum(min, min < 10 ? 1 : 0)} min` : fmtDuration(min * 60));

function timeCell(m) {
  const e = m.estimate || {};
  if (e.minutes_per_100_pages == null) return h('span', { class: 'muted' }, '–');
  const measured = e.source === 'measured';
  return h('div', { title: t('{tps} Tokens pro Sekunde', { tps: fmtInt(e.tok_per_s) }) },
    h('div', { class: 'em-time' }, (measured ? '' : '≈ ') + fmtMinutes(e.minutes_per_100_pages)),
    h('div', { class: ['small', measured ? 'ok-text' : 'muted'] }, measured ? t('gemessen') : t('geschätzt')));
}

function indexCell(m, d) {
  const ix = m.index || {};
  if (ix.vectors) return h('div', { title: t('Abschnitte mit Vektoren dieses Modells') }, fmtInt(ix.vectors), h('div', { class: 'muted small' }, fmtBytes(ix.bytes)));
  if (!d.chunks || !ix.estimated_bytes) return h('span', { class: 'muted' }, '–');
  return h('div', { title: t('Platzbedarf des Index, wenn alle {n} Abschnitte deiner Bibliothek mit diesem Modell eingebettet sind', { n: fmtInt(d.chunks) }) },
    '≈ ' + fmtBytes(ix.estimated_bytes), h('div', { class: 'muted small' }, t('für alle Texte')));
}

function actionCell(m, d) {
  const jid = (m.job && m.job.id) || ms().jobOf[m.id];
  const job = jid ? (state.jobs[jid] || m.job) : null;
  if (job && ['queued', 'running'].includes(job.status)) {
    const dl = job.kind === 'model-download' && job.total > 1e6;  // im Kurztest danach zählt total die Schritte
    const label = dl ? t('{a} von {b} MB', { a: fmtInt(Math.round(job.done / 1e6)), b: fmtInt(Math.round(job.total / 1e6)) }) : job.message || job.phase;
    return h('div', { class: 'em-job' },
      progress(job.done, job.total, label),
      btn(t('Abbrechen'), { size: 'sm', kind: 'ghost', onClick: () => api.post(`/api/jobs/${job.id}/cancel`) }));
  }
  const busyElsewhere = d.models.some(x => x.job && x.id !== m.id && x.job.kind === 'model-test');
  const more = iconBtn('more', t('Weitere Aktionen'), e => modelMenu(e, m));
  if (!m.installed) {
    const resume = m.partial_bytes > 0;
    const noneInstalled = !d.models.some(x => x.installed);
    return h('div', { class: 'em-actions' },
      btn(resume ? t('Fortsetzen') : t('Herunterladen'), { size: 'sm', icon: 'download', kind: m.default && noneInstalled ? 'primary' : 'secondary',
        title: resume ? t('{a} von {b} bereits geladen', { a: fmtBytes(m.partial_bytes), b: fmtBytes(m.bytes) }) : t('{s} herunterladen', { s: fmtBytes(m.bytes) }),
        onClick: () => startDownload(m) }), more);
  }
  return h('div', { class: 'em-actions' },
    m.active ? badge(t('aktiv'), 'success') : btn(t('Verwenden'), { size: 'sm', kind: 'primary', onClick: () => useModel(m) }),
    !m.test && btn(t('Kurztest'), { size: 'sm', kind: 'ghost', icon: 'play', disabled: busyElsewhere, onClick: () => startTest(m) }),
    more);
}

function propsCell(m) {
  const lines = [
    m.languages && t('Sprachen: {x}', { x: m.languages }),
    m.context && t('Textlänge: {n} Tokens', { n: fmtInt(m.context) }),
    m.dim && t('Vektoren: {n} Werte', { n: fmtInt(m.dim) }),
    m.license && t('Lizenz: {x}', { x: m.license }),
  ].filter(Boolean);
  return h('div', { class: 'em-props' },
    h('div', { class: 'em-mteb', title: m.mteb_note || t('Mittelwert im mehrsprachigen MTEB v2 (höher = besser)') },
      'MTEB ', h('b', null, m.mteb != null ? fmtNum(m.mteb, 1) : '–'), m.mteb == null && m.mteb_note ? h('span', { class: 'muted' }, ' ⓘ') : null),
    lines.map((x, i) => h('div', { key: i, class: 'muted small' }, x)));
}

function sizeCell(m) {
  const ram = m.ram || {};
  return h('div', null, fmtBytes(m.bytes),
    ram.mb ? h('div', { class: 'muted small', title: ram.source === 'measured' ? t('Arbeitsspeicher beim Einbetten, gemessen auf diesem Rechner') : t('Arbeitsspeicher beim Einbetten, gemessen auf dem Referenzrechner') },
      t('RAM ≈ {x}', { x: fmtBytes(ram.mb * 2 ** 20) })) : null);
}

function badges(m) {
  return h('div', { class: 'chips em-badges' },
    m.default && badge(t('vorausgewählt'), 'accent', t('Empfohlener Standard')),
    m.user ? badge(t('nicht geprüft'), 'warning', t('Selbst hinzugefügt – Präfixe und Pooling stammen aus der Modellbeschreibung. Der Kurztest zeigt, ob die Suche funktioniert.'))
      : m.official ? badge(t('offizielle Datei'), 'neutral', t('GGUF-Datei vom Hersteller bzw. von llama.cpp (ggml-org)'))
        : badge(t('Umwandlung durch Dritte'), 'neutral', t('GGUF-Datei von Dritten umgewandelt; Datei und Prüfsumme sind im Katalog festgelegt und in Zotivity getestet')),
    m.installed && !m.active ? badge(t('heruntergeladen'), 'success') : null);
}

function detailRow(m, d) {
  const rt = m.runtime || {};
  const test = m.test;
  const cur = state.settings.embedding;
  const prefix = x => x ? h('code', { class: 'em-prefix' }, x.replace(/\n/g, '⏎ ')) : h('span', { class: 'muted' }, t('keins'));
  // Heruntergeladene und eigene Modelle: Präfixe bearbeiten; sonst nur anzeigen
  const editable = m.installed || m.user;
  return h('div', { class: 'em-detail' },
    h('div', { class: 'em-detail-grid' },
      h('div', { class: 'stack-sm' },
        m.notes && h('p', null, m.notes),
        editable ? prefixEditor(m) : [
          h('div', null, h('span', { class: 'muted small' }, t('Präfix für Suchanfragen')), h('div', null, prefix(rt.query_prefix))),
          h('div', null, h('span', { class: 'muted small' }, t('Präfix für Textabschnitte')), h('div', null, prefix(rt.document_prefix)))],
        h('div', { class: 'muted small' }, t('Pooling: {p} · höchstens {n} Tokens je Abschnitt', { p: rt.pooling || t('aus der Datei'), n: fmtInt(rt.ctx) })),
        h('div', { class: 'muted small' }, t('Datei: {f} ({q}) aus {r}', { f: m.file, q: m.quant || '?', r: m.repo }))),
      h('div', { class: 'stack-sm' },
        test ? h('div', null, h('b', null, t('Kurztest auf diesem Rechner')),
          h('div', { class: test.ok ? 'ok-text' : 'warn-text' }, icon(test.ok ? 'check' : 'alert', 14), ' ', t('{a} von {b} Testfragen richtig (deutsch/englisch, sprachübergreifend)', { a: test.top1, b: test.queries })),
          h('div', { class: 'muted small' }, t('{tps} Tokens/s · ≈ {min} pro 100 Seiten · RAM {ram} · geladen in {s} s', { tps: fmtInt(test.tok_per_s), min: fmtMinutes(test.minutes_per_100_pages), ram: test.ram_mb ? fmtBytes(test.ram_mb * 2 ** 20) : '–', s: fmtNum(test.load_s, 1) })),
          h('div', { class: 'muted small' }, fmtDate(test.measured_at)))
          : h('div', { class: 'muted small' }, m.installed ? t('Noch kein Kurztest auf diesem Rechner.') : t('Nach dem Download misst ein Kurztest (10–60 Sekunden) Tempo und Suchqualität auf diesem Rechner.')),
        m.reference && m.reference.tok_per_s && h('div', { class: 'muted small' },
          t('Referenzrechner ({cpu}): {tps} Tokens/s, {a} von 8 Testfragen richtig', { cpu: (d.catalog.reference || {}).cpu || '–', tps: fmtInt(m.reference.tok_per_s), a: m.reference.top1 ?? '–' })),
        m.active && m.matryoshka && m.matryoshka.length ? field(t('Vektorlänge'), select({ value: cur.dimensions || '', label: t('Vektorlänge'),
          options: [{ value: '', label: t('voll ({n} Werte)', { n: fmtInt(m.dim) }) }, ...m.matryoshka.map(n => ({ value: n, label: t('{n} Werte – kleinerer Index', { n }) }))],
          onChange: v => useModel(m, v ? Number(v) : null) }), { help: t('Kürzere Vektoren sparen Speicher und machen die Suche etwas ungenauer. Jede Länge hat einen eigenen Index.') }) : null)));
}

// Präfixe stehen vor jedem Text, bevor er eingebettet wird (viele Modelle unterscheiden so Frage und Textstelle).
// Katalogmodelle: eigene Werte statt der geprüften (zurücksetzbar); eigene Modelle: auch das Pooling.
function prefixEditor(m) {
  const p = m.prefixes || m.runtime;
  const sig = JSON.stringify([p.query_prefix, p.document_prefix, m.runtime.pooling]);
  const s = ui('embprefix:' + m.id, { qp: '', dp: '', pooling: '', sig: null });
  if (s.sig !== sig) Object.assign(s, { qp: p.query_prefix, dp: p.document_prefix, pooling: m.runtime.pooling, sig });  // neu vom Dienst
  const def = m.default_prefixes;
  const custom = !!def && (p.query_prefix !== def.query_prefix || p.document_prefix !== def.document_prefix);
  const save = async () => {
    const r = m.user
      ? await run(() => api.put(`/api/embedding/user/${m.id}`, { query_prefix: s.qp, document_prefix: s.dp, pooling: s.pooling }))
      : await run(() => api.put(`/api/embedding/local/${m.id}/prefixes`, { query_prefix: s.qp, document_prefix: s.dp }));
    afterPrefixChange(m, r);
  };
  const reset = async () => afterPrefixChange(m, await run(() => api.del(`/api/embedding/local/${m.id}/prefixes`)), true);
  return h('div', { class: 'stack-sm em-prefix-edit' },
    h('div', { class: 'row' }, h('b', null, t('Präfixe')),
      custom ? badge(t('eigene Werte'), 'warning', t('Abweichend vom geprüften Katalogwert')) : def ? badge(t('Katalogwert'), 'neutral') : null),
    field(t('Präfix für Suchanfragen'), textArea({ value: s.qp, rows: 2, onInput: v => { s.qp = v; } })),
    field(t('Präfix für Textabschnitte'), textInput({ value: s.dp, onInput: v => { s.dp = v; } })),
    m.user && field(t('Pooling'), select({ value: s.pooling, onChange: v => { s.pooling = v; }, options: poolingOptions() })),
    h('p', { class: 'muted small' }, t('Präfixe stehen vor jedem Text, bevor er eingebettet wird. Geänderte Präfixe ergeben einen eigenen Index – der bisherige bleibt unter „Gespeicherte Indizes“ erhalten.')),
    h('div', { class: 'row' }, btn(t('Speichern'), { size: 'sm', onClick: save }),
      custom && btn(t('Standard wiederherstellen'), { size: 'sm', kind: 'ghost', icon: 'refresh', title: t('Präfixe aus dem Katalog verwenden'), onClick: reset })));
}

async function afterPrefixChange(m, r, reset = false) {
  toast(reset ? t('Präfixe aus dem Katalog wiederhergestellt.') : t('Gespeichert. Geänderte Präfixe ergeben einen eigenen Index.'), 'success', 5000);
  refreshAll();
  if (r && r.active) {
    // Das aktive Modell bettet jetzt anders ein: neuer Index – wie bei einem Modellwechsel erklären
    resetEmbeddingViews();
    await loadSettings();
    afterEmbeddingSwitch(null, null, { force: true, prevLabel: t('{m} mit den bisherigen Präfixen', { m: m.name }) });
  }
}

const poolingOptions = () => [{ value: '', label: t('aus der Datei') }, { value: 'cls', label: 'CLS' }, { value: 'mean', label: t('Mittelwert') }, { value: 'last', label: t('letztes Token') }];

function runtimeLine(d) {
  const r = d.runtime || {};
  const m = d.machine || {};
  const src = { measured: t('umgerechnet aus deinen Kurztests'), cpu_test: t('umgerechnet aus einem Rechentest'), reference: t('Werte des Referenzrechners') }[m.source] || '';
  return h('div', { class: 'em-runtime' },
    r.available ? h('span', { class: 'ok-text small' }, icon('check', 13), ' ', t('Laufzeit llama.cpp {v}', { v: r.version || '' }))
      : h('span', { class: 'danger-text small' }, icon('alert', 13), ' ', t('Laufzeit fehlt – Zotivity neu installieren')),
    h('span', { class: 'muted small' }, icon('cpu', 13), ' ', m.cpu || '', r.avx2 === false ? ' · ' + t('ohne AVX2 (langsamer)') : r.avx2 ? ' · AVX2' : ''),
    h('span', { class: 'muted small', title: t('Zeitschätzung für Modelle ohne Kurztest: {s}', { s: src }) }, t('Zeiten: {s}', { s: src })),
    m.source !== 'measured' && h('button', { type: 'button', class: 'link-btn small', onclick: async () => { await run(() => api.post('/api/system/cpu-test')); loadLocalModels(true); } }, t('Rechentest wiederholen')));
}

// Tabelle der Modelle: im Katalog-Dialog vollständig und nach Gruppen, im Reiter nur die installierten Modelle und
// kompakt (ohne „Stärken“ und „Eigenschaften“). Jede Zeile lässt sich für Details und Präfixe aufklappen.
function modelTable(d, models, { compact = false, groups = null } = {}) {
  const s = ms();
  const cols = compact ? 5 : 7;
  const rows = [];
  const row = m => {
    const open = !!s.open[m.id];
    const toggle = () => { s.open[m.id] = !open; update(); };
    rows.push(h('tr', { key: m.id, class: ['em-row', m.active && 'active', open && 'open'] },
      h('td', { class: 'em-name' },
        h('button', { type: 'button', class: 'em-toggle', 'aria-expanded': open ? 'true' : 'false', onclick: toggle },
          icon(open ? 'chevronDown' : 'chevronRight', 13), h('b', null, m.name)),
        h('div', { class: 'muted small' }, [m.vendor, m.year, m.params_m ? t('{n} Mio. Parameter', { n: fmtInt(Math.round(m.params_m)) }) : null].filter(Boolean).join(' · ')),
        badges(m),
        // Gut sichtbar: Details (Präfixe, Messwerte, Datei) – bei heruntergeladenen Modellen mit änderbaren Präfixen
        h('button', { type: 'button', class: 'link-btn small em-details-btn', 'aria-expanded': open ? 'true' : 'false', onclick: toggle },
          icon(open ? 'chevronDown' : 'chevronRight', 12), ' ',
          open ? t('Details ausblenden') : m.installed || m.user ? t('Details und Präfixe') : t('Details'))),
      !compact && h('td', { class: 'em-strength' }, h('div', null, m.strengths), m.disciplines && h('div', { class: 'muted small em-disc' }, icon('target', 12), ' ', m.disciplines)),
      !compact && h('td', null, propsCell(m)),
      h('td', { class: 'num' }, sizeCell(m)),
      h('td', { class: 'num' }, timeCell(m)),
      h('td', { class: 'num' }, indexCell(m, d)),
      h('td', { class: 'em-act' }, actionCell(m, d))));
    if (open) rows.push(h('tr', { key: m.id + ':d', class: 'em-detail-row' }, h('td', { colspan: cols }, detailRow(m, d))));
  };
  if (groups) {
    for (const g of groups) {
      rows.push(h('tr', { key: 'g:' + g.id, class: 'em-group' }, h('td', { colspan: cols }, g.label)));
      models.filter(x => x.group === g.id).forEach(row);
    }
  } else {
    models.forEach(row);
  }
  const head = h('thead', null, h('tr', null, h('th', null, t('Modell')),
    !compact && h('th', null, t('Stärken · geeignet für')), !compact && h('th', null, t('Eigenschaften')),
    h('th', { class: 'num' }, compact ? t('Grösse') : t('Download')),
    h('th', { class: 'num', title: t('Rechenzeit für das Einbetten von 100 Seiten auf diesem Rechner') }, t('Zeit / 100 S.')),
    h('th', { class: 'num' }, t('Index')), h('th', null)));
  return h('div', { class: 'table-wrap' }, h('table', { class: ['grid', 'em-table', compact && 'em-compact'] }, head, h('tbody', null, rows)));
}

// Laufender Download oder Kurztest eines Modells?
function modelBusy(m) {
  const jid = (m.job && m.job.id) || ms().jobOf[m.id];
  const job = jid ? (state.jobs[jid] || m.job) : null;
  return !!job && ['queued', 'running'].includes(job.status);
}

// Im Reiter: nur heruntergeladene Modelle (dazu laufende bzw. angehaltene Downloads und eigene Modelle).
// Alle übrigen stehen im Dialog „Modell hinzufügen“ (Katalog und Suche auf Hugging Face).
export function installedModelsCard() {
  const s = ms();
  if (!s.data && !s.loading && !s.error) loadLocalModels();
  const d = s.data;
  if (!d) return card(t('Installierte Modelle'), 'layers', s.error ? notice('error', s.error) : h('div', { class: 'row' }, spinner(16), h('span', { class: 'muted' }, t('Katalog und Rechenleistung werden geprüft …'))));
  const list = d.models.filter(m => m.installed || m.user || m.partial_bytes > 0 || modelBusy(m));
  const rec = d.models.find(m => m.default) || d.models[0];
  const anyInstalled = list.some(m => m.installed);
  return card(t('Installierte Modelle'), 'layers', h('div', { class: 'stack' },
    list.length ? modelTable(d, list, { compact: true }) : null,
    !anyInstalled && rec && !modelBusy(rec) ? notice('info', t('Noch kein Modell heruntergeladen. Für die meisten Bibliotheken empfohlen: {m} ({s}).', { m: rec.name, s: fmtBytes(rec.bytes) }),
      h('div', { class: 'notice-actions' },
        btn(t('{m} herunterladen', { m: rec.name }), { size: 'sm', kind: 'primary', icon: 'download', onClick: () => startDownload(rec) }),
        btn(t('Alle Modelle ansehen …'), { size: 'sm', onClick: () => openCatalogDialog() }))) : null,
    runtimeLine(d)),
  { actions: h('div', { class: 'row nowrap' },
    btn(t('Modell hinzufügen …'), { size: 'sm', kind: anyInstalled ? 'secondary' : 'ghost', icon: 'plus', onClick: () => openCatalogDialog() }),
    iconBtn('refresh', t('Neu laden'), () => loadLocalModels(true))) });
}

// Dialog „Modell hinzufügen“: geprüfter Katalog (mit Download) und Suche auf Hugging Face
export function openCatalogDialog(tab = 'catalog') {
  const s = ms();
  s.dialogTab = tab;
  if (!s.data && !s.loading) loadLocalModels();
  openModal({ title: t('Modell hinzufügen'), wide: true, cls: 'modal-xl', body: () => catalogDialogBody() });
}

function catalogDialogBody() {
  const s = ms();
  const d = s.data;
  const tabs = segmented({ value: s.dialogTab || 'catalog', onChange: v => { s.dialogTab = v; update(); }, options: [
    { value: 'catalog', label: t('Katalog'), icon: 'layers' }, { value: 'search', label: t('Nach Namen suchen'), icon: 'search' }] });
  if (s.dialogTab === 'search') return h('div', { class: 'stack' }, tabs, searchBody());
  if (!d) return h('div', { class: 'stack' }, tabs, s.error ? notice('error', s.error) : h('div', { class: 'row' }, spinner(16), h('span', { class: 'muted' }, t('Katalog und Rechenleistung werden geprüft …'))));
  const groups = d.groups.filter(g => d.models.some(m => m.group === g.id));
  const cat = d.catalog || {};
  return h('div', { class: 'stack' }, tabs,
    h('p', { class: 'muted small' }, t('Geprüfte Modelle für die eingebaute Laufzeit. Heruntergeladen wird nur per Knopf, in den lokalen Datenordner. Die Zeit gilt für das Einbetten von 100 Seiten auf diesem Rechner: geschätzt, bis ein Kurztest sie misst. Bei vielen Fächern sind mehrsprachige Allzweckmodelle die beste Wahl; Fachmodelle gibt es meist nur auf Englisch.')),
    runtimeLine(d),
    modelTable(d, d.models, { groups }),
    h('div', { class: 'row wrap muted small' },
      h('span', null, t('Katalog {v} ({o})', { v: cat.version, o: cat.origin === 'remote' ? t('zentral geladen') : t('mitgeliefert') })),
      h('span', null, '·'),
      h('span', null, t('Modelle belegen {a} · frei {b}', { a: fmtBytes(d.disk.used_bytes), b: fmtBytes(d.disk.free_bytes) })),
      api.isDesktop() && h('button', { type: 'button', class: 'link-btn small', onclick: () => api.revealPath(d.disk.folder) }, t('Ordner öffnen'))));
}

// ------------------------------------------------------------------ Einstellungen der Laufzeit
// Zugeklappt „Erweitert“: Threads, Parallelität, Entladen und zentraler Katalog braucht man selten
export function builtinOptionsCard() {
  const e = state.settings.embedding;
  const setEmb = patch => saveSettings({ embedding: patch });
  const cat = ms().data && ms().data.catalog;
  const summary = [t('CPU-Threads: {n}', { n: e.num_thread || t('automatisch') }), t('{n} Abschnitte gleichzeitig', { n: e.parallel }),
    t('Entladen nach {n} min', { n: e.keep_alive_minutes }),
    cat ? t('Katalog {v} ({o})', { v: cat.version, o: cat.origin === 'remote' ? t('zentral geladen') : t('mitgeliefert') }) : null].filter(Boolean).join(' · ');
  return foldCard('emb-runtime', t('Erweitert: Laufzeit und Modellkatalog'), 'cpu', summary, () => h('div', { class: 'stack' },
    h('div', { class: 'grid-2' },
      field(t('CPU-Threads'), numberInput({ value: e.num_thread, min: 1, max: 256, int: true, nullable: true, placeholder: t('automatisch'), onChange: v => setEmb({ num_thread: v }) }),
        { help: t('Leer = Anzahl physischer Kerne. Mehr Threads können etwas schneller sein, machen den Rechner beim Indexieren aber träger.') }),
      field(t('Gleichzeitige Abschnitte'), numberInput({ value: e.parallel, min: 1, max: 16, int: true, onChange: v => setEmb({ parallel: v }) }),
        { help: t('Wie viele Abschnitte die Laufzeit zugleich verarbeitet. 4 ist meist am schnellsten; weniger spart Arbeitsspeicher.') }),
      field(t('Modell entladen nach (Minuten)'), numberInput({ value: e.keep_alive_minutes, min: 1, max: 240, int: true, onChange: v => setEmb({ keep_alive_minutes: v }) }),
        { help: t('Ohne Anfrage wird das Modell nach dieser Zeit aus dem Arbeitsspeicher entfernt und bei Bedarf in wenigen Sekunden neu geladen.') })),
    field(t('Zentraler Modellkatalog'), h('div', { class: 'row nowrap' },
      h('div', { class: 'grow' }, textInput({ value: state.settings.model_catalog_url, placeholder: t('leer = nur der mitgelieferte Katalog'),
        onChange: v => saveSettings({ model_catalog_url: v.trim() }) })),
      btn(t('Aktualisieren'), { size: 'sm', icon: 'refresh', disabled: !state.settings.model_catalog_url, onClick: async () => {
        const r = await run(() => api.post('/api/embedding/catalog/refresh'));
        toast(r.updated ? t('Katalog {v} geladen.', { v: r.version }) : t('Der Katalog ist aktuell ({v}).', { v: r.version }), 'success', 5000);
        loadLocalModels(true);
      } })),
    { help: t('Adresse einer Katalogdatei (HTTPS oder Datei-/Netzwerkpfad), später die Datei im GitHub-Repository von Zotivity. Sie wird beim Start geladen und nur übernommen, wenn sie neuer ist; ohne Internet gilt der zuletzt geladene bzw. mitgelieferte Katalog.'),
      hint: cat ? t('Aktuell: Katalog {v} ({o})', { v: cat.version, o: cat.origin === 'remote' ? t('zentral geladen') : t('mitgeliefert') }) : null })));
}

// ------------------------------------------------------------------ Namenssuche auf Hugging Face
async function doSearch() {
  const s = ms();
  const q = s.q.trim();
  if (q.length < 2) return;
  s.searching = true; s.searchError = null; update();
  try { s.results = await api.get(`/api/embedding/hf/search?q=${encodeURIComponent(q)}`); } catch (err) { s.searchError = err.message; s.results = null; }
  s.searching = false; update();
}

const SUPPORT = () => ({
  supported: [t('unterstützt'), 'success', t('Embedding-Bauweise, die llama.cpp ausführen kann')],
  decoder: [t('Sprachmodell-Bauweise'), 'warning', t('Funktioniert nur, wenn das Modell für Embeddings trainiert ist (Pooling „letztes Token“).')],
  not_embedding: [t('kein Embedding-Modell'), 'danger', t('Ein Sprachmodell für Text – nicht zum Einbetten geeignet.')],
  unknown: [t('unbekannt'), 'neutral', t('llama.cpp kennt diese Bauweise möglicherweise nicht.')],
});

function supportBadge(x) {
  const [label, kind, title] = SUPPORT()[x.support] || SUPPORT().unknown;
  return badge(`${x.architecture || '?'} · ${label}`, kind, title);
}

// back: zurück in den Dialog „Modell hinzufügen“ (bei Abbrechen oder Fehler)
async function pickModel(repo, back = closeModal) {
  openModal({ title: repo, body: () => h('div', { class: 'row' }, spinner(16), h('span', { class: 'muted' }, t('Angaben werden geladen …'))) });
  let d;
  try { d = await api.get(`/api/embedding/hf/model?repo=${encodeURIComponent(repo)}`); } catch (err) { back(); toast(err.message, 'error', 8000); return; }
  if (!d.files.length) { back(); toast(t('In diesem Repository gibt es keine GGUF-Datei.'), 'warning', 6000); return; }
  const v = { file: d.recommended, qp: d.suggested.query_prefix || '', dp: d.suggested.document_prefix || '', pooling: d.suggested.pooling || '' };
  const blocked = d.gated || d.support === 'not_embedding';
  const add = async download => {
    const r = await run(() => api.post('/api/embedding/hf/add', { repo: d.repo, file: v.file, query_prefix: v.qp, document_prefix: v.dp, pooling: v.pooling, download }));
    closeModal();
    if (r.job) { ms().jobOf[r.model] = r.job.id; watchModelJob(r.job, d.repo); }
    toast(download ? t('Hinzugefügt unter „Eigene Modelle“ – der Download läuft.') : t('Hinzugefügt unter „Eigene Modelle“.'), 'success', 6000);
    loadLocalModels(true);
  };
  openModal({
    title: t('Modell hinzufügen'),
    body: () => h('div', { class: 'stack' },
      h('div', { class: 'row wrap' }, h('b', null, d.repo), supportBadge(d), d.license && badge(d.license, 'neutral'),
        h('a', { href: `https://huggingface.co/${d.repo}`, class: 'small' }, icon('external', 12), ' ', t('auf Hugging Face'))),
      d.gated && notice('error', t('Dieses Modell verlangt auf Hugging Face eine Anmeldung oder Lizenzbestätigung – das unterstützt Zotivity nicht.')),
      d.support === 'not_embedding' && notice('error', t('Das ist ein Sprachmodell, kein Embedding-Modell.')),
      d.support === 'unknown' && notice('warning', t('llama.cpp kennt die Bauweise „{a}“ möglicherweise nicht – das Modell lässt sich dann nicht laden.', { a: d.architecture || '?' })),
      d.support === 'decoder' && notice('info', t('Sprachmodell-Bauweise ({a}): Das funktioniert nur mit Modellen, die für Embeddings trainiert sind. Pooling „letztes Token“ verwenden.', { a: d.architecture })),
      field(t('Datei (Genauigkeit)'), select({ value: v.file, onChange: x => { v.file = x; update(); },
        options: d.files.map(f => ({ value: f.name, label: `${f.quant || f.name} · ${fmtBytes(f.bytes)}` })) }),
      { hint: t('Q8_0 (8 Bit): kaum ein Unterschied zum Original – empfohlen. F16/BF16: volle Genauigkeit, doppelt so gross. Q4–Q6: kleiner und etwas ungenauer.') }),
      field(t('Präfix für Suchanfragen'), textArea({ value: v.qp, rows: 2, onInput: x => { v.qp = x; } })),
      field(t('Präfix für Textabschnitte'), textInput({ value: v.dp, onInput: x => { v.dp = x; } }),
        { hint: d.suggested.source ? t('Vorschlag aus der Beschreibung von {r} – bitte mit der Modellbeschreibung vergleichen.', { r: d.suggested.source })
          : t('Keine Angaben gefunden, deshalb leer. Viele Modelle suchen ohne die richtigen Präfixe deutlich schlechter – siehe Modellbeschreibung.') }),
      field(t('Pooling'), select({ value: v.pooling, onChange: x => { v.pooling = x; }, options: poolingOptions() })),
      notice('warning', t('Nicht geprüftes Modell: Nach dem Download zeigt der Kurztest, ob die Suche damit funktioniert.'))),
    onClose: back === closeModal ? null : back,
    actions: [{ label: t('Abbrechen'), onClick: back },
      { label: t('Nur hinzufügen'), disabled: blocked, onClick: () => add(false) },
      { label: t('Hinzufügen und herunterladen'), kind: 'primary', disabled: blocked, onClick: () => add(true) }],
  });
}

// Reiter „Nach Namen suchen“ im Dialog „Modell hinzufügen“
function searchBody() {
  const s = ms();
  const r = s.results;
  return h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Weitere Embedding-Modelle im GGUF-Format auf Hugging Face suchen, z. B. „e5“, „gte“ oder „granite-embedding“ – oder eine Adresse von Hugging Face einfügen. Solche Modelle sind nicht geprüft: Präfixe und Pooling schlägt Zotivity aus der Beschreibung des Originalmodells vor.')),
    h('div', { class: 'row nowrap' },
      h('div', { class: 'grow' }, textInput({ value: s.q, placeholder: t('Modellname oder https://huggingface.co/…'), label: t('Modell suchen'),
        onInput: v => { s.q = v; }, onKeyDown: e => { if (e.key === 'Enter') { s.q = e.target.value; doSearch(); } } })),
      btn(t('Suchen'), { icon: 'search', busy: s.searching, onClick: doSearch })),
    s.searchError && notice('error', s.searchError),
    r && (r.results.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
      h('thead', null, h('tr', null, h('th', null, t('Repository')), h('th', null, t('Bauweise')), h('th', { class: 'num' }, t('Parameter')),
        h('th', null, t('Lizenz')), h('th', { class: 'num' }, t('Downloads')), h('th', null, t('Aktualisiert')), h('th', null))),
      h('tbody', null, r.results.map(x => h('tr', { key: x.repo },
        h('td', null, h('a', { href: `https://huggingface.co/${x.repo}` }, x.repo), x.gated ? ' ' : null, x.gated ? badge(t('Anmeldung nötig'), 'danger') : null),
        h('td', null, supportBadge(x)),
        h('td', { class: 'num' }, x.params_m ? t('{n} Mio.', { n: fmtInt(x.params_m) }) : '–'),
        h('td', { class: 'small' }, x.license || '–'),
        h('td', { class: 'num' }, fmtInt(x.downloads)),
        h('td', { class: 'small nowrap' }, x.updated ? new Date(x.updated).toLocaleDateString() : '–'),
        h('td', { class: 'num' }, x.catalog_id ? btn(t('Im Katalog'), { size: 'sm', kind: 'ghost', onClick: () => { s.open[x.catalog_id] = true; s.dialogTab = 'catalog'; update(); } })
          : btn(t('Auswählen …'), { size: 'sm', disabled: x.gated || x.support === 'not_embedding', onClick: () => pickModel(x.repo, () => openCatalogDialog('search')) })))))))
      : h('p', { class: 'muted' }, t('Keine Embedding-Modelle im GGUF-Format gefunden.'))));
}

// ------------------------------------------------------------------ Index übernehmen (Hinweis über den gespeicherten Indizes)
export function adoptNotice() {
  const s = ms();
  if (s.adopt === null) { s.adopt = false; api.get('/api/embedding/adopt').then(r => { s.adopt = r.candidates; update(); }).catch(() => {}); }
  if (!s.adopt || !s.adopt.length) return null;
  const c = s.adopt[0];
  return notice('info', t('Für das aktive Modell gibt es einen Index aus {p} ({n} Abschnitte). Er lässt sich übernehmen, statt alles neu einzubetten.', { p: providerLabel(c.provider), n: fmtInt(c.vectors) }),
    h('div', { class: 'notice-actions' }, btn(t('Prüfen und übernehmen'), { size: 'sm', kind: 'primary', onClick: () => adoptIndex(c.space) })));
}

// ------------------------------------------------------------------ Vergleich: gleiche Frage, zwei Modelle
const comparableSpaces = () => {
  const s = ms();
  if (s.spaces === null) { s.spaces = false; api.get('/api/embedding/spaces').then(r => { s.spaces = r; update(); }).catch(() => {}); }
  return s.spaces ? s.spaces.spaces.filter(x => x.n > 0) : [];
};

// Knopf „Modelle vergleichen …“ (bei den gespeicherten Indizes) – erst ab zwei Modellen mit Index
export function compareButton() {
  if (comparableSpaces().length < 2) return null;
  return btn(t('Modelle vergleichen …'), { size: 'sm', kind: 'ghost', icon: 'compare',
    title: t('Dieselbe Frage mit zwei Embedding-Modellen – Treffer nebeneinander'),
    onClick: () => openModal({ title: t('Modelle vergleichen'), wide: true, cls: 'modal-xl', body: () => compareBody() }) });
}

function compareBody() {
  const s = ms();
  const c = s.cmp;
  const spaces = comparableSpaces();
  const label = x => `${x.model} · ${providerLabel(x.provider)}${x.dim ? ` · ${x.dim}` : ''}`;
  if (spaces.length >= 2) {
    if (!spaces.find(x => x.space === c.a)) c.a = (spaces.find(x => x.space === s.spaces.active) || spaces[0]).space;
    if (!spaces.find(x => x.space === c.b) || c.b === c.a) c.b = (spaces.find(x => x.space !== c.a) || spaces[1]).space;
  }
  const go = async () => {
    if (!c.query.trim()) return;
    c.busy = true; c.result = null; update();
    try {
      c.result = await api.post('/api/embedding/compare', { query: c.query.trim(), a: c.a, b: c.b, filters: c.scope === 'project' && project() ? { project_id: project().id } : {} });
    } catch (err) { toast(err.message, 'error', 9000); }
    c.busy = false; update();
  };
  const side = r => h('div', { class: 'cmp-col' },
    h('div', { class: 'cmp-head' }, h('b', null, r.model), h('span', { class: 'muted small' }, providerLabel(r.provider)),
      h('div', { class: 'muted small' }, t('Index deckt {a} von {b} Abschnitten ab', { a: fmtInt(r.coverage.embedded), b: fmtInt(r.coverage.chunks) }))),
    r.warning && notice('warning', t(r.warning)),
    h('ol', { class: 'cmp-list' }, r.hits.map((x, i) => h('li', { key: x.chunk_id + ':' + i, class: x.shared ? 'shared' : '' },
      h('div', { class: 'cmp-title' }, h('b', null, [x.creators, x.year].filter(Boolean).join(' ')), x.creators || x.year ? ' – ' : '', x.title || t('(ohne Titel)'),
        x.page ? h('span', { class: 'muted' }, ` · ${t('S. {p}', { p: x.page })}`) : null),
      h('div', { class: 'cmp-meta' }, h('span', { class: 'muted small' }, fmtNum(x.score, 3)), x.shared ? badge(t('in beiden'), 'accent') : null),
      h('div', { class: 'cmp-text small muted' }, x.text)))));
  return h('div', { class: 'stack' },
    h('p', { class: 'muted small' }, t('Dieselbe Frage mit zwei Embedding-Modellen – reine Bedeutungssuche, Treffer nebeneinander. Hilft beim Entscheid, welches Modell zur eigenen Bibliothek passt. Beide Modelle brauchen einen Index.')),
    spaces.length < 2 ? notice('info', t('Sobald zwei Modelle einen Index haben, lässt sich hier dieselbe Frage mit beiden vergleichen.')) : [
      h('div', { class: 'row nowrap' }, h('div', { class: 'grow' }, textInput({ value: c.query, placeholder: t('Frage oder Stichworte'), label: t('Frage'),
        onInput: v => { c.query = v; }, onKeyDown: e => { if (e.key === 'Enter') { c.query = e.target.value; go(); } } })),
      btn(t('Vergleichen'), { kind: 'primary', icon: 'compare', busy: c.busy, onClick: go })),
      h('div', { class: 'grid-2' },
        field(t('Modell A'), select({ value: c.a, onChange: v => { c.a = v; update(); }, options: spaces.map(x => ({ value: x.space, label: label(x) })) })),
        field(t('Modell B'), select({ value: c.b, onChange: v => { c.b = v; update(); }, options: spaces.map(x => ({ value: x.space, label: label(x) })) })),
        field(t('Bereich'), select({ value: c.scope, onChange: v => { c.scope = v; update(); }, options: [
          { value: 'project', label: project() ? t('Korpora des Projekts „{p}“', { p: project().name }) : t('Projekt') }, { value: 'all', label: t('ganze indexierte Bibliothek') }] }))),
      c.result && h('div', { class: 'stack-sm' },
        h('div', { class: 'muted small' }, t('{n} Texte stehen in beiden Listen (A: {a}, B: {b} Texte).', { n: c.result.shared_docs, a: c.result.docs.a, b: c.result.docs.b })),
        h('div', { class: 'cmp-grid' }, side(c.result.a), side(c.result.b)))]);
}

// Auswahl für das Embedding-Modell eines Projekts: eingebaute (heruntergeladene) Modelle und das aktuell eingestellte
export async function projectEmbeddingOptions(current) {
  const d = await loadLocalModels(true).catch(() => null);
  const opts = [{ value: '', label: t('Kein eigenes – das jeweils eingestellte Modell') }];
  for (const m of (d && d.models) || []) if (m.installed) opts.push({ value: `builtin|${m.id}`, label: `${m.name} (${t('eingebaut')})` });
  const e = state.settings && state.settings.embedding;
  if (e && e.provider !== 'builtin') opts.push({ value: `${e.provider}|${e.model}`, label: `${e.model} (${providerLabel(e.provider)})` });
  if (current && !opts.find(o => o.value === `${current.provider}|${current.model}`)) {
    opts.push({ value: `${current.provider}|${current.model}`, label: `${current.model} (${providerLabel(current.provider)})` });
  }
  return opts;
}
