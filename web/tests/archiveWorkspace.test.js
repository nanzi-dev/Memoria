import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const sources = Object.fromEntries(await Promise.all(
  [
    ['workspace', new URL('../src/archive/ArchiveWorkspace.jsx', import.meta.url)],
    ['events', new URL('../src/pages/EventList.jsx', import.meta.url)],
    ['knowledge', new URL('../src/pages/KnowledgeManager.jsx', import.meta.url)],
  ].map(async ([name, url]) => {
    try {
      return [name, await readFile(url, 'utf8')];
    } catch (error) {
      return [name, { loadError: error }];
    }
  }),
));

test('archive management pages use the shell-native master-detail workspace', () => {
  assert.equal(typeof sources.workspace, 'string', 'ArchiveWorkspace.jsx should exist');

  for (const page of [sources.events, sources.knowledge]) {
    assert.equal(typeof page, 'string');
    assert.match(page, /useArchiveShell/);
    assert.match(page, /<ArchiveWorkspace/);
    assert.doesNotMatch(page, /<main\b|<header\b/);
    assert.doesNotMatch(
      page,
      /cyber-green|zinc-|memoria-page|memoria-app-header|createPortal|#[0-9a-fA-F]{3,8}/,
    );
  }
});
