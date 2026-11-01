// Zotero-Begriffe für die Oberfläche (Eintragsarten), übersetzbar.
import { t } from './i18n.js';

const TYPES = {
  journalArticle: 'Zeitschriftenartikel', book: 'Buch', bookSection: 'Buchkapitel', thesis: 'Abschlussarbeit',
  report: 'Bericht', webpage: 'Webseite', conferencePaper: 'Konferenzbeitrag', attachment: 'Datei', document: 'Dokument',
  magazineArticle: 'Magazinartikel', newspaperArticle: 'Zeitungsartikel', presentation: 'Präsentation',
  manuscript: 'Manuskript', blogPost: 'Blogbeitrag', forumPost: 'Forumsbeitrag', videoRecording: 'Video',
  audioRecording: 'Audioaufnahme', podcast: 'Podcast', interview: 'Interview', film: 'Film', encyclopediaArticle: 'Lexikonartikel',
  dictionaryEntry: 'Wörterbucheintrag', preprint: 'Preprint', dataset: 'Datensatz', statute: 'Gesetz', case: 'Gerichtsentscheid',
  letter: 'Brief', email: 'E-Mail', map: 'Karte', artwork: 'Kunstwerk', computerProgram: 'Software', standard: 'Norm',
  patent: 'Patent', hearing: 'Anhörung', bill: 'Gesetzesentwurf', radioBroadcast: 'Radiosendung', tvBroadcast: 'Fernsehsendung',
  instantMessage: 'Sofortnachricht',
};

export function itemTypeLabel(type) {
  return TYPES[type] ? t(TYPES[type]) : type || '';
}
