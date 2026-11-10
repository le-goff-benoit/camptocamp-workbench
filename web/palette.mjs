// Ctrl K command palette: jump to any project or page, or run a contextual action.
import { escape, icon, normalized } from './text.mjs';

export function createPalette(getCommands) {
  const dialog = document.querySelector('#palette');
  const field = document.querySelector('#palette-input');
  const list = document.querySelector('#palette-list');
  let items = [], selected = 0;

  function score(command, query) {
    if (!query) return command.rank ?? 1;
    const label = normalized(command.label), haystack = normalized(`${command.label} ${command.hint ?? ''} ${command.keywords ?? ''}`);
    if (label.startsWith(query)) return 4;
    if (label.split(/[\s_/-]+/).some(word => word.startsWith(query))) return 3;
    if (haystack.includes(query)) return 2;
    // Loose subsequence match: "nrl" finds "nouvelle release".
    let at = 0;
    for (const char of query.replace(/\s+/g, '')) { at = label.indexOf(char, at) + 1; if (!at) return 0; }
    return 1;
  }

  function paint() {
    const query = normalized(field.value.trim());
    items = getCommands()
      .map(command => ({ command, score: score(command, query) }))
      .filter(entry => entry.score > 0 && (query || !entry.command.quiet))
      .sort((a, b) => b.score - a.score || (a.command.order ?? 0) - (b.command.order ?? 0))
      .slice(0, 60)
      .map(entry => entry.command);
    if (!query) items.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    selected = Math.min(selected, Math.max(items.length - 1, 0));
    let group = '';
    list.innerHTML = items.length ? items.map((command, index) => {
      const header = !query && command.group !== group ? `<div class="palette-group">${escape(group = command.group)}</div>` : '';
      return `${header}<button type="button" class="palette-item" role="option" id="palette-${index}" data-index="${index}" aria-selected="${index === selected}">${icon(command.icon ?? 'chevron-right')}<span class="label">${escape(command.label)}</span>${command.hint ? `<small>${escape(command.hint)}</small>` : ''}</button>`;
    }).join('') : '<div class="palette-empty">Aucun résultat. Essayez un nom de client, de dépôt ou d’action.</div>';
    field.setAttribute('aria-activedescendant', items.length ? `palette-${selected}` : '');
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }

  async function run(index) {
    const command = items[index];
    if (!command) return;
    dialog.close();
    await command.run();
  }

  field.addEventListener('input', () => { selected = 0; paint(); });
  field.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      selected = (selected + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % Math.max(items.length, 1);
      paint();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      void run(selected);
    }
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-index]');
    if (button) void run(Number(button.dataset.index));
  });
  list.addEventListener('mousemove', event => {
    const button = event.target.closest('[data-index]');
    if (button && Number(button.dataset.index) !== selected) {
      list.querySelector('[aria-selected="true"]')?.setAttribute('aria-selected', 'false');
      selected = Number(button.dataset.index);
      button.setAttribute('aria-selected', 'true');
    }
  });
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

  return {
    open(query = '') {
      if (dialog.open) return;
      field.value = query; selected = 0; paint();
      dialog.showModal(); field.focus();
    },
    get isOpen() { return dialog.open; },
  };
}
