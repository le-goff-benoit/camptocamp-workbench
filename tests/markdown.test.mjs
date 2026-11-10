import test from 'node:test';
import assert from 'node:assert/strict';
import { markdown, inline } from '../web/markdown.mjs';

test('markdown escapes HTML and refuses script links', () => {
  const html = markdown('# Titre <script>alert(1)</script>\n\n[piège](javascript:alert(1)) et <img src=x onerror=alert(1)>');
  assert.ok(!html.includes('<script'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('href="javascript'));
  assert.match(html, /<h1>Titre &lt;script&gt;/);
  assert.match(html, /<span class="md-ref"[^>]*>piège<\/span>/);
});

test('markdown renders release documents: lists, tasks, tables, code and comments', () => {
  const html = markdown(`## Travaux\n\n- premier point\n  - détail\n- [x] contrôle fait\n- [ ] contrôle à faire\n\n1. un\n2. deux\n\n| Critère | État |\n|---|---|\n| Droits | **ok** |\n\n<!-- workbench:plans -->\n\`\`\`py\nprint("<b>")\n\`\`\``);
  assert.match(html, /<h2>Travaux<\/h2>/);
  assert.match(html, /<ul><li>premier point<ul><li>détail<\/li><\/ul><\/li><li class="task done">/);
  assert.match(html, /<li class="task"><span class="box"><\/span>contrôle à faire/);
  assert.match(html, /<ol><li>un<\/li><li>deux<\/li><\/ol>/);
  assert.match(html, /<th>Critère<\/th>.*<td><strong>ok<\/strong><\/td>/s);
  assert.ok(!html.includes('workbench:plans'));
  assert.match(html, /<pre><code>print\(&quot;&lt;b&gt;&quot;\)<\/code><\/pre>/);
});

test('inline formatting keeps code literal and links only http(s)', () => {
  assert.equal(inline('`**pas gras**`'), '<code>**pas gras**</code>');
  assert.match(inline('voir https://example.org/a?b=1&c=2.'), /<a href="https:\/\/example\.org\/a\?b=1&amp;c=2" target="_blank" rel="noreferrer">/);
  assert.match(inline('**gras** et *italique*'), /<strong>gras<\/strong> et <em>italique<\/em>/);
  assert.equal(inline('\u00000\u0000'), '0');
});

test('chat answers keep single line breaks when requested', () => {
  assert.equal(markdown('a\nb', { breaks: true }), '<p>a<br>b</p>');
  assert.equal(markdown('a\nb'), '<p>a b</p>');
});
