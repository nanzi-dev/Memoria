import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const sources = Object.fromEntries(await Promise.all(
  [
    ['button', new URL('../src/components/ui/button.jsx', import.meta.url)],
    ['dropdown', new URL('../src/components/ui/dropdown-menu.jsx', import.meta.url)],
    ['select', new URL('../src/components/ui/select.jsx', import.meta.url)],
    ['tabs', new URL('../src/components/ui/tabs.jsx', import.meta.url)],
    ['shell', new URL('../src/archive/ArchiveShell.jsx', import.meta.url)],
    ['chat', new URL('../src/pages/ChatRoom.jsx', import.meta.url)],
    ['styles', new URL('../src/index.css', import.meta.url)],
  ].map(async ([name, url]) => {
    try {
      return [name, await readFile(url, 'utf8')];
    } catch (error) {
      return [name, { loadError: error }];
    }
  }),
));

test('archive shared controls keep a 44px minimum touch target', () => {
  for (const source of Object.values(sources)) {
    assert.equal(typeof source, 'string');
  }

  assert.match(sources.button, /inline-flex min-h-11 items-center/);
  assert.match(sources.button, /default: 'h-11 px-4 py-2'/);
  assert.match(sources.button, /sm: 'h-11 min-h-11 rounded px-3 text-xs'/);
  assert.doesNotMatch(sources.dropdown, /min-h-10/);
  assert.match(sources.select, /relative flex min-h-11 w-full cursor-default/);
  assert.match(sources.tabs, /inline-flex min-h-11 items-center justify-center whitespace-nowrap/);
});

test('archive navigation and explicit icon controls do not shrink below 44px', () => {
  assert.match(sources.shell, /mobile \? 'min-h-12 px-3' : 'min-h-11 px-3'/);
  assert.doesNotMatch(
    sources.chat,
    /className="h-9 min-h-9 w-9 min-w-9"/,
  );
});

test('archive skip link is at least 44px high when focused', () => {
  assert.match(
    sources.styles,
    /\.archive-skip-link\s*\{[^}]*min-height:\s*44px;/s,
  );
});
