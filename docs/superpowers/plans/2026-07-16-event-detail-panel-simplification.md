# Event Detail Panel Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/events` right-hand detail panel shorter and easier to scan without changing the full event editor, event APIs, or management actions.

**Architecture:** Keep event loading and callbacks in `EventList.jsx`. Move effect-label and effect-summary formatting into a small pure JavaScript module so the user-facing summaries can be tested without rendering React. Update `EventDetailPanel` to conditionally render only meaningful metadata and remove generic record dumps.

**Tech Stack:** React 18, Vite, Tailwind CSS, Node.js built-in test runner

---

## File Structure

- Create `web/src/pages/eventDetailSummary.js`: localized effect labels and pure
  one-line effect summary formatting.
- Create `web/tests/eventDetailSummary.test.js`: unit coverage for effect
  summaries plus source-contract coverage for the simplified panel.
- Modify `web/src/pages/EventList.jsx`: consume the effect summary helper and
  conditionally render concise trigger, schedule, effect, and run-record data.

### Task 1: Lock Down Concise Effect Summaries

**Files:**
- Create: `web/tests/eventDetailSummary.test.js`
- Create: `web/src/pages/eventDetailSummary.js`

- [ ] **Step 1: Write the failing effect-summary tests**

Create `web/tests/eventDetailSummary.test.js` with tests that import the
not-yet-created helper:

```javascript
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

test('event effect labels never expose unknown internal effect types', () => {
  assert.equal(eventEffectLabel('modify_state'), '修改状态');
  assert.equal(eventEffectLabel('custom_internal_effect'), '其他效果');
  assert.equal(eventEffectLabel(), '其他效果');
});

test('event effects are summarized without reproducing configured payloads', () => {
  assert.equal(
    summarizeEventEffect({
      effect_type: 'modify_state',
      state_changes: { affection_level: 5, trust_level: 2 },
    }),
    '调整 2 项状态',
  );
  assert.equal(
    summarizeEventEffect({
      effect_type: 'unlock_content',
      unlock_keys: ['chapter_2', 'archive_note'],
    }),
    '解锁 2 项内容',
  );
  assert.equal(
    summarizeEventEffect({
      effect_type: 'trigger_dialogue',
      dialogue_text: '这段完整对白不应出现在详情摘要中',
    }),
    '播放预设对白',
  );
  assert.equal(
    summarizeEventEffect({
      effect_type: 'change_mood',
      target_mood: 'relieved',
    }),
    '情绪变为 relieved',
  );
  assert.equal(
    summarizeEventEffect({
      effect_type: 'branch_event',
      branch_conditions: [{}, {}, {}],
    }),
    '按 3 个条件选择分支',
  );
  assert.equal(
    summarizeEventEffect({
      effect_type: 'update_event_progress',
      progress_delta: 0.2,
    }),
    '相对调整事件进度',
  );
  assert.equal(
    summarizeEventEffect({ effect_type: 'custom_internal_effect', secret: 'hidden' }),
    '执行其他事件效果',
  );
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd web
node --test tests/eventDetailSummary.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for
`src/pages/eventDetailSummary.js`.

- [ ] **Step 3: Implement the pure effect-summary module**

Create `web/src/pages/eventDetailSummary.js`:

```javascript
const EFFECT_LABELS = {
  modify_state: '修改状态',
  unlock_content: '解锁内容',
  trigger_dialogue: '触发对话',
  add_memory: '添加记忆',
  change_mood: '改变情绪',
  notify_player: '通知玩家',
  trigger_event: '触发事件链',
  branch_event: '分支事件',
  npc_proactive_dialogue: 'NPC 主动发言',
  update_event_progress: '更新事件进度',
};

function collectionSize(value) {
  if (Array.isArray(value)) return value.filter(Boolean).length;
  if (value && typeof value === 'object') return Object.keys(value).length;
  return 0;
}

export function eventEffectLabel(effectType) {
  return EFFECT_LABELS[effectType] || '其他效果';
}

