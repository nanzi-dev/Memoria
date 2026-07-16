import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [homeSource, badgeSource] = await Promise.all([
  readFile(new URL('../src/pages/Home.jsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/components/CharacterBadge.jsx', import.meta.url), 'utf8'),
]);

test('home keeps a visible status while the lazy character module resolves', () => {
  const characterGridStart = homeSource.indexOf('{!loading && (');
  const characterGridEnd = homeSource.indexOf(
    '{!loading && user && characters.length === 0',
    characterGridStart,
  );
  const characterGridSource = homeSource.slice(characterGridStart, characterGridEnd);

  assert.match(characterGridSource, /<Suspense fallback=\{<CharacterArchiveLoading/);
  assert.doesNotMatch(characterGridSource, /<Suspense fallback=\{null\}>/);
});

test('character cards show a lightweight preview while the 3D lanyard loads', () => {
  assert.match(badgeSource, /const Lanyard = lazy\(\(\) => import\('\.\/Lanyard'\)\)/);
  assert.match(badgeSource, /function LanyardFallback\(/);
  assert.match(badgeSource, /<Suspense fallback=\{<LanyardFallback/);
  assert.doesNotMatch(badgeSource, /import Lanyard from '\.\/Lanyard'/);
});
