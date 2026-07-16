import test from 'node:test';
import assert from 'node:assert/strict';

async function loadArchiveTheme() {
  try {
    return await import('../src/archive/theme.js');
  } catch (error) {
    return { loadError: error };
  }
}

const themeModule = await loadArchiveTheme();

test('archive theme defaults to dark when no preference is stored', () => {
  assert.ifError(themeModule.loadError);
  assert.equal(themeModule.DEFAULT_ARCHIVE_THEME, 'dark');
  assert.equal(themeModule.resolveArchiveTheme(null), 'dark');
});

test('archive theme accepts persisted dark and light values', () => {
  assert.ifError(themeModule.loadError);
  assert.equal(themeModule.resolveArchiveTheme('dark'), 'dark');
  assert.equal(themeModule.resolveArchiveTheme('light'), 'light');
});

test('archive theme rejects unsupported persisted values', () => {
  assert.ifError(themeModule.loadError);
  assert.equal(themeModule.resolveArchiveTheme('system'), 'dark');
  assert.equal(themeModule.resolveArchiveTheme('sepia'), 'dark');
});

test('archive theme safely handles a localStorage getter that throws', () => {
  assert.ifError(themeModule.loadError);
  const windowLike = {};
  Object.defineProperty(windowLike, 'localStorage', {
    get() {
      throw new DOMException('Storage access denied', 'SecurityError');
    },
  });

  assert.equal(themeModule.safeGetArchiveStorage(windowLike), null);
  assert.equal(
    themeModule.readArchiveTheme(themeModule.safeGetArchiveStorage(windowLike)),
    'dark',
  );
});

test('archive theme defaults to dark when storage reads throw', () => {
  assert.ifError(themeModule.loadError);
  const storage = {
    getItem() {
      throw new DOMException('Storage access denied', 'SecurityError');
    },
  };

  assert.equal(themeModule.readArchiveTheme(storage), 'dark');
});

test('archive theme persists changes under the memoria-theme key', () => {
  assert.ifError(themeModule.loadError);
  const writes = [];
  const storage = {
    setItem(key, value) {
      writes.push([key, value]);
    },
  };

  const persisted = themeModule.persistArchiveTheme(storage, 'light');

  assert.equal(themeModule.THEME_STORAGE_KEY, 'memoria-theme');
  assert.equal(persisted, 'light');
  assert.deepEqual(writes, [['memoria-theme', 'light']]);
});

test('archive theme returns a legal theme when storage writes throw', () => {
  assert.ifError(themeModule.loadError);
  const storage = {
    setItem() {
      throw new DOMException('Storage access denied', 'SecurityError');
    },
  };

  const persisted = themeModule.persistArchiveTheme(storage, 'light');

  assert.equal(persisted, 'light');
  assert.equal(themeModule.ARCHIVE_THEMES.includes(persisted), true);
});
