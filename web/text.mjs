export const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const normalized = value => String(value ?? '').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
export const matchesProject = (project, query) => normalized([project.name,project.path,...(project.emails??[]),...(project.domains??[])].join(' ')).includes(normalized(query.trim()));

/** Inline SVG icon from the sprite declared in index.html. */
export const icon = (name, extra = '') => `<svg class="i${extra ? ' ' + extra : ''}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

export const initials = name => {
  const words = String(name ?? '').split(/[\s_.-]+/).filter(Boolean);
  return ((words.length > 1 ? words[0][0] + words[1][0] : String(name ?? '').slice(0, 2)) || '?').toUpperCase();
};

const relative = new Intl.RelativeTimeFormat('fr-CH', { numeric: 'auto' });
/** "il y a 5 min", "hier", or a date when older than a week. */
export function ago(value, now = Date.now()) {
  const at = new Date(value).getTime();
  if (!Number.isFinite(at)) return '';
  const seconds = Math.round((at - now) / 1000), abs = Math.abs(seconds);
  if (abs < 45) return 'à l’instant';
  if (abs < 3600) return relative.format(Math.round(seconds / 60), 'minute');
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), 'hour');
  if (abs < 7 * 86400) return relative.format(Math.round(seconds / 86400), 'day');
  return new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium' }).format(at);
}
