import { t, locale } from './i18n.js';

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export const fmtInt = n => (n ?? 0).toLocaleString(locale());

export function fmtNum(n, digits = 1) {
  return (n ?? 0).toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtBytes(b) {
  if (b == null) return '–';
  if (b >= 1e9) return `${fmtNum(b / 1e9, 2)} GB`;
  if (b >= 1e6) return `${fmtNum(b / 1e6, 0)} MB`;
  return `${fmtNum(b / 1e3, 0)} KB`;
}

export function fmtDuration(s) {
  if (s == null || !isFinite(s)) return '';
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${m % 60} min`;
}

export function fmtAgo(ts) {
  if (!ts) return '';
  const s = Date.now() / 1000 - ts;
  if (s < 60) return t('gerade eben');
  if (s < 3600) return t('vor {n} min', { n: Math.round(s / 60) });
  if (s < 86400) return t('vor {n} h', { n: Math.round(s / 3600) });
  return new Date(ts * 1000).toLocaleDateString(locale());
}

// Zeitpunkt in Sekunden (Zotivity) oder als ISO-Text (Recherche)
export function fmtDate(ts) {
  if (!ts) return '';
  if (typeof ts === 'string') {
    const d = new Date(ts);
    return isNaN(d) ? ts : d.toLocaleString(locale(), { dateStyle: 'short', timeStyle: 'short' });
  }
  return new Date(ts * 1000).toLocaleString(locale());
}

export function debounce(fn, ms) {
  let tm;
  return (...args) => { clearTimeout(tm); tm = setTimeout(() => fn(...args), ms); };
}

// plural(3, t('Text'), t('Texte')) → „3 Texte“
export const plural = (n, one, many) => `${fmtInt(n)} ${n === 1 ? one : many}`;

// „1 Text“ / „3 Texte“ (übersetzbar)
export const nTexts = n => (n === 1 ? t('{n} Text', { n: fmtInt(n) }) : t('{n} Texte', { n: fmtInt(n) }));

// Indexiert = mit dem aktiven Modell durchsuchbar – auch Texte, die nur auf erneutes Lesen warten („zu aktualisieren“)
export const nIndexed = x => (x.indexed || 0) + (x.refresh || 0);

// Erklärungen für Tooltips und Hinweise (Indexieren = Lesen + Einbetten)
export const embedHint = () => t('Einbetten: Das Embedding-Modell rechnet jeden Abschnitt in einen Vektor um – erst dann findet ihn die Bedeutungssuche.');
export const refreshHint = () => t('Mit dem bisherigen Text durchsuchbar. Der nächste Lauf liest diese Texte neu ein (z. B. für genauere Seitenzahlen oder nach einer Änderung der Datei).');
// „Offen“ heisst nicht unbedingt „nie gelesen“: auch früher gelesene Texte ohne Vektoren des aktiven Modells
export const openHint = m => t('Mit {m} noch nicht durchsuchbar – wird beim nächsten Lauf gelesen.', { m });

// Text in die Zwischenablage (mit HTML-Fassung, falls angegeben – z. B. für Word)
export async function copyToClipboard(text, html) {
  try {
    if (html && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({
        'text/plain': new Blob([text], { type: 'text/plain' }), 'text/html': new Blob([html], { type: 'text/html' }) })]);
    } else {
      await navigator.clipboard.writeText(text);
    }
    return true;
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand('copy'); ta.remove();
    return ok;
  }
}
