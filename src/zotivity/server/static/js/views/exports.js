// Kopieren und Exportieren von KI-Ausgaben (Antworten, Textstellen, Forschungsstand) als Text, Word oder LaTeX.
// Word: Belege und Literaturverzeichnis als Zotero-Felder – mit dem Zotero-Word-Plugin weiter bearbeitbar.
// LaTeX: \parencite-Belege und BibTeX aus Zotero in einer einzigen, direkt übersetzbaren .tex-Datei.
import { toast, run } from '../core/store.js';
import * as api from '../core/api.js';
import { t } from '../core/i18n.js';
import { openMenu } from '../ui/components.js';
import { copyToClipboard } from '../core/util.js';

function query(target, format) {
  const p = new URLSearchParams({ kind: target.kind, id: String(target.id), format });
  return `/api/export?${p}`;
}

function safeName(s) {
  return (s || 'export').replace(/[\\/:*?"<>|\n\r]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'export';
}

export async function copyTarget(target, rich = false) {
  const r = await run(() => api.get(query(target, 'text')));
  if (await copyToClipboard(r.text, rich ? r.html : null)) toast(rich ? t('Formatiert kopiert – in Word einfügen.') : t('In die Zwischenablage kopiert.'), 'success', 2500);
}

async function saveAs(target, format, name) {
  const ext = { docx: 'docx', tex: 'tex', md: 'md' }[format];
  const saved = await run(() => api.saveUrl(`${safeName(name)}.${ext}`, query(target, format)));
  if (saved) toast(typeof saved === 'string' ? t('Gespeichert: {path}', { path: saved }) : t('Gespeichert.'), 'success', 4000);
}

// target: { kind: 'answer' | 'sources' | 'review', id }, name: Dateiname ohne Endung
export function exportMenu(e, target, name) {
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4, [
    { heading: t('Kopieren') },
    { label: t('Als Text (mit Quellenangaben)'), icon: 'copy', onClick: () => copyTarget(target, false) },
    { label: t('Formatiert für Word'), icon: 'copy', onClick: () => copyTarget(target, true) },
    '-',
    { heading: t('Speichern') },
    { label: t('Word (.docx) – Belege als Zotero-Felder'), icon: 'download', onClick: () => saveAs(target, 'docx', name) },
    { label: t('LaTeX (.tex) – mit Literaturdatenbank'), icon: 'download', onClick: () => saveAs(target, 'tex', name) },
    { label: t('Markdown (.md)'), icon: 'download', onClick: () => saveAs(target, 'md', name) },
  ], { width: 320 });
}
