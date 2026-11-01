// Mehrsprachigkeit der Oberfläche. Ausgangssprache ist Deutsch: t('Einstellungen') liefert in anderen Sprachen den
// Eintrag aus deren Wörterbuch (js/i18n/<code>.js), sonst den deutschen Text. Platzhalter: t('{n} Texte', { n: 3 }).
// Neue Sprache: Datei js/i18n/<code>.js mit `export default { 'Deutscher Text': 'Übersetzung', … }` anlegen und
// unten in LANGUAGES eintragen – die Oberfläche bietet sie dann automatisch an.
import en from '../i18n/en.js';

export const LANGUAGES = [
  { code: 'de', label: 'Deutsch', dict: null, locale: 'de-CH' },
  { code: 'en', label: 'English', dict: en, locale: 'en-GB' },
];

let current = LANGUAGES[0];

export function setLanguage(code) {
  current = LANGUAGES.find(l => l.code === code) || LANGUAGES[0];
  document.documentElement.lang = current.code;
}

export const language = () => current.code;
export const locale = () => current.locale;

export function t(text, params) {
  let s = (current.dict && current.dict[text]) || text;
  if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => (params[k] ?? m));
  return s;
}

// Sprachen für KI-Ausgaben (Antworten, Forschungsstand). Muss zu LANG_NAMES in rag/prompts.py passen.
export const OUTPUT_LANGUAGES = ['de', 'en', 'fr', 'it', 'es', 'pt', 'nl', 'pl', 'sv', 'da', 'rm', 'tr'];

// Name einer Sprache in der Sprache der Oberfläche (z. B. „fr“ → „Französisch“ bzw. „French“)
export function languageName(code) {
  try {
    const n = new Intl.DisplayNames([current.locale], { type: 'language' }).of(code);
    return n ? n.charAt(0).toUpperCase() + n.slice(1) : code;
  } catch { return code; }
}

// Systemsprache als Vorschlag, falls noch nichts eingestellt ist
export function systemLanguage() {
  const nav = (navigator.language || 'de').slice(0, 2).toLowerCase();
  return LANGUAGES.some(l => l.code === nav) ? nav : 'en';
}
