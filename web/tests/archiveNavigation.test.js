import test from 'node:test';
import assert from 'node:assert/strict';

async function loadArchiveNavigation() {
  try {
    return await import('../src/archive/navigation.js');
  } catch (error) {
    return { loadError: error };
  }
}

const navigationModule = await loadArchiveNavigation();

test('archive navigation exposes the five primary destinations in order', () => {
  assert.ifError(navigationModule.loadError);
  assert.deepEqual(
    navigationModule.ARCHIVE_NAV_ITEMS.map(({ label, path }) => ({ label, path })),
    [
      { label: '对话', path: '/chat' },
      { label: '事件', path: '/events' },
      { label: '角色', path: '/persona' },
      { label: '图谱', path: '/graph' },
      { label: '知识', path: '/knowledge' },
    ],
  );
});

test('archive route metadata resolves static page titles', () => {
  assert.ifError(navigationModule.loadError);
  assert.equal(navigationModule.getArchiveRouteMeta('/chat').title, '对话');
  assert.equal(navigationModule.getArchiveRouteMeta('/events').title, '事件');
  assert.equal(navigationModule.getArchiveRouteMeta('/persona').title, '角色');
  assert.equal(navigationModule.getArchiveRouteMeta('/graph').title, '关系图谱');
  assert.equal(navigationModule.getArchiveRouteMeta('/knowledge').title, '知识');
});

test('archive route metadata resolves dynamic editor page titles', () => {
  assert.ifError(navigationModule.loadError);
  assert.equal(navigationModule.getArchiveRouteMeta('/events/event-42').title, '事件详情');
  assert.equal(navigationModule.getArchiveRouteMeta('/editor').title, '角色编辑');
  assert.equal(navigationModule.getArchiveRouteMeta('/editor/character-7').title, '角色编辑');
});

test('archive navigation keeps parent destinations active on nested routes', () => {
  assert.ifError(navigationModule.loadError);
  assert.equal(navigationModule.getActiveArchiveNavPath('/events/event-42'), '/events');
  assert.equal(navigationModule.getActiveArchiveNavPath('/editor/character-7'), '/persona');
  assert.equal(navigationModule.getActiveArchiveNavPath('/knowledge'), '/knowledge');
});

test('archive route focus skips initial mount and runs for real path changes', () => {
  assert.ifError(navigationModule.loadError);
  assert.equal(navigationModule.shouldFocusArchiveMain(null, '/events'), false);
  assert.equal(navigationModule.shouldFocusArchiveMain('/events', '/events/'), false);
  assert.equal(navigationModule.shouldFocusArchiveMain('/events', '/knowledge'), true);
  assert.equal(
    navigationModule.shouldFocusArchiveMain('/events', '/events/event-42'),
    true,
  );
});
