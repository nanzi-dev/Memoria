import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  eventEffectLabel,
  summarizeEventEffect,
} from '../src/pages/eventDetailSummary.js';

const eventListSource = await readFile(
  new URL('../src/pages/EventList.jsx', import.meta.url),
  'utf8',
);

test('event effect labels use known Chinese labels and a generic fallback', () => {
  assert.equal(eventEffectLabel('modify_state'), '修改状态');
  assert.equal(eventEffectLabel('unknown_effect'), '其他效果');
  assert.equal(eventEffectLabel(), '其他效果');
  assert.equal(typeof eventListSource, 'string');
});

test('modify state summary reports the number of changed fields', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'modify_state',
    state_changes: { affinity: 2, trust: 1 },
  }), '调整 2 项状态');
});

test('unlock content summary counts configured keys', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'unlock_content',
    unlock_keys: ['chapter_two', 'gallery_entry'],
  }), '解锁 2 项内容');
});

test('trigger dialogue summary does not echo configured dialogue', () => {
  const dialogue = '这段预设对白不应出现在摘要中';
  const summary = summarizeEventEffect({
    effect_type: 'trigger_dialogue',
    dialogue_text: dialogue,
  });

  assert.equal(summary, '播放预设对白');
  assert.equal(summary.includes(dialogue), false);
});

test('change mood summary names the target mood', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'change_mood',
    target_mood: 'relieved',
  }), '情绪变为 relieved');
});

test('branch event summary reports the number of conditions', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'branch_event',
    branch_conditions: [{}, {}, {}],
  }), '按 3 个条件选择分支');
});

test('event progress summary identifies relative changes', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'update_event_progress',
    progress_delta: 2,
  }), '相对调整事件进度');
});

test('unknown effects use a generic execution summary', () => {
  assert.equal(summarizeEventEffect({
    effect_type: 'unknown_effect',
  }), '执行其他事件效果');
});
