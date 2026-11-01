// Zugriff auf den lokalen Dienst. Schreibende Anfragen tragen den Header X-Zotivity (Schutz gegen CSRF).
import { t } from './i18n.js';

const HDR = { 'Content-Type': 'application/json', 'X-Zotivity': '1' };

export class ApiError extends Error {
  constructor(message, status, kind) { super(message); this.status = status; this.kind = kind; }
}

async function fail(res) {
  let message = `${res.status} ${res.statusText}`;
  let kind = null;
  try {
    const j = await res.json();
    kind = j.kind || null;
    if (typeof j.detail === 'string') message = j.detail;
    else if (Array.isArray(j.detail)) message = j.detail.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  } catch { /* kein JSON */ }
  throw new ApiError(message, res.status, kind);
}

async function request(method, path, body, opts = {}) {
  let res;
  try {
    res = await fetch(path, { method, headers: method === 'GET' ? undefined : HDR, body: body === undefined ? undefined : JSON.stringify(body), ...opts });
  } catch (err) {
    throw new ApiError(t('Der Zotivity-Dienst antwortet nicht.'), 0, 'offline');
  }
  if (!res.ok) await fail(res);
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}

export const get = path => request('GET', path);
export const post = (path, body = {}) => request('POST', path, body);
export const put = (path, body, opts) => request('PUT', path, body, opts);  // opts.keepalive: auch beim Schliessen des Fensters
export const del = path => request('DELETE', path);

// Server-Sent Events über POST (Antworten werden gestreamt)
export async function stream(path, body, onEvent, signal) {
  let res;
  try {
    res = await fetch(path, { method: 'POST', headers: HDR, body: JSON.stringify(body), signal });
  } catch (err) {
    if (err.name === 'AbortError') return;
    throw new ApiError(t('Der Zotivity-Dienst antwortet nicht.'), 0, 'offline');
  }
  if (!res.ok) await fail(res);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const line of block.split('\n')) if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

// ------------------------------------------------------------------ Desktop-Funktionen
// Im Programmfenster (pywebview) stellt Python Funktionen bereit; im Browser gibt es Ersatzlösungen.
const desktop = () => (window.pywebview && window.pywebview.api) || null;
export const isDesktop = () => !!desktop();

export async function openExternal(url) {
  const d = desktop();
  if (d) { await d.open_url(url); return; }
  const a = document.createElement('a');
  a.href = url; a.rel = 'noopener';
  if (/^https?:/.test(url)) a.target = '_blank';
  document.body.appendChild(a); a.click(); a.remove();
}

export async function saveText(filename, text, mime = 'text/plain') {
  const d = desktop();
  if (d) return d.save_text(filename, text);
  const blob = new Blob([text], { type: mime + ';charset=utf-8' });
  return downloadBlob(filename, blob);
}

export async function saveUrl(filename, url) {
  const d = desktop();
  if (d) return d.save_url(filename, url);
  const res = await fetch(url);
  return downloadBlob(filename, await res.blob());
}

function downloadBlob(filename, blob) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  return true;
}

export async function revealPath(path) {
  const d = desktop();
  if (d) return d.reveal(path);
  return false;
}
