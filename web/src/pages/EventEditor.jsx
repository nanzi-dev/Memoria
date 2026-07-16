import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Save,
  Loader2,
  Plus,
  Trash2,
  Zap,
  ChevronDown,
  ChevronUp,
  X,
  AlertCircle,
  AlertTriangle,
  Wand2,
  Workflow,
  Sparkles,
  Activity,
  Settings2,
  ChevronRight,
} from 'lucide-react';
import ArchiveEditorWorkspace from '@/archive/ArchiveEditorWorkspace';
import { useArchiveShell } from '@/archive/ArchiveShell';
import { Button } from '@/components/ui/button';
import { characterAdmin, eventAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import EventOperationsPanel from '../components/EventOperationsPanel';
import { createTimeoutController } from '../utils/timeoutController';

const TRIGGER_TYPES = [
  { value: 'affinity_threshold', label: '好感度阈值' },
  { value: 'trust_threshold', label: '信任度阈值' },
  { value: 'keyword_match', label: '关键词匹配' },
  { value: 'npc_keyword_match', label: 'NPC 回复关键词' },
  { value: 'dialogue_count', label: '对话次数' },
  { value: 'time_based', label: '时间条件' },
  { value: 'mood_match', label: '情绪匹配' },
  { value: 'state_delta', label: '状态变化量' },
  { value: 'event_history', label: '事件历史' },
  { value: 'world_time_window', label: '世界时间窗口' },
  { value: 'composite', label: '复合条件' },
];

const COMPARISONS = [
  { value: 'gte', label: '≥ 大于等于' },
  { value: 'lte', label: '≤ 小于等于' },
  { value: 'gt', label: '> 大于' },
  { value: 'lt', label: '< 小于' },
  { value: 'eq', label: '= 等于' },
];

const EFFECT_TYPES = [
  { value: 'modify_state', label: '修改状态' },
  { value: 'unlock_content', label: '解锁内容' },
  { value: 'trigger_dialogue', label: '触发对话' },
  { value: 'add_memory', label: '添加记忆' },
  { value: 'change_mood', label: '改变情绪' },
  { value: 'notify_player', label: '通知玩家' },
  { value: 'trigger_event', label: '触发事件链' },
  { value: 'branch_event', label: '分支事件' },
  { value: 'npc_proactive_dialogue', label: 'NPC 主动发言' },
  { value: 'update_event_progress', label: '更新事件进度' },
];
const EFFECT_LABELS = Object.fromEntries(EFFECT_TYPES.map(et => [et.value, et.label]));

const UNAVAILABLE_TRIGGER_TYPES = new Set([
  'item_acquired',
  'quest_completed',
  'relationship_change',
]);
const UNAVAILABLE_EFFECT_TYPES = new Set([
  'grant_item',
  'start_quest',
  'modify_relationship',
]);
const MATCH_MODES = [
  { value: 'any', label: '任一匹配' },
  { value: 'all', label: '全部匹配' },
  { value: 'exact', label: '全文精确' },
  { value: 'whole_word', label: '完整词匹配' },
  { value: 'regex', label: '正则表达式' },
];
const EVENT_STATUSES = ['succeeded', 'failed', 'partial', 'skipped'];
const PROGRESS_STATUSES = ['pending', 'active', 'completed', 'failed'];
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

const MOODS = ['happy', 'sad', 'angry', 'fearful', 'surprised', 'disgusted', 'neutral', 'excited', 'nervous', 'calm'];

const DEFAULT_EFFECT = {
  effect_type: 'modify_state',
  state_changes: {},
  unlock_keys: [],
  dialogue_text: '',
  dialogue_action: '',
  memory_text: '',
  memory_importance: 5,
  target_mood: 'neutral',
  notification_message: '',
  notification_type: 'info',
  item_id: '',
  quest_id: '',
  target_character_id: '',
  relationship_change: {},
  next_event_id: '',
  branch_conditions: [],
  target_session_id: '',
  proactive_character_id: '',
  proactive_prompt: '',
  progress: null,
  progress_delta: null,
  event_status: '',
};

const DEFAULT_SUB_CONDITION = {
  trigger_type: 'keyword_match',
  threshold: null,
  comparison: 'gte',
  keywords: [],
  match_mode: 'any',
  crossing: false,
  state_field: 'affinity',
  event_id: '',
  event_status: 'succeeded',
  min_occurrences: 1,
  time_window_start: '',
  time_window_end: '',
  weekdays: [],
  cooldown_hours: 0,
};

const DEFAULT_BRANCH_CONDITION = {
  event_id: '',
  condition: { ...DEFAULT_SUB_CONDITION },
};

const cloneJson = value => JSON.parse(JSON.stringify(value ?? null));

const DEFAULT_FORM = {
  event_id: '',
  event_name: '',
  description: '',
  character_id: '',
  trigger_condition: { trigger_type: 'keyword_match', keywords: [], match_mode: 'any', cooldown_hours: 0 },
  effects: [],
  priority: 0,
  exclusive_group: '',
  max_triggers_per_turn: 3,
  stop_processing: false,
  is_active: true,
  schedule: '',
  template_id: '',
};

function cloneDefaultForm() {
  return {
    ...DEFAULT_FORM,
    trigger_condition: { ...DEFAULT_FORM.trigger_condition },
    effects: [],
  };
}

function sanitizeOptionalString(value) {
  const trimmed = String(value || '').trim();
  return trimmed || null;
}

function sanitizeEffect(effect) {
  const { branch_conditions_text, ...rest } = effect;
  const cleaned = { ...rest, effect_type: rest.effect_type || 'modify_state' };

  for (const key of [
    'dialogue_text',
    'dialogue_action',
    'memory_text',
    'notification_message',
    'item_id',
    'quest_id',
    'target_character_id',
    'next_event_id',
    'target_session_id',
    'proactive_character_id',
    'proactive_prompt',
    'event_status',
  ]) {
    if (key in cleaned) cleaned[key] = sanitizeOptionalString(cleaned[key]);
  }

  if (cleaned.effect_type === 'branch_event' && branch_conditions_text) {
    try {
      cleaned.branch_conditions = JSON.parse(branch_conditions_text);
    } catch (err) {
      cleaned.branch_conditions = cleaned.branch_conditions || [];
    }
  }
  if (Array.isArray(cleaned.branch_conditions)) {
    cleaned.branch_conditions = cleaned.branch_conditions.map(branch => ({
      ...branch,
      event_id: sanitizeOptionalString(branch?.event_id),
      condition: sanitizeCondition(branch?.condition),
    }));
  }

  return cleaned;
}

function sanitizeCondition(condition) {
  const cleaned = cloneJson(condition || DEFAULT_FORM.trigger_condition);
  for (const key of [
    'schedule',
    'mood',
    'state_field',
    'event_id',
    'event_status',
    'time_window_start',
    'time_window_end',
  ]) {
    if (key in cleaned) cleaned[key] = sanitizeOptionalString(cleaned[key]);
  }
  if (Array.isArray(cleaned.sub_conditions)) {
    cleaned.sub_conditions = cleaned.sub_conditions.map(sanitizeCondition);
  }
  if (Array.isArray(cleaned.weekdays) && cleaned.weekdays.length === 0) {
    cleaned.weekdays = null;
  }
  return cleaned;
}

function sanitizeEventPayload(form) {
  return {
    ...form,
    event_id: String(form.event_id || '').trim(),
    event_name: String(form.event_name || '').trim(),
    description: String(form.description || '').trim(),
    character_id: sanitizeOptionalString(form.character_id),
    priority: Number(form.priority) || 0,
    exclusive_group: sanitizeOptionalString(form.exclusive_group),
    max_triggers_per_turn: Math.max(1, Math.min(20, Number(form.max_triggers_per_turn) || 3)),
    stop_processing: Boolean(form.stop_processing),
    schedule: sanitizeOptionalString(form.schedule),
    trigger_condition: sanitizeCondition(form.trigger_condition),
    effects: (form.effects || []).map(sanitizeEffect),
  };
}

function collectUnavailableConfiguration(condition, effects, messages = []) {
  if (UNAVAILABLE_TRIGGER_TYPES.has(condition?.trigger_type)) {
    messages.push(`触发类型 ${condition.trigger_type} 尚未实现`);
  }
  for (const child of condition?.sub_conditions || []) {
    collectUnavailableConfiguration(child, [], messages);
  }
  for (const effect of effects || []) {
    if (UNAVAILABLE_EFFECT_TYPES.has(effect.effect_type)) {
      messages.push(`效果类型 ${effect.effect_type} 尚未实现`);
    }
  }
  return messages;
}

function validateEventForm(form) {
  const errors = [];
  const warnings = [];
  const condition = form.trigger_condition || {};

  if (!String(form.event_id || '').trim()) errors.push('事件 ID 必填');
  if (!String(form.event_name || '').trim()) errors.push('事件名称必填');
  if (form.schedule?.trim() && !form.character_id?.trim()) {
    errors.push('定时事件必须绑定角色 ID');
  }

  function validateCondition(current, label = '触发条件') {
    const triggerType = current?.trigger_type;
    if (UNAVAILABLE_TRIGGER_TYPES.has(triggerType)) {
      errors.push(`${label}使用未实现类型 ${triggerType}，请更换后保存`);
    }
    if (
      (triggerType === 'keyword_match' || triggerType === 'npc_keyword_match')
      && !(current.keywords || []).some(keyword => String(keyword || '').trim())
    ) {
      errors.push(`${label}需要至少 1 个关键词`);
    }
    if (
      ['affinity_threshold', 'trust_threshold', 'state_delta'].includes(triggerType)
      && current.threshold == null
    ) {
      errors.push(`${label}需要填写阈值`);
    }
    if (triggerType === 'state_delta' && !['affinity', 'trust'].includes(current.state_field)) {
      errors.push(`${label}需要选择好感度或信任度变化量`);
    }
    if (triggerType === 'dialogue_count' && current.count == null) {
      errors.push(`${label}需要填写对话次数`);
    }
    if (triggerType === 'time_based' && current.duration_minutes == null && !current.schedule?.trim()) {
      errors.push(`${label}需要填写分钟数或 Cron 表达式`);
    }
    if (triggerType === 'mood_match' && !current.mood) {
      errors.push(`${label}需要选择情绪`);
    }
    if (triggerType === 'event_history' && !current.event_id) {
      errors.push(`${label}需要选择依赖事件`);
    }
    if (triggerType === 'event_history' && Number(current.min_occurrences) < 1) {
      errors.push(`${label}的最少执行次数必须大于 0`);
    }
    if (
      triggerType === 'world_time_window'
      && (!current.time_window_start || !current.time_window_end)
    ) {
      errors.push(`${label}需要填写开始和结束时间`);
    }
    if (triggerType === 'composite') {
      if (!(current.sub_conditions || []).length) {
        errors.push(`${label}需要至少 1 个子条件`);
      }
      (current.sub_conditions || []).forEach((child, index) => {
        validateCondition(child, `${label} #${index + 1}`);
      });
    }
  }

  validateCondition(condition);

  (form.effects || []).forEach((effect, index) => {
    const label = `效果 #${index + 1}`;
    if (UNAVAILABLE_EFFECT_TYPES.has(effect.effect_type)) {
      errors.push(`${label} 使用未实现类型 ${effect.effect_type}，请更换后保存`);
    }
    if (effect.effect_type === 'modify_state' && !Object.keys(effect.state_changes || {}).length) {
      errors.push(`${label} 需要至少 1 个状态变化`);
    }
    if (effect.effect_type === 'modify_state') {
      const unknownFields = Object.keys(effect.state_changes || {}).filter(
        key => !['affection_level', 'trust_level', 'current_mood'].includes(key)
      );
      if (unknownFields.length) {
        errors.push(`${label} 包含不支持的状态字段: ${unknownFields.join(', ')}`);
      }
    }
    if (effect.effect_type === 'unlock_content' && !(effect.unlock_keys || []).length) {
      errors.push(`${label} 需要至少 1 个解锁标识`);
    }
    if (effect.effect_type === 'trigger_dialogue' && !String(effect.dialogue_text || '').trim()) {
      errors.push(`${label} 需要填写对话内容`);
    }
    if (effect.effect_type === 'add_memory' && !String(effect.memory_text || '').trim()) {
      errors.push(`${label} 需要填写记忆内容`);
    }
    if (effect.effect_type === 'change_mood' && !effect.target_mood) {
      errors.push(`${label} 需要选择目标情绪`);
    }
    if (effect.effect_type === 'notify_player' && !String(effect.notification_message || '').trim()) {
      errors.push(`${label} 需要填写通知消息`);
    }
    if (effect.effect_type === 'trigger_event' && !String(effect.next_event_id || '').trim()) {
      errors.push(`${label} 需要选择后续事件`);
    }
    if (effect.effect_type === 'branch_event' && !(effect.branch_conditions || []).length) {
      errors.push(`${label} 需要至少 1 个分支`);
    }
    if (effect.effect_type === 'branch_event') {
      (effect.branch_conditions || []).forEach((branch, branchIndex) => {
        if (!branch.event_id || !branch.condition) {
          errors.push(`${label} 的分支 #${branchIndex + 1} 配置不完整`);
        } else {
          validateCondition(branch.condition, `${label} 的分支 #${branchIndex + 1}`);
        }
      });
    }
    if (effect.effect_type === 'npc_proactive_dialogue' && !String(effect.proactive_prompt || '').trim()) {
      errors.push(`${label} 需要填写主动发言提示`);
    }
    if (
      effect.effect_type === 'update_event_progress'
      && effect.progress == null
      && effect.progress_delta == null
      && !effect.event_status
    ) {
      errors.push(`${label} 需要设置进度、进度变化量或状态`);
    }
    if (
      effect.effect_type === 'update_event_progress'
      && effect.progress != null
      && (Number(effect.progress) < 0 || Number(effect.progress) > 1)
    ) {
      errors.push(`${label} 的直接进度必须位于 0 到 1`);
    }
  });

  if (!form.effects?.length) warnings.push('当前事件没有效果，触发后不会产生动作');
  if (!form.description?.trim()) warnings.push('建议补充描述，便于后续维护');

  return { errors, warnings };
}


// ─── Pipeline Preview ────────────────────────────────────────────────────
function PipelinePreview({ triggerCondition, effects }) {
  const t = triggerCondition?.trigger_type || 'keyword_match';
  const tcLabel = TRIGGER_TYPES.find(tt => tt.value === t)?.label || t;

  return (
    <div className="flex items-center gap-2 text-[10px] font-archive-mono flex-wrap">
      <div className="flex items-center gap-1.5 rounded-md border border-border bg-muted/35 px-2.5 py-1">
        <Zap size={12} className="text-muted-foreground" />
        <span className="text-foreground">{tcLabel}</span>
      </div>
      <ArrowLeft size={12} className="rotate-180 text-muted-foreground" />

      {t === 'composite' && (
        <span className="text-muted-foreground">
          {(triggerCondition?.sub_conditions || []).length} 子条件
          {' '}{triggerCondition?.logic_operator === 'or' ? 'OR' : 'AND'}
        </span>
      )}
      {t === 'keyword_match' && (
        <span className="text-muted-foreground">
          {(triggerCondition?.keywords || []).length} 关键词
        </span>
      )}
      {(t === 'affinity_threshold' || t === 'trust_threshold') && (
        <span className="text-muted-foreground">
          {triggerCondition?.comparison || 'gte'} {triggerCondition?.threshold ?? '?'}
        </span>
      )}
      {t === 'dialogue_count' && (
        <span className="text-muted-foreground">
          {triggerCondition?.comparison || 'gte'} {triggerCondition?.count ?? '?'}
        </span>
      )}

      {effects.length > 0 && <ArrowLeft size={12} className="rotate-180 text-muted-foreground" />}
      {effects.map((eff, i) => (
        <span key={i} className="rounded-md border border-border bg-muted/25 px-2.5 py-1 text-muted-foreground">
          {EFFECT_LABELS[eff.effect_type] || eff.effect_type}
        </span>
      ))}
    </div>
  );
}

function EventDependencySelect({ value, onChange, eventOptions, placeholder, allowEmpty = true }) {
  const normalizedValue = value || '';
  const valueIsMissing = normalizedValue && !eventOptions.some(event => event.event_id === normalizedValue);

  return (
    <select
      value={normalizedValue}
      onChange={event => onChange(event.target.value)}
      className="min-h-11 w-full min-w-0 rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
    >
      {allowEmpty && <option value="">{placeholder || '选择事件'}</option>}
      {valueIsMissing && (
        <option value={normalizedValue}>[{normalizedValue} - 当前不可选]</option>
      )}
      {eventOptions.map(event => (
        <option key={event.event_id} value={event.event_id}>
          {event.event_name ? `${event.event_name} (${event.event_id})` : event.event_id}
        </option>
      ))}
    </select>
  );
}

function SubConditionEditor({ condition, onChange, onDelete, eventOptions, depth = 0 }) {
  return (
    <div className="rounded border-l-2 border-border pl-3 sm:ml-4 sm:pl-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-archive-mono text-muted-foreground">子条件</span>
        <button
          type="button"
          onClick={onDelete}
          aria-label="删除子条件"
          title="删除子条件"
          className="inline-flex h-11 w-11 items-center justify-center text-muted-foreground transition-colors hover:text-destructive"
        >
          <Trash2 size={10} />
        </button>
      </div>
      <TriggerConditionForm
        condition={condition}
        onChange={onChange}
        eventOptions={eventOptions}
        isSub={true}
        depth={depth + 1}
      />
    </div>
  );
}

function TriggerConditionForm({ condition, onChange, eventOptions = [], isSub = false, depth = 0 }) {
  const update = (k, v) => onChange({ ...condition, [k]: v });
  const t = condition?.trigger_type || 'keyword_match';
  const unavailable = UNAVAILABLE_TRIGGER_TYPES.has(t);
  const thresholdType = ['affinity_threshold', 'trust_threshold', 'state_delta'].includes(t);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={t}
          onChange={e => onChange({ ...DEFAULT_SUB_CONDITION, trigger_type: e.target.value })}
          className="min-h-11 max-w-full rounded border border-primary/35 bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
        >
          {unavailable && <option value={t}>{t}（未实现）</option>}
          {TRIGGER_TYPES.filter(tt => isSub ? tt.value !== 'composite' : true).map(tt => (
            <option key={tt.value} value={tt.value}>{tt.label}</option>
          ))}
        </select>
      </div>

      {unavailable && (
        <div className="flex items-start gap-2 rounded border border-border bg-muted/35 p-3 text-[10px] font-archive-mono text-muted-foreground">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          该旧触发类型尚未实现，原配置已保留。请切换到可用类型后再保存。
        </div>
      )}

      {thresholdType && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,180px)_minmax(0,140px)]">
          <select
            value={condition.comparison || 'gte'}
            onChange={e => update('comparison', e.target.value)}
            className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-foreground"
          >
            {COMPARISONS.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <input
            type="number"
            value={condition.threshold ?? ''}
            onChange={e => update('threshold', e.target.value === '' ? null : Number(e.target.value))}
            placeholder="数值"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
        </div>
      )}

      {(t === 'affinity_threshold' || t === 'trust_threshold') && (
        <label className="flex min-h-11 items-center gap-2 text-[10px] font-archive-mono text-muted-foreground">
          <input
            type="checkbox"
            checked={Boolean(condition.crossing)}
            onChange={e => update('crossing', e.target.checked)}
            className="accent-primary"
          />
          仅在本轮首次跨过阈值时触发
        </label>
      )}

      {t === 'state_delta' && (
        <label className="block text-[10px] font-archive-mono text-muted-foreground">
          <span className="mb-1 block">变化字段</span>
          <select
            value={condition.state_field || 'affinity'}
            onChange={e => update('state_field', e.target.value)}
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary sm:max-w-xs"
          >
            <option value="affinity">好感度变化量</option>
            <option value="trust">信任度变化量</option>
          </select>
        </label>
      )}

      {t === 'dialogue_count' && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,180px)_minmax(0,140px)]">
          <select
            value={condition.comparison || 'gte'}
            onChange={e => update('comparison', e.target.value)}
            className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-foreground"
          >
            {COMPARISONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <input
            type="number"
            min="0"
            value={condition.count ?? ''}
            onChange={e => update('count', e.target.value === '' ? null : Number(e.target.value))}
            placeholder="历史总轮数"
            className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
        </div>
      )}

      {t === 'time_based' && (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">会话时长（分钟）</span>
              <input
                type="number"
                min="0"
                value={condition.duration_minutes ?? ''}
                onChange={e => update('duration_minutes', e.target.value === '' ? null : Number(e.target.value))}
                className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
              />
            </label>
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">Cron（5 字段，可替代时长）</span>
              <input
                type="text"
                value={condition.schedule || ''}
                onChange={e => update('schedule', e.target.value)}
                placeholder="0 9 * * *"
                className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
              />
            </label>
          </div>
          <label className="block text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">补偿重放上限</span>
            <input
              type="number"
              min="1"
              max="100"
              value={condition.catch_up_replay_limit ?? 1}
              onChange={event => update('catch_up_replay_limit', Math.min(100, Math.max(1, Number(event.target.value) || 1)))}
              className="min-h-11 w-28 rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
            />
          </label>
        </div>
      )}

      {(t === 'keyword_match' || t === 'npc_keyword_match') && (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <select
              value={condition.match_mode || 'any'}
              onChange={e => update('match_mode', e.target.value)}
              className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-foreground"
            >
              {MATCH_MODES.map(mode => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </div>
          <TagInput
            tags={condition.keywords || []}
            onChange={v => update('keywords', v)}
            placeholder={condition.match_mode === 'regex' ? '输入正则表达式并按 Enter' : '输入关键词并按 Enter'}
          />
        </div>
      )}

      {t === 'mood_match' && (
        <select
          value={condition.mood || 'neutral'}
          onChange={e => update('mood', e.target.value)}
          className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary sm:max-w-xs"
        >
          {MOODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      )}

      {t === 'event_history' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="min-w-0 text-[10px] font-archive-mono text-muted-foreground sm:col-span-3">
            <span className="mb-1 block">依赖事件</span>
            <EventDependencySelect
              value={condition.event_id}
              onChange={value => update('event_id', value)}
              eventOptions={eventOptions}
              placeholder="选择依赖事件"
            />
          </label>
          <label className="text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">执行状态</span>
            <select
              value={condition.event_status || 'succeeded'}
              onChange={e => update('event_status', e.target.value)}
              className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary"
            >
              {EVENT_STATUSES.map(status => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
          <label className="text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">最少执行次数</span>
            <input
              type="number"
              min="1"
              value={condition.min_occurrences ?? 1}
              onChange={e => update('min_occurrences', Math.max(1, Number(e.target.value) || 1))}
              className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
            />
          </label>
        </div>
      )}

      {t === 'world_time_window' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">开始时间</span>
              <input
                type="time"
                value={condition.time_window_start || ''}
                onChange={e => update('time_window_start', e.target.value)}
                className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary"
              />
            </label>
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">结束时间</span>
              <input
                type="time"
                value={condition.time_window_end || ''}
                onChange={e => update('time_window_end', e.target.value)}
                className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary"
              />
            </label>
          </div>
          <div>
            <p className="mb-1 text-[10px] font-archive-mono text-muted-foreground">星期（不选表示每天）</p>
            <div className="flex flex-wrap gap-1.5">
              {WEEKDAYS.map((label, day) => {
                const selected = (condition.weekdays || []).includes(day);
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      const weekdays = selected
                        ? (condition.weekdays || []).filter(value => value !== day)
                        : [...(condition.weekdays || []), day].sort();
                      update('weekdays', weekdays);
                    }}
                    className={`h-11 w-11 rounded border text-[10px] font-archive-mono transition-colors ${
                      selected
                        ? 'border-primary/40 bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[10px] font-archive-mono text-muted-foreground">冷却时间</label>
        <input
          type="number"
          min="0"
          value={condition.cooldown_hours ?? 0}
          onChange={e => update('cooldown_hours', Math.max(0, Number(e.target.value)))}
          className="min-h-11 w-20 rounded border border-border bg-background px-2 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
        />
        <span className="text-[10px] text-muted-foreground">小时 (0=一次性)</span>
      </div>

      {t === 'composite' && !isSub && (
        <div className="space-y-2 mt-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              value={condition.logic_operator || 'and'}
              onChange={e => update('logic_operator', e.target.value)}
              className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-foreground"
            >
              <option value="and">AND（全部满足）</option>
              <option value="or">OR（任一满足）</option>
            </select>
            <button
              type="button"
              onClick={() => {
                const subs = [...(condition.sub_conditions || []), cloneJson(DEFAULT_SUB_CONDITION)];
                update('sub_conditions', subs);
              }}
              className="flex min-h-11 items-center justify-center gap-1 rounded border border-border px-3 text-[10px] font-archive-mono text-muted-foreground transition-colors hover:text-primary"
            >
              <Plus size={10} /> 添加子条件
            </button>
          </div>
          {(condition.sub_conditions || []).map((sc, i) => (
            <SubConditionEditor
              key={i}
              condition={sc}
              onChange={v => {
                const subs = [...(condition.sub_conditions || [])];
                subs[i] = v;
                update('sub_conditions', subs);
              }}
              onDelete={() => {
                const subs = (condition.sub_conditions || []).filter((_, j) => j !== i);
                update('sub_conditions', subs);
              }}
              eventOptions={eventOptions}
              depth={depth}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TagInput({ tags, onChange, placeholder }) {
  const [input, setInput] = useState('');

  function handleKeyDown(e) {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault();
      if (!tags.includes(input.trim())) {
        onChange([...tags, input.trim()]);
      }
      setInput('');
    }
  }

  function removeTag(tag) {
    onChange(tags.filter(t => t !== tag));
  }

  return (
    <div className="flex flex-wrap items-center gap-1 p-1.5 bg-background border border-border rounded">
      {tags.map(tag => (
        <span key={tag} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-primary/10 border border-border rounded text-[10px] font-archive-mono text-foreground">
          {tag}
          <button type="button" onClick={() => removeTag(tag)} className="text-muted-foreground hover:text-destructive">
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="flex-1 min-w-[80px] bg-transparent text-primary text-xs font-archive-mono focus:outline-none placeholder:text-muted-foreground"
      />
    </div>
  );
}

function EffectEditor({ effect, onChange, onDelete, index, eventOptions }) {
  const update = (k, v) => onChange({ ...effect, [k]: v });
  const t = effect.effect_type || 'modify_state';
  const unavailable = UNAVAILABLE_EFFECT_TYPES.has(t);

  return (
    <div className="space-y-3 rounded border border-border bg-muted/25 p-3 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2">
          <span className="text-[10px] font-archive-mono text-muted-foreground">效果 #{index + 1}</span>
          <select
            value={t}
            onChange={e => onChange({ ...cloneJson(DEFAULT_EFFECT), effect_type: e.target.value })}
            className="min-h-11 min-w-0 rounded border border-primary/35 bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          >
            {unavailable && <option value={t}>{t}（未实现）</option>}
            {EFFECT_TYPES.map(et => (
              <option key={et.value} value={et.value}>{et.label}</option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`删除效果 ${index + 1}`}
          title="删除效果"
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:text-destructive"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {unavailable && (
        <div className="flex items-start gap-2 rounded border border-border bg-muted/35 p-3 text-[10px] font-archive-mono text-muted-foreground">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          该旧效果尚未实现，原始字段仍保留。请切换到可用效果后再保存。
        </div>
      )}

      {t === 'modify_state' && (
        <div className="space-y-2">
          {Object.entries(effect.state_changes || {}).map(([key, value]) => (
            <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_40px] items-center gap-2">
              <select
                value={key}
                onChange={e => {
                  const next = { ...(effect.state_changes || {}) };
                  delete next[key];
                  next[e.target.value] = value;
                  update('state_changes', next);
                }}
                className="min-h-11 min-w-0 rounded border border-border bg-background px-2 text-[11px] font-archive-mono text-primary"
              >
                {!['affection_level', 'trust_level', 'current_mood'].includes(key) && (
                  <option value={key}>{key}（不支持）</option>
                )}
                <option value="affection_level">好感度变化</option>
                <option value="trust_level">信任度变化</option>
                <option value="current_mood">当前情绪</option>
              </select>
              {key === 'current_mood' ? (
                <select
                  value={value ?? 'neutral'}
                  onChange={e => update('state_changes', { ...(effect.state_changes || {}), [key]: e.target.value })}
                  className="min-h-11 min-w-0 rounded border border-border bg-background px-2 text-[11px] font-archive-mono text-primary"
                >
                  {MOODS.map(mood => <option key={mood} value={mood}>{mood}</option>)}
                </select>
              ) : (
                <input
                  type="number"
                  value={value ?? ''}
                  onChange={e => update('state_changes', {
                    ...(effect.state_changes || {}),
                    [key]: e.target.value === '' ? '' : Number(e.target.value),
                  })}
                  placeholder="变化值"
                  className="min-h-11 min-w-0 rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                />
              )}
              <button
                type="button"
                onClick={() => {
                  const next = { ...(effect.state_changes || {}) };
                  delete next[key];
                  update('state_changes', next);
                }}
                aria-label={`删除状态字段 ${key}`}
                title="删除状态字段"
                className="inline-flex h-11 w-11 items-center justify-center text-muted-foreground hover:text-destructive"
              >
                <X size={12} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => {
              const changes = effect.state_changes || {};
              const nextKey = ['affection_level', 'trust_level', 'current_mood'].find(key => !(key in changes));
              if (nextKey) update('state_changes', { ...changes, [nextKey]: nextKey === 'current_mood' ? 'neutral' : 0 });
            }}
            disabled={['affection_level', 'trust_level', 'current_mood'].every(key => key in (effect.state_changes || {}))}
            className="flex min-h-11 items-center gap-1 text-[10px] font-archive-mono text-muted-foreground hover:text-primary disabled:opacity-30"
          >
            <Plus size={11} /> 添加状态字段
          </button>
        </div>
      )}

      {t === 'unlock_content' && (
        <TagInput
          tags={effect.unlock_keys || []}
          onChange={v => update('unlock_keys', v)}
          placeholder="解锁内容标识"
        />
      )}

      {t === 'trigger_dialogue' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.dialogue_text || ''}
            onChange={e => update('dialogue_text', e.target.value)}
            placeholder="对话内容"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
          <input
            type="text"
            value={effect.dialogue_action || ''}
            onChange={e => update('dialogue_action', e.target.value)}
            placeholder="动作描述"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
        </div>
      )}

      {t === 'add_memory' && (
        <div className="space-y-2">
          <textarea
            value={effect.memory_text || ''}
            onChange={e => update('memory_text', e.target.value)}
            placeholder="记忆内容"
            rows={2}
            className="w-full rounded border border-border bg-background px-3 py-2 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-archive-mono text-muted-foreground">重要性</label>
            <input
              type="number"
              value={effect.memory_importance ?? 5}
              onChange={e => update('memory_importance', Number(e.target.value))}
              min={1} max={10}
              className="min-h-11 w-20 rounded border border-border bg-background px-2 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
            />
          </div>
        </div>
      )}

      {t === 'change_mood' && (
        <select
          value={effect.target_mood || 'neutral'}
          onChange={e => update('target_mood', e.target.value)}
          className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary sm:max-w-xs"
        >
          {MOODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      )}

      {t === 'notify_player' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.notification_message || ''}
            onChange={e => update('notification_message', e.target.value)}
            placeholder="通知消息"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
          <select
            value={effect.notification_type || 'info'}
            onChange={e => update('notification_type', e.target.value)}
            className="min-h-11 rounded border border-border bg-background px-3 text-xs font-archive-mono text-foreground"
          >
            <option value="info">Info</option>
            <option value="success">Success</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </div>
      )}

      {t === 'trigger_event' && (
        <EventDependencySelect
          value={effect.next_event_id}
          onChange={value => update('next_event_id', value)}
          eventOptions={eventOptions}
          placeholder="选择后续事件"
        />
      )}

      {t === 'branch_event' && (
        <div className="space-y-4">
          <label className="block text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">默认后续事件（无分支命中时，可选）</span>
            <EventDependencySelect
              value={effect.next_event_id}
              onChange={value => update('next_event_id', value)}
              eventOptions={eventOptions}
              placeholder="不设置默认事件"
            />
          </label>
          {(effect.branch_conditions || []).map((branch, branchIndex) => (
            <div key={branchIndex} className="space-y-3 border-l-2 border-border pl-3 sm:pl-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-archive-mono text-muted-foreground">分支 #{branchIndex + 1}</span>
                <button
                  type="button"
                  onClick={() => update(
                    'branch_conditions',
                    (effect.branch_conditions || []).filter((_, itemIndex) => itemIndex !== branchIndex)
                  )}
                  aria-label={`删除分支 ${branchIndex + 1}`}
                  title="删除分支"
                  className="inline-flex h-11 w-11 items-center justify-center text-muted-foreground hover:text-destructive"
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <EventDependencySelect
                value={branch.event_id}
                onChange={value => {
                  const branches = cloneJson(effect.branch_conditions || []);
                  branches[branchIndex] = { ...branches[branchIndex], event_id: value };
                  update('branch_conditions', branches);
                }}
                eventOptions={eventOptions}
                placeholder="选择该分支的后续事件"
              />
              <TriggerConditionForm
                condition={branch.condition || cloneJson(DEFAULT_SUB_CONDITION)}
                onChange={value => {
                  const branches = cloneJson(effect.branch_conditions || []);
                  branches[branchIndex] = { ...branches[branchIndex], condition: value };
                  update('branch_conditions', branches);
                }}
                eventOptions={eventOptions}
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => update('branch_conditions', [
              ...(effect.branch_conditions || []),
              cloneJson(DEFAULT_BRANCH_CONDITION),
            ])}
            className="flex min-h-11 items-center gap-1 rounded border border-border px-3 text-[10px] font-archive-mono text-muted-foreground hover:text-primary"
          >
            <Plus size={11} /> 添加分支
          </button>
        </div>
      )}

      {t === 'npc_proactive_dialogue' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.proactive_character_id || ''}
            onChange={e => update('proactive_character_id', e.target.value)}
            placeholder="主动发言角色 ID（可选）"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
          <input
            type="text"
            value={effect.target_session_id || ''}
            onChange={e => update('target_session_id', e.target.value)}
            placeholder="目标会话 ID（可选）"
            className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
          <textarea
            value={effect.proactive_prompt || ''}
            onChange={e => update('proactive_prompt', e.target.value)}
            placeholder="主动发言提示"
            rows={2}
            className="w-full rounded border border-border bg-background px-3 py-2 text-xs font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
          />
        </div>
      )}

      {t === 'update_event_progress' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">直接进度（0 到 1）</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={effect.progress ?? ''}
              onChange={e => update('progress', e.target.value === '' ? null : Number(e.target.value))}
              className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
            />
          </label>
          <label className="text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">进度变化量</span>
            <input
              type="number"
              step="0.01"
              value={effect.progress_delta ?? ''}
              onChange={e => update('progress_delta', e.target.value === '' ? null : Number(e.target.value))}
              className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
            />
          </label>
          <label className="text-[10px] font-archive-mono text-muted-foreground">
            <span className="mb-1 block">阶段状态</span>
            <select
              value={effect.event_status || ''}
              onChange={e => update('event_status', e.target.value)}
              className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary"
            >
              <option value="">不修改</option>
              {PROGRESS_STATUSES.map(status => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
        </div>
      )}
    </div>
  );
}

export default function EventEditor() {
  const { eventId } = useParams();
  const navigate = useNavigate();
  const dialog = useDialog();
  const { setPrimaryAction } = useArchiveShell();
  const isExistingEvent = !!eventId && eventId !== 'new';
  const eventRequestRef = useRef(0);
  const navigationTimeoutRef = useRef(null);
  if (!navigationTimeoutRef.current) {
    navigationTimeoutRef.current = createTimeoutController();
  }
  const [loading, setLoading] = useState(isExistingEvent);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [saveMsgKind, setSaveMsgKind] = useState('info');
  const [validationWarnings, setValidationWarnings] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [loadedEventId, setLoadedEventId] = useState(isExistingEvent ? null : 'new');
  const [reloadVersion, setReloadVersion] = useState(0);
  const [form, setForm] = useState(cloneDefaultForm);

  const [activeStep, setActiveStep] = useState('basic');
  const [templateOpen, setTemplateOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState('');
  const [characters, setCharacters] = useState([]);
  const [charactersLoading, setCharactersLoading] = useState(true);
  const [charactersError, setCharactersError] = useState('');

  useEffect(() => () => navigationTimeoutRef.current.cancel(), []);

  const selectedTemplate = useMemo(
    () => templates.find(t => t.template_id === selectedTemplateId),
    [templates, selectedTemplateId]
  );
  const eventOptions = useMemo(
    () => events.filter(event => event.event_id !== (eventId && eventId !== 'new' ? eventId : form.event_id)),
    [events, eventId, form.event_id]
  );
  const characterOptions = useMemo(
    () => [...characters].sort((a, b) => {
      const activeDifference = Number(Boolean(b.is_active)) - Number(Boolean(a.is_active));
      if (activeDifference) return activeDifference;
      const aName = a.display_name || a.name || a.character_id;
      const bName = b.display_name || b.name || b.character_id;
      return aName.localeCompare(bName, 'zh-CN');
    }),
    [characters]
  );
  const selectedCharacterMissing = Boolean(
    form.character_id
    && !characters.some(character => character.character_id === form.character_id)
  );
  const unavailableConfiguration = useMemo(
    () => collectUnavailableConfiguration(form.trigger_condition, form.effects, []),
    [form.trigger_condition, form.effects]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await eventAdmin.templates();
        if (cancelled) return;
        setTemplates(Array.isArray(rows) ? rows : []);
        setTemplatesError('');
      } catch (e) {
        if (cancelled) return;
        setTemplatesError(e.message || '模板加载失败');
      } finally {
        if (!cancelled) setTemplatesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await characterAdmin.list(false);
        if (cancelled) return;
        setCharacters(Array.isArray(rows) ? rows : []);
        setCharactersError('');
      } catch (e) {
        if (cancelled) return;
        setCharacters([]);
        setCharactersError(e.message || '角色列表加载失败');
      } finally {
        if (!cancelled) setCharactersLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await eventAdmin.list();
        if (cancelled) return;
        setEvents(Array.isArray(rows) ? rows : []);
        setEventsError('');
      } catch (e) {
        if (cancelled) return;
        setEventsError(e.message || '事件依赖列表加载失败');
      } finally {
        if (!cancelled) setEventsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const requestId = ++eventRequestRef.current;
    let cancelled = false;

    setSaveMsg('');
    setSaveMsgKind('info');
    setValidationWarnings([]);
    setLoadError('');

    if (!isExistingEvent) {
      setForm(cloneDefaultForm());
      setSelectedTemplateId('');
      setActiveStep('basic');
      setTemplateOpen(false);
      setAdvancedOpen(false);
      setLoadedEventId('new');
      setLoading(false);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setLoadedEventId(null);
    setActiveStep('basic');
    setTemplateOpen(false);
    setAdvancedOpen(false);
    (async () => {
      try {
        const detail = await eventAdmin.get(eventId);
        if (cancelled || eventRequestRef.current !== requestId) return;
        setForm({
          event_id: detail.event_id,
          event_name: detail.event_name,
          description: detail.description || '',
          character_id: detail.character_id || '',
          trigger_condition: detail.trigger_condition || { trigger_type: 'keyword_match', keywords: [] },
          effects: detail.effects || [],
          priority: detail.priority || 0,
          exclusive_group: detail.exclusive_group || '',
          max_triggers_per_turn: detail.max_triggers_per_turn || 3,
          stop_processing: Boolean(detail.stop_processing),
          is_active: detail.is_active,
          schedule: detail.schedule || '',
          template_id: detail.template_id || '',
        });
        setSelectedTemplateId(detail.template_id || '');
        setLoadedEventId(eventId);
      } catch (e) {
        if (cancelled || eventRequestRef.current !== requestId) return;
        setLoadError(e.message || '事件加载失败');
      } finally {
        if (!cancelled && eventRequestRef.current === requestId) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [eventId, isExistingEvent, reloadVersion]);

  async function handleSave() {
    if (isExistingEvent && loadedEventId !== eventId) {
      setSaveMsg('事件尚未正确加载，无法保存');
      setSaveMsgKind('error');
      return;
    }
    const { errors, warnings } = validateEventForm(form);
    setValidationWarnings(warnings);
    if (errors.length) {
      setSaveMsg(errors.join('；'));
      setSaveMsgKind('error');
      return;
    }
    setSaving(true);
    setSaveMsg('');
    setSaveMsgKind('info');
    try {
      const payload = cloneJson(sanitizeEventPayload(form));
      payload.template_id = sanitizeOptionalString(payload.template_id);
      if (isExistingEvent) {
        await eventAdmin.update(eventId, payload);
      } else {
        await eventAdmin.create(payload);
      }
      setSaveMsg(warnings.length ? `保存成功；${warnings.join('；')}` : '保存成功');
      setSaveMsgKind('success');
      navigationTimeoutRef.current.schedule(() => navigate('/events'), 600);
    } catch (e) {
      setSaveMsg(`保存失败: ${e.message}`);
      setSaveMsgKind('error');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!isExistingEvent || loadedEventId !== eventId || saving || deleting) return;
    const ok = await dialog.confirm({
      title: '永久删除事件',
      message: `确定要永久删除「${form.event_name || eventId}」吗？\n删除后无法恢复。`,
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;
    setDeleting(true);
    setSaveMsg('');
    setSaveMsgKind('info');
    try {
      await eventAdmin.delete(eventId);
      navigate('/events');
    } catch (e) {
      setSaveMsg(`删除失败: ${e.message}`);
      setSaveMsgKind('error');
    } finally {
      setDeleting(false);
    }
  }

  const actionPending = saving || deleting;
  const saveDisabled = loading || actionPending || Boolean(loadError)
    || (isExistingEvent && loadedEventId !== eventId)
    || unavailableConfiguration.length > 0;
  const primaryAction = useMemo(() => (
    <Button type="button" size="lg" onClick={handleSave} disabled={saveDisabled}>
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存事件'}
    </Button>
  ), [
    deleting,
    eventId,
    form,
    isExistingEvent,
    loadError,
    loadedEventId,
    loading,
    saving,
  ]);

  useEffect(() => {
    setPrimaryAction(primaryAction);
    return () => setPrimaryAction(null);
  }, [primaryAction, setPrimaryAction]);

  if (loading) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center text-muted-foreground" role="status">
        <Loader2 className="h-7 w-7 animate-spin" aria-hidden="true" />
        <span className="sr-only">正在加载事件档案</span>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center px-4">
        <div className="w-full max-w-md border border-destructive/30 bg-card p-6 text-center" role="alert">
          <AlertCircle className="mx-auto h-8 w-8 text-destructive" aria-hidden="true" />
          <h1 className="mt-4 font-archive-serif text-lg font-semibold text-foreground">
            事件档案加载失败
          </h1>
          <p className="mt-2 break-words font-archive-mono text-xs text-destructive">{loadError}</p>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Button type="button" variant="outline" onClick={() => navigate('/events')}>
              <ArrowLeft aria-hidden="true" /> 返回
            </Button>
            <Button type="button" onClick={() => setReloadVersion(value => value + 1)}>
              重试
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const updateField = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const handleApplyTemplate = () => {
    if (!selectedTemplate) return;
    setForm(prev => ({
      ...prev,
      event_name: prev.event_name || selectedTemplate.template_name || '',
      description: selectedTemplate.description || prev.description || '',
      trigger_condition: cloneJson(selectedTemplate.trigger_config) || prev.trigger_condition,
      effects: cloneJson(selectedTemplate.effects_config) || [],
      template_id: selectedTemplate.template_id,
    }));
    setSaveMsg(`已应用模板: ${selectedTemplate.template_name}`);
    setSaveMsgKind('info');
  };

  const editorSteps = [
    {
      id: 'basic',
      label: '基本信息',
      description: '名称、范围和基础属性',
      icon: Zap,
    },
    {
      id: 'trigger',
      label: '触发条件',
      description: '定义事件何时发生',
      icon: Workflow,
    },
    {
      id: 'effects',
      label: '事件效果',
      description: `配置触发后的结果${form.effects.length ? ` · ${form.effects.length} 项` : ''}`,
      icon: Sparkles,
    },
    ...(isExistingEvent
      ? [{
          id: 'operations',
          label: '运行管理',
          description: '查看和控制运行状态',
          icon: Activity,
        }]
      : []),
  ];
  const activeStepIndex = Math.max(
    0,
    editorSteps.findIndex(step => step.id === activeStep)
  );
  const currentStep = editorSteps[activeStepIndex];
  const previousStep = editorSteps[activeStepIndex - 1];
  const nextStep = editorSteps[activeStepIndex + 1];

  const notice = (saveMsg || unavailableConfiguration.length > 0 || validationWarnings.length > 0) ? (
    <div className="mb-4 space-y-2">
      {saveMsg && (
        <div
          className={`flex items-start gap-2 border px-3 py-3 font-archive-mono text-xs ${
            saveMsgKind === 'error'
              ? 'border-destructive/30 bg-destructive/5 text-destructive'
              : saveMsgKind === 'success'
                ? 'border-primary/30 bg-primary/5 text-foreground'
                : 'border-border bg-muted/25 text-muted-foreground'
          }`}
          role={saveMsgKind === 'error' ? 'alert' : 'status'}
          aria-live={saveMsgKind === 'error' ? 'assertive' : 'polite'}
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{saveMsg}</span>
        </div>
      )}
      {unavailableConfiguration.length > 0 && (
        <div
          className="flex items-start gap-3 border border-destructive/25 bg-destructive/5 px-4 py-3 text-xs text-foreground"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
          <div className="min-w-0">
            <p className="font-medium text-foreground">存在不可用的旧配置，当前禁止保存</p>
            <p className="mt-1 break-words font-archive-mono text-[11px] leading-5 text-muted-foreground">
              {unavailableConfiguration.join('；')}。原字段不会被静默替换，请在对应位置切换类型。
            </p>
          </div>
        </div>
      )}
      {validationWarnings.length > 0 && (
        <div
          className="flex items-start gap-3 border border-border bg-muted/25 px-4 py-3 text-xs text-muted-foreground"
          role="status"
          aria-live="polite"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="min-w-0 break-words font-archive-mono">{validationWarnings.join('；')}</p>
        </div>
      )}
    </div>
  ) : null;

  const directory = (
    <div className="p-3">
      <div className="border-b border-border px-2 pb-3">
        <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">章节目录</p>
        <p className="mt-1 truncate font-archive-serif text-base font-semibold text-foreground">
          {form.event_name || '未命名事件'}
        </p>
        <p className="mt-1 break-all font-archive-mono text-[10px] tabular-nums text-muted-foreground">
          {form.event_id || '尚未填写事件 ID'}
        </p>
      </div>
      <nav aria-label="事件编辑步骤" className="mt-2 space-y-1">
        {editorSteps.map((step, index) => {
          const StepIcon = step.icon;
          const isActive = step.id === currentStep.id;
          const isComplete = index < activeStepIndex;
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setActiveStep(step.id)}
              aria-current={isActive ? 'step' : undefined}
              className={`flex min-h-14 w-full min-w-0 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
                isActive
                  ? 'border-primary/40 bg-primary/10 text-foreground'
                  : 'border-transparent text-muted-foreground hover:border-border hover:bg-muted/35 hover:text-foreground'
              }`}
            >
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${
                isActive || isComplete
                  ? 'border-primary/35 bg-background text-primary'
                  : 'border-border bg-background'
              }`}>
                <StepIcon className="h-4 w-4" aria-hidden="true" />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-medium">{step.label}</span>
                <span className="mt-0.5 hidden truncate text-[10px] text-muted-foreground lg:block">
                  {step.description}
                </span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="mt-4 border-t border-border pt-4">
        <p className="px-2 text-[10px] uppercase text-muted-foreground">档案工具</p>
        <div className="mt-2 grid gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate('/events')}
            className="w-full justify-start"
          >
            <ArrowLeft aria-hidden="true" /> 返回事件目录
          </Button>
          {isExistingEvent && (
            <Button
              type="button"
              variant="destructive"
              onClick={handleDelete}
              disabled={actionPending || loadedEventId !== eventId}
              className="w-full justify-start"
            >
              {deleting
                ? <Loader2 className="animate-spin" aria-hidden="true" />
                : <Trash2 aria-hidden="true" />}
              永久删除
            </Button>
          )}
        </div>
      </div>
    </div>
  );

  const editor = (
    <div className="min-w-0">
      <div className="flex min-h-20 items-center gap-3 border-b border-border bg-muted/20 px-4 py-4 sm:px-6">
        <span className="font-archive-mono text-xs tabular-nums text-muted-foreground">
          {String(activeStepIndex + 1).padStart(2, '0')}
        </span>
        <div className="min-w-0">
          <h2 className="font-archive-serif text-lg font-semibold text-foreground">{currentStep.label}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{currentStep.description}</p>
        </div>
      </div>

      <div className="min-h-[520px] min-w-0 p-4 font-archive-serif leading-7 sm:p-6">
                {currentStep.id === 'basic' && (
                  <div className="space-y-6">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <label className="block">
                        <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">事件 ID *</span>
                        <input
                          type="text"
                          value={form.event_id}
                          onChange={e => updateField('event_id', e.target.value)}
                          disabled={isExistingEvent}
                          placeholder="evt_charactername_eventname"
                          className="min-h-11 w-full rounded border border-primary/35 bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none disabled:opacity-40"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">事件名称 *</span>
                        <input
                          type="text"
                          value={form.event_name}
                          onChange={e => updateField('event_name', e.target.value)}
                          placeholder="例如：初次见面的惊喜"
                          className="min-h-11 w-full rounded border border-primary/35 bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                        />
                      </label>
                    </div>

                    <label className="block">
                      <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">描述</span>
                      <textarea
                        value={form.description}
                        onChange={e => updateField('description', e.target.value)}
                        placeholder="事件的简要描述..."
                        rows={3}
                        className="w-full rounded border border-border bg-background px-3 py-2.5 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                      />
                    </label>

                    <section className="border-t border-border pt-2">
                      <button
                        type="button"
                        onClick={() => setTemplateOpen(value => !value)}
                        aria-expanded={templateOpen}
                        className="flex min-h-11 w-full items-center justify-between gap-3 text-left text-xs font-archive-mono text-muted-foreground transition-colors hover:text-primary"
                      >
                        <span className="flex items-center gap-2">
                          <Wand2 size={14} />
                          从模板快速创建
                        </span>
                        <ChevronRight
                          size={15}
                          className={`shrink-0 transition-transform ${templateOpen ? 'rotate-90' : ''}`}
                        />
                      </button>
                      {templateOpen && (
                        <div className="space-y-3 pb-4 pt-2">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                            <label className="min-w-0 flex-1">
                              <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">系统模板</span>
                              <select
                                value={selectedTemplateId}
                                onChange={e => setSelectedTemplateId(e.target.value)}
                                disabled={templatesLoading}
                                className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none disabled:opacity-50"
                              >
                                <option value="">{templatesLoading ? '加载模板中...' : '不使用模板'}</option>
                                {templates.map(template => (
                                  <option key={template.template_id} value={template.template_id}>
                                    {template.category ? `[${template.category}] ` : ''}{template.template_name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <button
                              type="button"
                              onClick={handleApplyTemplate}
                              disabled={!selectedTemplate || templatesLoading}
                              className="flex min-h-11 items-center justify-center gap-2 rounded border border-primary/35 px-4 text-xs font-archive-mono text-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-40"
                            >
                              <Wand2 size={14} />
                              应用模板
                            </button>
                          </div>
                          {templatesError && (
                            <p className="text-xs font-archive-mono text-destructive">{templatesError}</p>
                          )}
                          {selectedTemplate?.description && (
                            <p className="text-xs font-archive-mono leading-5 text-muted-foreground">
                              {selectedTemplate.description}
                            </p>
                          )}
                          {selectedTemplate && (
                            <div className="border-l-2 border-border pl-3">
                              <PipelinePreview
                                triggerCondition={selectedTemplate.trigger_config}
                                effects={selectedTemplate.effects_config || []}
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </section>

                    <section className="border-t border-border pt-2">
                      <button
                        type="button"
                        onClick={() => setAdvancedOpen(value => !value)}
                        aria-expanded={advancedOpen}
                        className="flex min-h-11 w-full items-center justify-between gap-3 text-left text-xs font-archive-mono text-muted-foreground transition-colors hover:text-primary"
                      >
                        <span className="flex items-center gap-2">
                          <Settings2 size={14} />
                          高级运行参数
                        </span>
                        <ChevronRight
                          size={15}
                          className={`shrink-0 transition-transform ${advancedOpen ? 'rotate-90' : ''}`}
                        />
                      </button>
                      {advancedOpen && (
                        <div className="grid grid-cols-1 gap-4 pb-4 pt-3 sm:grid-cols-2">
                          <label className="block">
                            <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">关联角色 ID</span>
                            <select
                              value={form.character_id}
                              onChange={e => updateField('character_id', e.target.value)}
                              disabled={charactersLoading}
                              aria-describedby={charactersError ? 'event-character-error' : undefined}
                              className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none disabled:cursor-wait disabled:opacity-50"
                            >
                              <option value="">
                                {charactersLoading ? '正在加载角色...' : '全局事件（不关联角色）'}
                              </option>
                              {selectedCharacterMissing && (
                                <option value={form.character_id}>
                                  {form.character_id}（角色不存在或不可用）
                                </option>
                              )}
                              {characterOptions.map(character => {
                                const name = character.display_name || character.name || character.character_id;
                                const isActive = Boolean(character.is_active);
                                return (
                                  <option
                                    key={character.character_id}
                                    value={character.character_id}
                                    disabled={!isActive}
                                  >
                                    {name}（{character.character_id}）{isActive ? '' : ' · 已停用'}
                                  </option>
                                );
                              })}
                            </select>
                            {charactersError && (
                              <span
                                id="event-character-error"
                                className="mt-1.5 block text-xs font-archive-mono leading-5 text-destructive"
                              >
                                角色列表加载失败：{charactersError}
                              </span>
                            )}
                          </label>
                          <label className="block">
                            <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">优先级</span>
                            <input
                              type="number"
                              value={form.priority}
                              onChange={e => updateField('priority', Number(e.target.value))}
                              className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                            />
                          </label>
                          <label className="block">
                            <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">互斥组</span>
                            <input
                              type="text"
                              value={form.exclusive_group}
                              onChange={e => updateField('exclusive_group', e.target.value)}
                              placeholder="同组每轮仅触发最高优先级"
                              className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                            />
                          </label>
                          <label className="block">
                            <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">每轮最多触发</span>
                            <input
                              type="number"
                              min="1"
                              max="20"
                              value={form.max_triggers_per_turn}
                              onChange={e => updateField('max_triggers_per_turn', Number(e.target.value))}
                              className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                            />
                          </label>
                          <label className="block sm:col-span-2">
                            <span className="mb-1.5 block text-xs font-archive-mono text-muted-foreground">调度 Cron（5 字段）</span>
                            <input
                              type="text"
                              value={form.schedule}
                              onChange={e => updateField('schedule', e.target.value)}
                              placeholder="0 9 * * *；必须绑定角色"
                              className="min-h-11 w-full rounded border border-border bg-background px-3 text-sm font-archive-mono text-primary focus:border-primary/40 focus:outline-none"
                            />
                          </label>
                          <div className="flex flex-col gap-1 sm:col-span-2 sm:flex-row sm:gap-6">
                            <label className="flex min-h-11 cursor-pointer items-center gap-2">
                              <input
                                type="checkbox"
                                checked={form.is_active}
                                onChange={e => updateField('is_active', e.target.checked)}
                                className="accent-primary"
                              />
                              <span className="text-xs font-archive-mono text-muted-foreground">启用事件</span>
                            </label>
                            <label className="flex min-h-11 cursor-pointer items-center gap-2">
                              <input
                                type="checkbox"
                                checked={form.stop_processing}
                                onChange={e => updateField('stop_processing', e.target.checked)}
                                className="accent-primary"
                              />
                              <span className="text-xs font-archive-mono text-muted-foreground">
                                触发后停止处理后续事件
                              </span>
                            </label>
                          </div>
                        </div>
                      )}
                    </section>
                  </div>
                )}

                {currentStep.id === 'trigger' && (
                  <div className="space-y-5">
                    {(eventsLoading || eventsError) && (
                      <div className="border-l-2 border-border pl-3">
                        {eventsLoading && (
                          <p className="text-xs font-archive-mono text-muted-foreground">正在加载事件依赖...</p>
                        )}
                        {eventsError && (
                          <p className="break-words text-xs font-archive-mono text-destructive">{eventsError}</p>
                        )}
                      </div>
                    )}
                    <TriggerConditionForm
                      condition={form.trigger_condition}
                      onChange={value => updateField('trigger_condition', value)}
                      eventOptions={eventOptions}
                    />
                    <div className="border-t border-border pt-4">
                      <p className="mb-3 text-[10px] font-archive-mono uppercase text-muted-foreground">
                        事件流程摘要
                      </p>
                      <PipelinePreview
                        triggerCondition={form.trigger_condition}
                        effects={form.effects}
                      />
                    </div>
                  </div>
                )}

                {currentStep.id === 'effects' && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between gap-3 border-b border-border pb-4">
                      <p className="text-xs font-archive-mono text-muted-foreground">
                        {form.effects.length > 0
                          ? `已配置 ${form.effects.length} 项效果，按顺序执行`
                          : '尚未配置事件效果'}
                      </p>
                      <button
                        type="button"
                        onClick={() => updateField('effects', [...form.effects, { ...DEFAULT_EFFECT }])}
                        className="flex min-h-11 shrink-0 items-center justify-center gap-2 rounded border border-primary/30 px-4 text-xs font-archive-mono text-foreground transition-colors hover:border-primary/40 hover:text-primary"
                      >
                        <Plus size={14} />
                        添加效果
                      </button>
                    </div>
                    {form.effects.length === 0 && (
                      <div className="flex min-h-48 flex-col items-center justify-center border border-dashed border-border px-6 text-center">
                        <Sparkles size={22} className="text-muted-foreground" />
                        <p className="mt-3 text-sm font-archive-mono text-muted-foreground">此事件暂时不会产生效果</p>
                        <p className="mt-1 text-xs font-archive-mono text-muted-foreground">添加一项效果来定义触发后的结果</p>
                      </div>
                    )}
                    {form.effects.map((effect, index) => (
                      <EffectEditor
                        key={index}
                        index={index}
                        effect={effect}
                        eventOptions={eventOptions}
                        onChange={value => {
                          const effects = [...form.effects];
                          effects[index] = value;
                          updateField('effects', effects);
                        }}
                        onDelete={() => {
                          updateField('effects', form.effects.filter((_, itemIndex) => itemIndex !== index));
                        }}
                      />
                    ))}
                  </div>
                )}

                {currentStep.id === 'operations' && isExistingEvent && loadedEventId === eventId && (
                  <EventOperationsPanel eventId={eventId} characterId={form.character_id} />
                )}
              </div>

              <div className="flex flex-col-reverse gap-3 border-t border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <button
                  type="button"
                  onClick={() => previousStep && setActiveStep(previousStep.id)}
                  disabled={!previousStep}
                  className="flex min-h-11 items-center justify-center gap-2 rounded border border-border px-4 text-xs font-archive-mono text-muted-foreground transition-colors hover:border-primary/35 hover:text-primary disabled:invisible"
                >
                  <ArrowLeft size={14} />
                  上一步
                </button>
                {nextStep ? (
                  <button
                    type="button"
                    onClick={() => setActiveStep(nextStep.id)}
                    className="flex min-h-11 items-center justify-center gap-2 rounded border border-primary/35 bg-primary/10 px-5 text-xs font-archive-mono text-primary transition-colors hover:bg-primary/15"
                  >
                    下一步
                    <ChevronRight size={14} />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saveDisabled}
                    className="flex min-h-11 items-center justify-center gap-2 rounded border border-primary/35 bg-primary/10 px-5 text-xs font-archive-mono text-primary transition-colors hover:bg-primary/15 disabled:opacity-50"
                  >
                    {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                    保存事件
                  </button>
                )}
              </div>
    </div>
  );

  const summary = (
    <div className="p-4">
      <div className="border-b border-border pb-3">
        <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">事件摘要</p>
        <p className="mt-1 font-archive-serif text-base font-semibold text-foreground">
          {form.event_name || '未命名事件'}
        </p>
      </div>
      <dl className="text-xs">
        {[
          ['状态', form.is_active ? '启用' : '停用', false],
          ['作用域', form.character_id || '全局事件', true],
          [
            '触发类型',
            TRIGGER_TYPES.find(type => type.value === form.trigger_condition?.trigger_type)?.label || '未配置',
            false,
          ],
          ['效果数量', form.effects.length, true],
          ['优先级', form.priority, true],
          ['每轮上限', form.max_triggers_per_turn, true],
          ['当前章节', `${activeStepIndex + 1} / ${editorSteps.length}`, true],
        ].map(([label, value, mono]) => (
          <div
            key={label}
            className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 border-b border-border py-3 last:border-b-0"
          >
            <dt className="text-muted-foreground">{label}</dt>
            <dd className={`min-w-0 break-words text-right text-foreground ${
              mono ? 'font-archive-mono tabular-nums' : ''
            }`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
      {form.schedule && (
        <div className="mt-4 border border-border bg-muted/25 p-3">
          <p className="text-xs font-medium text-foreground">调度 Cron</p>
          <p className="mt-2 break-all font-archive-mono text-xs tabular-nums text-muted-foreground">
            {form.schedule}
          </p>
        </div>
      )}
      <div className="mt-4 border border-border bg-muted/25 p-3">
        <p className="text-xs font-medium text-foreground">流程预览</p>
        <div className="mt-3">
          <PipelinePreview
            triggerCondition={form.trigger_condition}
            effects={form.effects}
          />
        </div>
      </div>
    </div>
  );

  const mobileAction = (
    <Button
      type="button"
      size="lg"
      onClick={handleSave}
      disabled={saveDisabled}
      className="w-full"
    >
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存事件'}
    </Button>
  );

  return (
    <ArchiveEditorWorkspace
      indexLabel={isExistingEvent ? 'Event archive / edit' : 'Event archive / new'}
      title={isExistingEvent ? '编辑事件档案' : '新建事件档案'}
      description="按章节编排触发条件与事件效果，并在右侧实时核对运行摘要。"
      directory={directory}
      editor={editor}
      summary={summary}
      mobileAction={mobileAction}
      notice={notice}
    />
  );
}
