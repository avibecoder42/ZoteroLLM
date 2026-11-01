// Markdown → HTML (sicher: erst escapen, dann formatieren). Belege [1] werden zu Knöpfen.
import { esc } from './util.js';

function inline(t, opts) {
  t = esc(t);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^*\w])\*(?!\s)(.+?)\*(?!\w)/g, '$1<em>$2</em>');
  t = t.replace(/\[([^\]]+)\]\(((?:https?|zotero):\/\/[^)\s]+)\)/g, (m, label, url) => `<a href="${url}" data-ext="1">${label}</a>`);
  // Belege des Forschungsstands: Klick öffnet die Auswahl (Eintrag in Zotero / PDF)
  t = t.replace(/\[([^\]]+)\]\(#cite-(\d+)\)/g, (m, label, n) => `<a href="#cite-${n}" class="cite-link" data-cite="${n}">${label}</a>`);
  if (opts.cites) {
    t = t.replace(/\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]/g, (m, inner) => {
      const nums = [];
      for (const part of inner.split(/[,;]/)) {
        const r = part.trim().split(/[–-]/).map(Number);
        if (r.length === 2 && r[1] >= r[0] && r[1] - r[0] < 20) for (let n = r[0]; n <= r[1]; n++) nums.push(n);
        else if (!isNaN(r[0])) nums.push(r[0]);
      }
      return nums.map(n => `<button type="button" class="cite" data-n="${n}">${n}</button>`).join('');
    });
  }
  return t;
}

export function markdown(src, opts = {}) {
  const lines = String(src || '').replace(/\r/g, '').split('\n');
  let html = '', list = null, para = [], inCode = false, code = [];
  const flush = () => { if (para.length) { html += `<p>${inline(para.join(' '), opts)}</p>`; para = []; } };
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    if (raw.trim().startsWith('```')) {
      if (inCode) { html += `<pre><code>${esc(code.join('\n'))}</code></pre>`; code = []; inCode = false; }
      else { flush(); closeList(); inCode = true; }
      continue;
    }
    if (inCode) { code.push(raw); continue; }
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); closeList(); continue; }
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      flush(); closeList();
      const l = Math.min(m[1].length + 1, 4);
      html += `<h${l}>${inline(m[2], opts)}</h${l}>`;
      continue;
    }
    if ((m = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/))) {
      flush();
      const t = /\d/.test(m[1]) ? 'ol' : 'ul';
      if (list !== t) { closeList(); html += `<${t}>`; list = t; }
      html += `<li>${inline(m[2], opts)}</li>`;
      continue;
    }
    if (line.startsWith('>')) { flush(); closeList(); html += `<blockquote>${inline(line.replace(/^>\s?/, ''), opts)}</blockquote>`; continue; }
    if (list && /^\s{2,}\S/.test(raw)) { html = html.replace(/<\/li>$/, ` ${inline(line.trim(), opts)}</li>`); continue; }
    closeList();
    para.push(line.trim());
  }
  if (inCode) html += `<pre><code>${esc(code.join('\n'))}</code></pre>`;
  flush(); closeList();
  return html;
}
