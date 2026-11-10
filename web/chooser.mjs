// "Which agent?" popover shown whenever a terminal is opened.
import { escape, icon } from './text.mjs';

export const agentLogo = (kind, size = '') => kind === 'codex' || kind === 'claude'
  ? `<svg class="logo${size ? ' ' + size : ''}" aria-hidden="true"><use href="#logo-${kind}"/></svg>`
  : icon('terminal', size);

let current = null;

function close() {
  current?.element.remove();
  current?.anchor?.setAttribute('aria-expanded', 'false');
  current = null;
}

/** Ask Codex / Claude / shell next to `anchor`; resolves with the kind or null. */
export function chooseAgent(anchor, { title = 'Ouvrir un terminal', context = '' } = {}) {
  close();
  return new Promise(resolve => {
    const element = document.createElement('div');
    element.className = 'chooser';
    element.setAttribute('role', 'menu');
    element.setAttribute('aria-label', title);
    element.innerHTML = `<div class="chooser-title">${escape(title)}${context ? `<small>${escape(context)}</small>` : ''}</div>
      <div class="chooser-options">
        <button role="menuitem" data-agent="codex" aria-label="Ouvrir Codex">${agentLogo('codex', 'xl')}<span>Codex</span></button>
        <button role="menuitem" data-agent="claude" aria-label="Ouvrir Claude">${agentLogo('claude', 'xl')}<span>Claude</span></button>
      </div>
      <button role="menuitem" class="chooser-shell" data-agent="shell" aria-label="Shell simple">${icon('terminal', 'sm')}Shell simple</button>`;
    document.body.append(element);
    const finish = value => { if (current?.element === element) close(); resolve(value); };
    current = { element, anchor, finish };
    anchor?.setAttribute('aria-expanded', 'true');

    const rect = anchor?.getBoundingClientRect() ?? { left: innerWidth / 2, right: innerWidth / 2, top: innerHeight / 2, bottom: innerHeight / 2 };
    const box = element.getBoundingClientRect();
    const below = rect.bottom + 8 + box.height < innerHeight;
    element.style.top = `${below ? rect.bottom + 8 : Math.max(8, rect.top - box.height - 8)}px`;
    element.style.left = `${Math.min(Math.max(8, rect.right - box.width), innerWidth - box.width - 8)}px`;

    const items = [...element.querySelectorAll('[data-agent]')];
    items[0].focus();
    element.addEventListener('click', event => {
      const button = event.target.closest('[data-agent]');
      if (button) finish(button.dataset.agent);
    });
    element.addEventListener('keydown', event => {
      const index = items.indexOf(document.activeElement);
      if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) {
        event.preventDefault();
        const step = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
        items[(index + step + items.length) % items.length].focus();
      } else if (event.key === 'Escape') { event.preventDefault(); anchor?.focus(); finish(null); }
      else if (event.key === 'c' || event.key === 'C') finish('claude');
      else if (event.key === 'x' || event.key === 'X') finish('codex');
    });
    setTimeout(() => document.addEventListener('pointerdown', function outside(event) {
      if (!element.contains(event.target)) { document.removeEventListener('pointerdown', outside); finish(null); }
    }), 0);
  });
}
export const chooserOpen = () => !!current;