export function summarizeEventEffect(effect = {}) {
  switch (effect.effect_type) {
    case 'modify_state': {
      const count = collectionSize(effect.state_changes);
      return count ? `调整 ${count} 项状态` : '调整角色状态';
    }
    case 'unlock_content': {
      const count = collectionSize(effect.unlock_keys);
      return count ? `解锁 ${count} 项内容` : '解锁剧情内容';
    }
    case 'trigger_dialogue':
      return '播放预设对白';
    case 'add_memory':
      return '写入一条长期记忆';
    case 'change_mood':
      return effect.target_mood ? `情绪变为 ${effect.target_mood}` : '调整角色情绪';
    case 'notify_player':
      return '向玩家发送通知';
    case 'trigger_event':
      return '继续触发后续事件';
    case 'branch_event': {
      const count = collectionSize(effect.branch_conditions);
      return count ? `按 ${count} 个条件选择分支` : '按条件选择事件分支';
    }
    case 'npc_proactive_dialogue':
      return '安排 NPC 主动发言';
    case 'update_event_progress':
      return effect.progress_delta != null ? '相对调整事件进度' : '设置事件进度';
    default:
      return '执行其他事件效果';
  }
}
```

- [ ] **Step 4: Run the focused test and verify the helper tests pass**

Run:

```bash
cd web
node --test tests/eventDetailSummary.test.js
```

Expected: PASS for both effect-summary tests.

- [ ] **Step 5: Commit the helper and its tests**

```bash
git add web/src/pages/eventDetailSummary.js web/tests/eventDetailSummary.test.js
git commit -m "test: define concise event effect summaries"
```

### Task 2: Simplify the Event Detail Panel

**Files:**
- Modify: `web/tests/eventDetailSummary.test.js`
- Modify: `web/src/pages/EventList.jsx:77-220`
- Modify: `web/src/pages/EventList.jsx:478-497`
- Modify: `web/src/pages/EventList.jsx:717-930`

- [ ] **Step 1: Add failing panel source-contract tests**

Append these tests to `web/tests/eventDetailSummary.test.js`:

```javascript
test('event detail panel omits raw configuration and empty placeholders', () => {
  assert.doesNotMatch(eventListSource, /function ArchiveValue/);
  assert.doesNotMatch(eventListSource, /function RecordFields/);
  assert.doesNotMatch(eventListSource, /触发类型字段|条件字段|计划表达式|世界时区|时间倍率/);
  assert.doesNotMatch(eventListSource, /<RecordFields\b/);
  assert.match(eventListSource, /event\.exclusive_group &&/);
  assert.match(eventListSource, /event\.stop_processing &&/);
  assert.match(eventListSource, /Number\(event\.missed_count\) > 0/);
  assert.match(eventListSource, /event\.template_id &&/);
});

test('event detail panel keeps concise summaries and management actions', () => {
  assert.match(eventListSource, /line-clamp-2/);
  assert.match(eventListSource, /eventEffectLabel\(effect\.effect_type\)/);
  assert.match(eventListSource, /summarizeEventEffect\(effect\)/);
  assert.match(eventListSource, /onClick=\{onEdit\}/);
  assert.match(eventListSource, /onClick=\{onToggle\}/);
  assert.match(eventListSource, /onClick=\{onDelete\}/);
  assert.match(eventListSource, /停用事件/);
  assert.match(eventListSource, /onClick=\{onRefresh\}/);
  assert.match(eventListSource, /这里只显示事件摘要/);
});
```

- [ ] **Step 2: Run the focused test and verify the panel tests fail**

Run:

```bash
cd web
node --test tests/eventDetailSummary.test.js
```

Expected: FAIL because `EventList.jsx` still defines `ArchiveValue` and
`RecordFields`, renders technical labels, and does not call the summary
helpers.

- [ ] **Step 3: Replace local effect labels and raw record helpers**

In `web/src/pages/EventList.jsx`, import the pure summary functions:

```javascript
import {
  eventEffectLabel,
  summarizeEventEffect,
} from './eventDetailSummary';
```

Delete the local `EFFECT_LABELS` constant and the `ArchiveValue` and
`RecordFields` functions. Keep `DetailItem`, because the simplified panel still
uses the established label/value styling.

For time-based triggers, change `describeTrigger` so it does not expose the raw
schedule expression:

```javascript
if (type === 'time_based') return '按预定时间触发';
```

- [ ] **Step 4: Simplify trigger and schedule rendering**

In `EventDetailPanel`, limit the natural-language trigger summary and render
only meaningful trigger metadata:

```jsx
const hasScheduleDetails = Boolean(
  event?.next_run_at
  || event?.next_due_real_at
  || Number(worldClock?.time_scale) === 0
  || Number(event?.missed_count) > 0,
);
const hasRunRecords = Boolean(
  event?.last_triggered_at
  || event?.updated_at
  || event?.template_id
  || event?.created_at,
);

<p className="mb-4 line-clamp-2 text-sm leading-7 text-foreground">
  {describeTrigger(event.trigger_condition, event.trigger_type)}
