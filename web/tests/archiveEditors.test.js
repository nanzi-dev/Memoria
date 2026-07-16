import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const sourceEntries = [
  ['workspace', '../src/archive/ArchiveEditorWorkspace.jsx'],
  ['persona', '../src/pages/PersonaEditor.jsx'],
  ['character', '../src/pages/CharacterEditor.jsx'],
  ['event', '../src/pages/EventEditor.jsx'],
  ['operations', '../src/components/EventOperationsPanel.jsx'],
  ['identity', '../src/components/editor/StepIdentity.jsx'],
  ['personality', '../src/components/editor/StepPersonality.jsx'],
  ['speech', '../src/components/editor/StepSpeechStyle.jsx'],
  ['background', '../src/components/editor/StepBackground.jsx'],
  ['interaction', '../src/components/editor/StepInteraction.jsx'],
  ['tags', '../src/components/editor/TagInput.jsx'],
];

const sources = Object.fromEntries(await Promise.all(
  sourceEntries.map(async ([name, path]) => {
    try {
      return [name, await readFile(new URL(path, import.meta.url), 'utf8')];
    } catch (error) {
      return [name, { loadError: error }];
    }
  }),
));

const legacyVisualPattern =
  /cyber-green|cyber-surface|cyber-bg|cyber-ink|zinc-|memoria-app-header|memoria-glass|#[0-9a-fA-F]{3,8}/;

test('persona, character, and event editors share the archive editor workspace', () => {
  assert.equal(typeof sources.workspace, 'string', 'ArchiveEditorWorkspace.jsx should exist');
  assert.match(sources.workspace, /grid-cols-\[minmax\(220px,280px\)_minmax\(0,1fr\)_minmax\(240px,320px\)\]/);
  assert.match(sources.workspace, /mobileAction/);

  for (const page of [sources.persona, sources.character, sources.event]) {
    assert.equal(typeof page, 'string');
    assert.match(page, /useArchiveShell/);
    assert.match(page, /<ArchiveEditorWorkspace/);
    assert.match(page, /setPrimaryAction/);
    assert.doesNotMatch(page, /<header\b|<main\b/);
    assert.doesNotMatch(page, legacyVisualPattern);
  }
});

test('editor steps and event operations use archive semantic styling', () => {
  for (const source of [
    sources.identity,
    sources.personality,
    sources.speech,
    sources.background,
    sources.interaction,
    sources.tags,
    sources.operations,
  ]) {
    assert.equal(typeof source, 'string');
    assert.doesNotMatch(source, legacyVisualPattern);
  }
});

test('persona editor keeps loading, avatar, refresh, and save behavior contracts', () => {
  assert.match(sources.persona, /userApi\.getCharacterCard\(\)/);
  assert.match(sources.persona, /userApi\.updateCharacterCard\(payload\)/);
  assert.match(sources.persona, /userApi\.uploadCharacterCardAvatar\(file\)/);
  assert.match(sources.persona, /userApi\.setCharacterCardAvatarUrl\(avatarUrl\.trim\(\)\)/);
  assert.match(sources.persona, /await refresh\(\)/);
  assert.match(sources.persona, /validateCard\(card\)/);
});

test('character editor keeps five-step and lifecycle behavior contracts', () => {
  assert.match(sources.character, /const STEPS = \[/);
  assert.match(sources.character, /characterAdmin\.get\(characterId\)/);
  assert.match(sources.character, /characterAdmin\.update\(characterId, data\)/);
  assert.match(sources.character, /characterAdmin\.create\(data\)/);
  assert.match(sources.character, /characterAdmin\.delete\(characterId, false\)/);
  assert.match(sources.character, /characterAdmin\.activate\(characterId\)/);
  assert.match(sources.character, /characterAdmin\.delete\(characterId, true\)/);
  assert.match(sources.character, /handleImportFile/);
  assert.match(sources.character, /handleExportFile/);
  assert.match(sources.character, /navigationTimeoutRef\.current\.schedule/);
  assert.match(sources.character, /data\.character_id = `npc_/);
});

test('event editor keeps dependency loading, validation, operations, and persistence contracts', () => {
  assert.match(sources.event, /eventAdmin\.templates\(\)/);
  assert.match(sources.event, /characterAdmin\.list\(false\)/);
  assert.match(sources.event, /eventAdmin\.list\(\)/);
  assert.match(sources.event, /eventAdmin\.get\(eventId\)/);
  assert.match(sources.event, /validateEventForm\(form\)/);
  assert.match(sources.event, /sanitizeEventPayload\(form\)/);
  assert.match(sources.event, /eventAdmin\.update\(eventId, payload\)/);
  assert.match(sources.event, /eventAdmin\.create\(payload\)/);
  assert.match(sources.event, /eventAdmin\.delete\(eventId\)/);
  assert.match(sources.event, /<EventOperationsPanel/);
});

test('event editor disables save while unavailable legacy configuration blocks persistence', () => {
  const saveDisabledExpression = sources.event.match(
    /const saveDisabled = ([\s\S]*?);/,
  )?.[1] || '';

  assert.match(saveDisabledExpression, /unavailableConfiguration\.length > 0/);
  assert.match(sources.event, /disabled=\{saveDisabled\}/);
});
