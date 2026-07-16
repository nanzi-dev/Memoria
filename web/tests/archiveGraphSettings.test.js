import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [graphSource, settingsSource] = await Promise.all([
  readFile(new URL('../src/pages/RelationshipGraph.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/UserSettingsModal.jsx', import.meta.url), 'utf8'),
]);

test('relationship graph uses the archive clue-wall surface without a legacy page shell', () => {
  assert.match(graphSource, /useArchiveShell/);
  assert.match(graphSource, /setPrimaryAction/);
  assert.match(graphSource, /font-archive-serif/);
  assert.match(graphSource, /font-archive-mono/);
  assert.match(graphSource, /tabular-nums/);
  assert.match(graphSource, /--archive-graph-character/);
  assert.match(graphSource, /--archive-graph-player/);
  assert.match(graphSource, /--archive-graph-surface/);
  assert.doesNotMatch(
    graphSource,
    /SideRays|GRAPH_RAYS_PROPS|memoria-page|memoria-app-header|cyber-green|CYBER_GREEN|PLAYER_CYAN|CYBER_SURFACE/,
  );
});

test('relationship editors delegate focus, escape, and portal behavior to Radix Dialog', () => {
  assert.match(graphSource, /from '@\/components\/ui\/dialog'/);
  assert.match(graphSource, /<Dialog\b[^>]*open=/);
  assert.match(graphSource, /<DialogContent\b/);
  assert.match(graphSource, /<DialogTitle\b/);
  assert.match(graphSource, /<DialogDescription\b/);
  assert.doesNotMatch(graphSource, /createPortal/);
  assert.doesNotMatch(graphSource, /rounded-(?:xl|2xl|3xl|full)/);
});

test('user settings uses archive Radix primitives and preserves the three settings tabs', () => {
  assert.match(settingsSource, /from '@\/components\/ui\/dialog'/);
  assert.match(settingsSource, /from '@\/components\/ui\/tabs'/);
  assert.match(settingsSource, /<Dialog\b[^>]*open/);
  assert.match(settingsSource, /<DialogContent\b/);
  assert.match(settingsSource, /<Tabs\b/);
  assert.match(settingsSource, /value="account"/);
  assert.match(settingsSource, /value="clock"/);
  assert.match(settingsSource, /value="speech"/);
  assert.doesNotMatch(settingsSource, /document\.body\.style\.overflow/);
  assert.doesNotMatch(
    settingsSource,
    /cyber-green|zinc-|cyan-|amber-|bg-black|border-white|#[0-9a-fA-F]{3,8}|rgba\(/,
  );
  assert.doesNotMatch(settingsSource, /rounded-(?:xl|2xl|3xl|full)/);
});

test('world-clock dates, offsets, scales, and counts use archive tabular numerals', () => {
  assert.match(settingsSource, /font-archive-mono/);
  assert.match(settingsSource, /tabular-nums/);

  for (const label of ['与现实偏移', '当前流速', '下一计划事件', '用户 ID']) {
    assert.match(
      settingsSource,
      new RegExp(`${label}[\\s\\S]{0,420}font-archive-mono[\\s\\S]{0,120}tabular-nums`),
      `${label} should be followed by archive mono tabular data`,
    );
  }
});