</p>
<dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
  <DetailItem label="绑定角色" value={event.character_id || '全局事件'} mono />
  {event.exclusive_group && (
    <DetailItem label="独占分组" value={event.exclusive_group} mono />
  )}
  {event.stop_processing && (
    <DetailItem label="命中后处理" value="停止后续事件匹配" />
  )}
</dl>
```

Replace the schedule details with conditional rows:

```jsx
<dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
  {event.next_run_at && (
    <DetailItem
      label="世界时间触发"
      value={formatScheduleTime(event.next_run_at)}
      mono
    />
  )}
  {(event.next_due_real_at || Number(worldClock?.time_scale) === 0) && (
    <DetailItem
      label="现实预计时间"
      value={event.next_due_real_at
        ? formatScheduleTime(event.next_due_real_at)
        : '世界时间已暂停'}
      mono
    />
  )}
  {Number(event.missed_count) > 0 && (
    <DetailItem label="合并漏触发" value={`${Number(event.missed_count)} 次`} mono />
  )}
</dl>
```

If all schedule values are absent and world time is not paused, render one
neutral sentence instead of empty rows:

```jsx
{!hasScheduleDetails && (
  <p className="text-sm text-muted-foreground">暂无可用排期。</p>
)}
```

- [ ] **Step 5: Replace raw effect payloads with one-line summaries**

Keep the existing numbered effect list, but replace each raw type and
`RecordFields` block with:

```jsx
<div className="min-w-0 flex-1">
  <h4 className="font-archive-serif text-base font-semibold text-foreground">
    {eventEffectLabel(effect.effect_type)}
  </h4>
  <p className="mt-1 text-sm leading-6 text-muted-foreground">
    {summarizeEventEffect(effect)}
  </p>
</div>
```

Use `effect-${index}` as the React key fallback without showing
`effect.effect_type` to the user.

- [ ] **Step 6: Hide missing run-record metadata and update empty copy**

Render run-record rows only when their source value exists:

```jsx
<dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
  {event.last_triggered_at && (
    <DetailItem label="最后触发" value={formatDateTime(event.last_triggered_at)} mono />
  )}
  {event.updated_at && (
    <DetailItem label="最后更新" value={formatDateTime(event.updated_at)} mono />
  )}
  {event.template_id && (
    <DetailItem label="模板" value={event.template_id} mono />
  )}
  {event.created_at && (
    <DetailItem label="创建时间" value={formatDateTime(event.created_at)} mono />
  )}
</dl>
```

If no run-record source values exist, render:

```jsx
{!hasRunRecords && (
  <p className="text-sm text-muted-foreground">暂无运行记录。</p>
)}
```

Change the unselected-panel description to:

```jsx
description="从目录中选择事件后，这里只显示事件摘要；完整配置请进入编辑页查看。"
```

- [ ] **Step 7: Run focused tests and verify they pass**

Run:

```bash
cd web
node --test tests/eventDetailSummary.test.js
```

Expected: all tests in `eventDetailSummary.test.js` PASS.

- [ ] **Step 8: Commit the panel simplification**

```bash
git add web/src/pages/EventList.jsx web/tests/eventDetailSummary.test.js
git commit -m "feat: simplify event detail preview"
```

### Task 3: Verify the Frontend and Inspect the Result

**Files:**
- Verify: `web/src/pages/EventList.jsx`
- Verify: `web/src/pages/eventDetailSummary.js`
- Verify: `web/tests/eventDetailSummary.test.js`

- [ ] **Step 1: Run the full frontend test suite**

Run:

```bash
cd web
npm test
```

Expected: all Node test files PASS with no failures.

- [ ] **Step 2: Run the production build**

Run:

```bash
cd web
npm run build
```

Expected: Vite exits with code 0 and writes the production bundle to
`web/dist`.

- [ ] **Step 3: Start the local frontend server**

Run:

```bash
cd web
npm run dev -- --host 127.0.0.1
```

Expected: Vite reports an available local URL. If port `5173` is occupied, use
the next available Vite port and record it.

- [ ] **Step 4: Inspect `/events` at desktop and mobile widths**

Log in with the locally configured test account, open `/events`, select a
normal event and a time-based event, and verify:

- The panel has no raw field table, JSON block, raw effect type, or unset row.
- Trigger text is limited to two lines.
- Optional schedule and run-record rows collapse without leaving blank gaps.
- Effect entries show a Chinese title and one short summary.
- Edit, enable/disable, delete, and refresh controls remain visible and aligned.
- No text overlaps at desktop and mobile widths.

- [ ] **Step 5: Check the final diff**

Run:

```bash
git status --short
git diff --check
git log -3 --oneline
```

Expected: no whitespace errors; only intended files are changed or committed.
