import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [graphSource, settingsSource, archiveCss] = await Promise.all([
  readFile(new URL('../src/pages/RelationshipGraph.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/UserSettingsModal.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/index.css', import.meta.url), 'utf8'),
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
  assert.match(graphSource, /archive-clue-wall/);
  assert.match(graphSource, /关系调查墙/);
  assert.match(archiveCss, /--archive-graph-wall/);
  assert.match(archiveCss, /--archive-graph-paper/);
  assert.match(archiveCss, /--archive-graph-pin/);
  assert.match(archiveCss, /--archive-graph-rope-shadow/);
  assert.match(archiveCss, /\.archive-clue-wall/);
  assert.doesNotMatch(
    graphSource,
    /SideRays|GRAPH_RAYS_PROPS|memoria-page|memoria-app-header|cyber-green|CYBER_GREEN|PLAYER_CYAN|CYBER_SURFACE/,
  );
});

test('relationship graph renders square archive photos connected by pushpins and rope layers', () => {
  assert.match(graphSource, /DESKTOP_NODE/);
  assert.match(graphSource, /imageSize/);
  assert.match(graphSource, /append\('clipPath'\)[\s\S]{0,260}append\('rect'\)/);
  assert.match(graphSource, /photo-mount/);
  assert.match(graphSource, /node-hit-target/);
  assert.match(graphSource, /fill', 'transparent'[\s\S]{0,100}pointer-events', 'all'/);
  assert.match(graphSource, /pushpin/);
  assert.match(graphSource, /pin-head/);
  assert.match(graphSource, /rope-shadow/);
  assert.match(graphSource, /rope-base/);
  assert.match(graphSource, /rope-fiber/);
  assert.match(graphSource, /rope-hit/);
  assert.match(graphSource, /Q\$\{controlX\},\$\{controlY\}/);
  assert.doesNotMatch(graphSource, /marker-end|link-flow|stroke-dashoffset|arrow-/);
});

test('relationship wall keeps mouse, keyboard, drag, zoom, and edit interactions', () => {
  assert.match(graphSource, /d3\.drag\(\)/);
  assert.match(graphSource, /d3\.zoom\(\)/);
  assert.match(graphSource, /\.attr\('tabindex', 0\)/);
  assert.match(graphSource, /\.attr\('role', 'button'\)/);
  assert.match(graphSource, /\.on\('keydown'/);
  assert.match(graphSource, /event\.key !== 'Enter'/);
  assert.match(graphSource, /setEditEdge\((?:d|link)\)/);
  assert.match(graphSource, /characterEditorPath\(d\.character_id\)/);
});

test('relationship wall progressively reveals dense networks without discarding ropes', () => {
  assert.match(graphSource, /FOCUS_LINKS_PER_NODE = 2/);
  assert.match(graphSource, /priorityLinks/);
  assert.match(graphSource, /edgeDensity/);
  assert.match(graphSource, /setEdgeDensity\('priority'\)/);
  assert.match(graphSource, /setEdgeDensity\('all'\)/);
  assert.match(graphSource, />\s*重点\s*</);
  assert.match(graphSource, />\s*全部\s*</);
  assert.match(graphSource, /selectedRelationType/);
  assert.match(graphSource, /DropdownMenuRadioGroup/);
  assert.match(graphSource, /relationship-label/);
  assert.match(graphSource, /getRelationshipLabelText/);
  assert.match(graphSource, /let lockedNode = null/);
  assert.match(graphSource, /toggleNodeLock/);
  assert.match(graphSource, /event\.key === ' '/);
  assert.match(graphSource, /pointer-events', link => isLinkVisible/);
  assert.doesNotMatch(graphSource, /activeRelationType|setActiveRelationType/);
  assert.match(archiveCss, /\.relationship-label/);
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

test('relationship type picker keeps the current type clear and bounds long type lists', () => {
  assert.match(graphSource, /<DropdownMenu\b[^>]*open=/);
  assert.match(graphSource, /<DropdownMenuTrigger asChild>/);
  assert.match(graphSource, /当前关系/);
  assert.match(graphSource, /aria-label="搜索关系类型"/);
  assert.match(graphSource, /max-h-64 overflow-y-auto/);
  assert.match(graphSource, /filteredRelationTypes\.map/);
  assert.match(graphSource, /<Check\b/);
  assert.match(graphSource, /scrollIntoView\(\{ block: 'nearest' \}\)/);
  assert.match(graphSource, /bg-accent\/70 text-accent-foreground/);
  assert.match(graphSource, /没有匹配的关系类型/);
  assert.match(graphSource, /新增关系类型/);
  assert.match(graphSource, /当前类型正在使用，无法删除/);
  assert.doesNotMatch(graphSource, /flex flex-wrap gap-2[\s\S]{0,120}relationTypes\.map/);
});

test('relationship wall filter searches a bounded list and keeps the current filter visible', () => {
  assert.match(graphSource, /function RelationTypeFilter/);
  assert.match(graphSource, /aria-label="搜索关系筛选"/);
  assert.match(
    graphSource,
    /id="relationship-filter-options"[\s\S]{0,120}max-h-64 overflow-y-auto/,
  );
  assert.match(graphSource, /filteredUsedRelationTypes\.map/);
  assert.match(graphSource, /selectedFilterItemRef/);
  assert.match(graphSource, /handleFilterOpenChange\(false\)/);
  assert.match(graphSource, /筛选关系类型，当前为/);
  assert.match(
    graphSource,
    /value=\{RELATION_FILTER_ALL\}[\s\S]{0,1000}id="relationship-filter-options"/,
  );
  assert.doesNotMatch(graphSource, /\{usedRelationTypes\.map/);
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
