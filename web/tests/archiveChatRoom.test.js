import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(
  new URL('../src/pages/ChatRoom.jsx', import.meta.url),
  'utf8',
);

const legacyVisualPattern =
  /ChatBackdrop|SideRays|cyber-green|zinc-|memoria-(?:page|glass|card-hover|avatar-ring)|#[0-9a-fA-F]{3,8}|rounded-(?:xl|2xl)/;

test('ChatRoom uses the ArchiveShell-native three-column narrative workbench', () => {
  assert.match(source, /useArchiveShell/);
  assert.match(source, /setPrimaryAction/);
  assert.match(source, /data-archive-chat-workbench/);
  assert.match(
    source,
    /grid-cols-\[minmax\(220px,280px\)_minmax\(0,1fr\)_minmax\(240px,320px\)\]/,
  );
  assert.match(source, /h-\[calc\(100dvh-4rem\)\]/);
  assert.doesNotMatch(source, /<main\b|<header\b/);
  assert.doesNotMatch(source, legacyVisualPattern);
});

test('assistant messages use script typography while player messages remain compact chat messages', () => {
  assert.match(source, /data-message-layout=\{isUser \? 'chat' : 'script'\}/);
  assert.match(source, /data-archive-script-message/);
  assert.match(source, /data-scene-speaker/);
  assert.match(source, /data-stage-direction/);
  assert.match(source, /font-archive-serif/);
  assert.match(source, /font-archive-mono/);
  assert.match(source, /tabular-nums/);
});

test('ChatRoom keeps request ownership, polling, history compensation, and optimistic message contracts', () => {
  assert.match(source, /createRequestEpoch\(\)/);
  assert.match(source, /beginOwnedRequest\(/);
  assert.match(source, /singleRequestGenerationRef/);
  assert.match(source, /groupRequestGenerationRef/);
  assert.match(source, /activeSendRequestRef/);
  assert.match(source, /window\.setInterval\(syncGroupHistory, GROUP_POLL_INTERVAL_MS\)/);
  assert.match(
    source,
    /container\.scrollTop = pending\.scrollTop \+ \(container\.scrollHeight - pending\.scrollHeight\)/,
  );
  assert.match(source, /createPendingUserMessage\(/);
  assert.match(source, /settlePendingMessage\(/);
  assert.match(source, /removePendingMessage\(/);
  assert.match(source, /restoreFailedDraft\(/);
});

test('new group chat claims request ownership before awaiting the session response', () => {
  const functionStart = source.indexOf('const startGroupChat = async () => {');
  const functionEnd = source.indexOf('// ── Send message ──', functionStart);
  const startGroupChatSource = source.slice(functionStart, functionEnd);

  const ownerCapture = startGroupChatSource.indexOf('const requestPlayerId = PLAYER_ID;');
  const generationCapture = startGroupChatSource.indexOf(
    'const generation = groupRequestGenerationRef.current + 1;',
  );
  const generationClaim = startGroupChatSource.indexOf(
    'groupRequestGenerationRef.current = generation;',
  );
  const requestAwait = startGroupChatSource.indexOf(
    'const res = await multiDialogue.startSession(',
  );

  assert.ok(ownerCapture >= 0, 'group creation must capture the player that owns the request');
  assert.ok(generationCapture >= 0, 'group creation must capture a request generation');
  assert.ok(generationClaim >= 0, 'group creation must claim the request generation');
  assert.ok(requestAwait >= 0, 'group creation must await the session API');
  assert.ok(ownerCapture < requestAwait, 'request owner must be captured before the API wait');
  assert.ok(generationCapture < requestAwait, 'request generation must be captured before the API wait');
  assert.ok(generationClaim < requestAwait, 'request generation must be claimed before the API wait');
  assert.match(
    startGroupChatSource,
    /if \(\s*generation !== groupRequestGenerationRef\.current\s*\|\| playerIdRef\.current !== requestPlayerId\s*\) return;/,
  );
  assert.match(
    startGroupChatSource,
    /catch \(e\) \{\s*if \(\s*generation !== groupRequestGenerationRef\.current\s*\|\| playerIdRef\.current !== requestPlayerId\s*\) return;/,
  );
});

test('ChatRoom keeps session lifecycle and browser speech integration contracts', () => {
  assert.match(source, /dialogue\.startSession\(/);
  assert.match(source, /dialogue\.endSession/);
  assert.match(source, /multiDialogue\.endSession/);
  assert.match(source, /useBrowserSpeech\(/);
  assert.match(source, /startRecording/);
  assert.match(source, /stopRecording/);
  assert.match(source, /cancelRecording/);
  assert.match(source, /toggleAudio/);
  assert.match(source, /retryAudio/);
  assert.match(source, /enqueueAutoplay/);
  assert.match(source, /stopAudio/);
});
