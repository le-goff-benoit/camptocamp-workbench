// Small, safe Markdown renderer for release documents, requests and plans.
// Everything is escaped first; only http(s)/mailto links become anchors.
import { escape } from './text.mjs';

const SLOT = '\u0000';
const safeUrl = url => /^(https?:\/\/|mailto:)/i.test(url);
const external = (url, label) => `<a href="${escape(url)}" target="_blank" rel="noreferrer">${label}</a>`;

export function inline(source) {
  const slots = [];
  const keep = html => `${SLOT}${slots.push(html) - 1}${SLOT}`;
  let text = String(source ?? '').replaceAll(SLOT, '');
  text = text.replace(/`([^`\n]+)`/g, (_, code) => keep(`<code>${escape(code)}</code>`));
  text = text.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_, label, url) =>
    keep(safeUrl(url) ? external(url, escape(label)) : `<span class="md-ref" title="${escape(url)}">${escape(label)}</span>`));
  text = text.replace(/\bhttps?:\/\/[^\s<>()"']+[^\s<>()"'.,;:!?]/g, url => keep(external(url, escape(url))));
  text = escape(text)
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[\s(«])\*([^*\n]+)\*(?=[\s).,;:!?»]|$)/g, '$1<em>$2</em>')
    .replace(/(^|[\s(«])_([^_\n]+)_(?=[\s).,;:!?»]|$)/g, '$1<em>$2</em>')
    .replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return text.replace(new RegExp(`${SLOT}(\\d+)${SLOT}`, 'g'), (_, index) => slots[Number(index)]);
}

const ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const cells = row => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());

function listHTML(items) {
  let html = '';
  const stack = [];
  for (const item of items) {
    while (stack.length && item.indent < stack.at(-1).indent) html += `</li></${stack.pop().type}>`;
    const top = stack.at(-1);
    if (!top || item.indent > top.indent) {
      html += `<${item.type}>`;
      stack.push({ indent: item.indent, type: item.type });
    } else {
      html += '</li>';
      if (top.type !== item.type) { html += `</${top.type}><${item.type}>`; top.type = item.type; }
    }
    const task = /^\[([ xX])\]\s+(.*)$/.exec(item.text);
    html += task
      ? `<li class="task${task[1] === ' ' ? '' : ' done'}"><span class="box">${task[1] === ' ' ? '' : '✓'}</span>${inline(task[2])}`
      : `<li>${inline(item.text)}`;
  }
  while (stack.length) html += `</li></${stack.pop().type}>`;
  return html;
}

/** Render Markdown to HTML. `breaks` keeps single newlines (short notes). */
export function markdown(source, { breaks = false } = {}) {
  const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let paragraph = [];
  const flush = () => {
    if (paragraph.length) out.push(`<p>${paragraph.map(inline).join(breaks ? '<br>' : ' ')}</p>`);
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = /^\s*(```|~~~)\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      flush();
      const code = [];
      while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i]);
      out.push(`<pre><code>${escape(code.join('\n'))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (/^\s*<!--.*-->\s*$/.test(line)) { flush(); continue; }
    const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) { flush(); out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); continue; }
    if (/^\s*>/.test(line)) {
      flush();
      const quote = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) quote.push(lines[i].replace(/^\s*>\s?/, ''));
      i--;
      out.push(`<blockquote>${markdown(quote.join('\n'), { breaks })}</blockquote>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && TABLE_SEPARATOR.test(lines[i + 1] ?? '')) {
      flush();
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) rows.push(cells(lines[i]));
      i--;
      out.push(`<table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${head.map((_, k) => `<td>${inline(r[k] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (ITEM.test(line)) {
      flush();
      const items = [];
      for (; i < lines.length; i++) {
        const match = ITEM.exec(lines[i]);
        if (match) {
          items.push({ indent: match[1].replace(/\t/g, '  ').length, type: /\d/.test(match[2]) ? 'ol' : 'ul', text: match[3] });
        } else if (/^\s{2,}\S/.test(lines[i]) && items.length) {
          items.at(-1).text += (breaks ? '\n' : ' ') + lines[i].trim();
        } else break;
      }
      i--;
      out.push(listHTML(items));
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return out.join('\n');
}
