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
} from 'lucide-react';
import { eventAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import EventOperationsPanel from '../components/EventOperationsPanel';

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
    <div className="flex items-center gap-2 text-[10px] font-mono flex-wrap">
      <div className="flex items-center gap-1.5 rounded-lg border border-cyber-green/15 bg-cyber-surface/60 px-2.5 py-1">
        <Zap size={12} className="text-cyber-green/50" />
        <span className="text-cyber-green/65">{tcLabel}</span>
      </div>
      <ArrowLeft size={12} className="rotate-180 text-cyber-green/18" />

      {t === 'composite' && (
        <span className="text-cyber-green/25">
          {(triggerCondition?.sub_conditions || []).length} 子条件
          {' '}{triggerCondition?.logic_operator === 'or' ? 'OR' : 'AND'}
        </span>
      )}
      {t === 'keyword_match' && (
        <span className="text-cyber-green/25">
          {(triggerCondition?.keywords || []).length} 关键词
        </span>
      )}
      {(t === 'affinity_threshold' || t === 'trust_threshold') && (
        <span className="text-cyber-green/25">
          {triggerCondition?.comparison || 'gte'} {triggerCondition?.threshold ?? '?'}
        </span>
      )}
      {t === 'dialogue_count' && (
        <span className="text-cyber-green/25">
          {triggerCondition?.comparison || 'gte'} {triggerCondition?.count ?? '?'}
        </span>
      )}

      {effects.length > 0 && <ArrowLeft size={12} className="rotate-180 text-cyber-green/18" />}
      {effects.map((eff, i) => (
        <span key={i} className="rounded-lg border border-cyber-green/8 bg-cyber-green/5 px-2.5 py-1 text-cyber-green/45">
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
      className="min-h-11 w-full min-w-0 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
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
    <div className="rounded border-l-2 border-cyber-green/10 pl-3 sm:ml-4 sm:pl-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-mono text-cyber-green/40">子条件</span>
        <button
          type="button"
          onClick={onDelete}
          aria-label="删除子条件"
          title="删除子条件"
          className="inline-flex h-11 w-11 items-center justify-center text-cyber-green/30 transition-colors hover:text-red-400"
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
          className="min-h-11 max-w-full rounded border border-cyber-green/30 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/60 focus:outline-none"
        >
          {unavailable && <option value={t}>{t}（未实现）</option>}
          {TRIGGER_TYPES.filter(tt => isSub ? tt.value !== 'composite' : true).map(tt => (
            <option key={tt.value} value={tt.value}>{tt.label}</option>
          ))}
        </select>
      </div>

      {unavailable && (
        <div className="flex items-start gap-2 rounded border border-amber-300/20 bg-amber-300/5 p-3 text-[10px] font-mono text-amber-200/70">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          该旧触发类型尚未实现，原配置已保留。请切换到可用类型后再保存。
        </div>
      )}

      {thresholdType && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,180px)_minmax(0,140px)]">
          <select
            value={condition.comparison || 'gte'}
            onChange={e => update('comparison', e.target.value)}
            className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green/70"
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
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
        </div>
      )}

      {(t === 'affinity_threshold' || t === 'trust_threshold') && (
        <label className="flex min-h-11 items-center gap-2 text-[10px] font-mono text-cyber-green/45">
          <input
            type="checkbox"
            checked={Boolean(condition.crossing)}
            onChange={e => update('crossing', e.target.checked)}
            className="accent-cyber-green"
          />
          仅在本轮首次跨过阈值时触发
        </label>
      )}

      {t === 'state_delta' && (
        <label className="block text-[10px] font-mono text-cyber-green/40">
          <span className="mb-1 block">变化字段</span>
          <select
            value={condition.state_field || 'affinity'}
            onChange={e => update('state_field', e.target.value)}
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green sm:max-w-xs"
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
            className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green/70"
          >
            {COMPARISONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <input
            type="number"
            min="0"
            value={condition.count ?? ''}
            onChange={e => update('count', e.target.value === '' ? null : Number(e.target.value))}
            placeholder="历史总轮数"
            className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
        </div>
      )}

      {t === 'time_based' && (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-[10px] font-mono text-cyber-green/40">
              <span className="mb-1 block">会话时长（分钟）</span>
              <input
                type="number"
                min="0"
                value={condition.duration_minutes ?? ''}
                onChange={e => update('duration_minutes', e.target.value === '' ? null : Number(e.target.value))}
                className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green focus:border-cyber-green/50 focus:outline-none"
              />
            </label>
            <label className="text-[10px] font-mono text-cyber-green/40">
              <span className="mb-1 block">Cron（5 字段，可替代时长）</span>
              <input
                type="text"
                value={condition.schedule || ''}
                onChange={e => update('schedule', e.target.value)}
                placeholder="0 9 * * *"
                className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green focus:border-cyber-green/50 focus:outline-none"
              />
            </label>
          </div>
          <label className="block text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">补偿重放上限</span>
            <input
              type="number"
              min="1"
              max="100"
              value={condition.catch_up_replay_limit ?? 1}
              onChange={event => update('catch_up_replay_limit', Math.min(100, Math.max(1, Number(event.target.value) || 1)))}
              className="min-h-11 w-28 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
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
              className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green/70"
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
          className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green sm:max-w-xs"
        >
          {MOODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      )}

      {t === 'event_history' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="min-w-0 text-[10px] font-mono text-cyber-green/40 sm:col-span-3">
            <span className="mb-1 block">依赖事件</span>
            <EventDependencySelect
              value={condition.event_id}
              onChange={value => update('event_id', value)}
              eventOptions={eventOptions}
              placeholder="选择依赖事件"
            />
          </label>
          <label className="text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">执行状态</span>
            <select
              value={condition.event_status || 'succeeded'}
              onChange={e => update('event_status', e.target.value)}
              className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green"
            >
              {EVENT_STATUSES.map(status => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
          <label className="text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">最少执行次数</span>
            <input
              type="number"
              min="1"
              value={condition.min_occurrences ?? 1}
              onChange={e => update('min_occurrences', Math.max(1, Number(e.target.value) || 1))}
              className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green focus:border-cyber-green/50 focus:outline-none"
            />
          </label>
        </div>
      )}

      {t === 'world_time_window' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <label className="text-[10px] font-mono text-cyber-green/40">
              <span className="mb-1 block">开始时间</span>
              <input
                type="time"
                value={condition.time_window_start || ''}
                onChange={e => update('time_window_start', e.target.value)}
                className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green"
              />
            </label>
            <label className="text-[10px] font-mono text-cyber-green/40">
              <span className="mb-1 block">结束时间</span>
              <input
                type="time"
                value={condition.time_window_end || ''}
                onChange={e => update('time_window_end', e.target.value)}
                className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green"
              />
            </label>
          </div>
          <div>
            <p className="mb-1 text-[10px] font-mono text-cyber-green/40">星期（不选表示每天）</p>
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
                    className={`h-11 w-11 rounded border text-[10px] font-mono transition-colors ${
                      selected
                        ? 'border-cyber-green/40 bg-cyber-green/10 text-cyber-green'
                        : 'border-cyber-green/15 text-cyber-green/35 hover:text-cyber-green/70'
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
        <label className="text-[10px] font-mono text-cyber-green/40">冷却时间</label>
        <input
          type="number"
          min="0"
          value={condition.cooldown_hours ?? 0}
          onChange={e => update('cooldown_hours', Math.max(0, Number(e.target.value)))}
          className="min-h-11 w-20 rounded border border-cyber-green/20 bg-cyber-surface px-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
        />
        <span className="text-[10px] text-cyber-green/30">小时 (0=一次性)</span>
      </div>

      {t === 'composite' && !isSub && (
        <div className="space-y-2 mt-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              value={condition.logic_operator || 'and'}
              onChange={e => update('logic_operator', e.target.value)}
              className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green/70"
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
              className="flex min-h-11 items-center justify-center gap-1 rounded border border-cyber-green/20 px-3 text-[10px] font-mono text-cyber-green/50 transition-colors hover:text-cyber-green"
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
    <div className="flex flex-wrap items-center gap-1 p-1.5 bg-cyber-surface border border-cyber-green/20 rounded">
      {tags.map(tag => (
        <span key={tag} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-cyber-green/10 border border-cyber-green/20 rounded text-[10px] font-mono text-cyber-green/80">
          {tag}
          <button type="button" onClick={() => removeTag(tag)} className="text-cyber-green/40 hover:text-red-400">
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
        className="flex-1 min-w-[80px] bg-transparent text-cyber-green text-xs font-mono focus:outline-none placeholder:text-cyber-green/20"
      />
    </div>
  );
}

function EffectEditor({ effect, onChange, onDelete, index, eventOptions }) {
  const update = (k, v) => onChange({ ...effect, [k]: v });
  const t = effect.effect_type || 'modify_state';
  const unavailable = UNAVAILABLE_EFFECT_TYPES.has(t);

  return (
    <div className="space-y-3 rounded border border-cyber-green/10 bg-cyber-surface/40 p-3 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2">
          <span className="text-[10px] font-mono text-cyber-green/40">效果 #{index + 1}</span>
          <select
            value={t}
            onChange={e => onChange({ ...cloneJson(DEFAULT_EFFECT), effect_type: e.target.value })}
            className="min-h-11 min-w-0 rounded border border-cyber-green/30 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/60 focus:outline-none"
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
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-cyber-green/30 transition-colors hover:text-red-400"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {unavailable && (
        <div className="flex items-start gap-2 rounded border border-amber-300/20 bg-amber-300/5 p-3 text-[10px] font-mono text-amber-200/70">
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
                className="min-h-11 min-w-0 rounded border border-cyber-green/20 bg-cyber-surface px-2 text-[11px] font-mono text-cyber-green"
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
                  className="min-h-11 min-w-0 rounded border border-cyber-green/20 bg-cyber-surface px-2 text-[11px] font-mono text-cyber-green"
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
                  className="min-h-11 min-w-0 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
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
                className="inline-flex h-11 w-11 items-center justify-center text-cyber-green/30 hover:text-red-400"
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
            className="flex min-h-11 items-center gap-1 text-[10px] font-mono text-cyber-green/45 hover:text-cyber-green disabled:opacity-30"
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
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
          <input
            type="text"
            value={effect.dialogue_action || ''}
            onChange={e => update('dialogue_action', e.target.value)}
            placeholder="动作描述"
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
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
            className="w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-mono text-cyber-green/40">重要性</label>
            <input
              type="number"
              value={effect.memory_importance ?? 5}
              onChange={e => update('memory_importance', Number(e.target.value))}
              min={1} max={10}
              className="min-h-11 w-20 rounded border border-cyber-green/20 bg-cyber-surface px-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
            />
          </div>
        </div>
      )}

      {t === 'change_mood' && (
        <select
          value={effect.target_mood || 'neutral'}
          onChange={e => update('target_mood', e.target.value)}
          className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green sm:max-w-xs"
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
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
          <select
            value={effect.notification_type || 'info'}
            onChange={e => update('notification_type', e.target.value)}
            className="min-h-11 rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green/70"
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
          <label className="block text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">默认后续事件（无分支命中时，可选）</span>
            <EventDependencySelect
              value={effect.next_event_id}
              onChange={value => update('next_event_id', value)}
              eventOptions={eventOptions}
              placeholder="不设置默认事件"
            />
          </label>
          {(effect.branch_conditions || []).map((branch, branchIndex) => (
            <div key={branchIndex} className="space-y-3 border-l-2 border-cyber-green/10 pl-3 sm:pl-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-mono text-cyber-green/40">分支 #{branchIndex + 1}</span>
                <button
                  type="button"
                  onClick={() => update(
                    'branch_conditions',
                    (effect.branch_conditions || []).filter((_, itemIndex) => itemIndex !== branchIndex)
                  )}
                  aria-label={`删除分支 ${branchIndex + 1}`}
                  title="删除分支"
                  className="inline-flex h-11 w-11 items-center justify-center text-cyber-green/30 hover:text-red-400"
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
            className="flex min-h-11 items-center gap-1 rounded border border-cyber-green/20 px-3 text-[10px] font-mono text-cyber-green/50 hover:text-cyber-green"
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
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
          <input
            type="text"
            value={effect.target_session_id || ''}
            onChange={e => update('target_session_id', e.target.value)}
            placeholder="目标会话 ID（可选）"
            className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
          <textarea
            value={effect.proactive_prompt || ''}
            onChange={e => update('proactive_prompt', e.target.value)}
            placeholder="主动发言提示"
            rows={2}
            className="w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
          />
        </div>
      )}

      {t === 'update_event_progress' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">直接进度（0 到 1）</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={effect.progress ?? ''}
              onChange={e => update('progress', e.target.value === '' ? null : Number(e.target.value))}
              className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green focus:border-cyber-green/50 focus:outline-none"
            />
          </label>
          <label className="text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">进度变化量</span>
            <input
              type="number"
              step="0.01"
              value={effect.progress_delta ?? ''}
              onChange={e => update('progress_delta', e.target.value === '' ? null : Number(e.target.value))}
              className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green focus:border-cyber-green/50 focus:outline-none"
            />
          </label>
          <label className="text-[10px] font-mono text-cyber-green/40">
            <span className="mb-1 block">阶段状态</span>
            <select
              value={effect.event_status || ''}
              onChange={e => update('event_status', e.target.value)}
              className="min-h-11 w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs text-cyber-green"
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
  const isExistingEvent = !!eventId && eventId !== 'new';
  const eventRequestRef = useRef(0);
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

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState('');

  const selectedTemplate = useMemo(
    () => templates.find(t => t.template_id === selectedTemplateId),
    [templates, selectedTemplateId]
  );
  const eventOptions = useMemo(
    () => events.filter(event => event.event_id !== (eventId && eventId !== 'new' ? eventId : form.event_id)),
    [events, eventId, form.event_id]
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
      setLoadedEventId('new');
      setLoading(false);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setLoadedEventId(null);
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
      setTimeout(() => navigate('/events'), 600);
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

  if (loading) {
    return (
      <div className="min-h-dvh memoria-page memoria-app-page flex items-center justify-center">
        <Loader2 className="animate-spin text-cyber-green" size={32} />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="min-h-dvh memoria-page memoria-app-page flex items-center justify-center px-6">
        <div className="memoria-panel w-full max-w-md p-6 text-center">
          <AlertCircle className="mx-auto text-red-400/80" size={32} />
          <h1 className="mt-4 font-display text-base text-cyber-green tracking-[0.16em]">
            EVENT LOAD FAILED
          </h1>
          <p className="mt-2 break-words text-xs font-mono text-red-300/80">{loadError}</p>
          <div className="mt-5 flex justify-center gap-3">
            <button
              onClick={() => navigate('/events')}
              className="memoria-button"
            >
              <ArrowLeft size={14} />
              返回
            </button>
            <button
              onClick={() => setReloadVersion(value => value + 1)}
              className="memoria-button memoria-button-primary"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  const updateField = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  const actionPending = saving || deleting;
  const saveDisabled = actionPending || (isExistingEvent && loadedEventId !== eventId);

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

  return (
    <div className="min-h-dvh memoria-page memoria-app-page">
      {/* Header */}
      <div className="memoria-app-header sticky top-0 z-20 border-b">
        <div className="mx-auto grid max-w-6xl grid-cols-[auto_1fr_auto] items-center gap-2 px-4 py-3 sm:gap-4 sm:px-6 sm:py-4">
          <button
            onClick={() => navigate('/events')}
            aria-label="返回事件列表"
            title="返回事件列表"
            className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-1 text-sm font-mono text-cyber-green/60 transition-colors hover:text-cyber-green"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline">Events</span>
          </button>
          <div className="min-w-0 text-center">
            <h1 className="font-display text-sm text-cyber-green tracking-[0.16em] sm:text-base sm:tracking-[0.25em]">
              {eventId && eventId !== 'new' ? 'EDIT EVENT' : 'NEW EVENT'}
            </h1>
            {form.event_id && (
              <p className="mt-0.5 hidden truncate text-[10px] font-mono text-cyber-green/30 sm:block">
                {form.event_id}
              </p>
            )}
          </div>
          <div className="flex items-center justify-end gap-1.5 sm:gap-2">
            {eventId && eventId !== 'new' && (
              <button
                onClick={handleDelete}
                disabled={actionPending || loadedEventId !== eventId}
                aria-label="删除事件"
                title="删除事件"
                className="inline-flex min-h-[44px] items-center justify-center rounded border border-red-400/20 px-2 text-xs font-mono text-red-400/60 transition-colors hover:border-red-400/40 hover:text-red-400 sm:px-3"
              >
                {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                <span className="ml-1 hidden sm:inline">Delete</span>
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={saveDisabled}
              aria-label="保存事件"
              title="保存事件"
              className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-1 rounded border border-cyber-green/30 bg-cyber-green/10 px-2 text-xs font-mono text-cyber-green transition-colors hover:bg-cyber-green/20 disabled:opacity-50 sm:px-4 sm:text-sm"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              <span className="hidden sm:inline">Save</span>
            </button>
          </div>
        </div>
      </div>

      {/* Save message */}
      {saveMsg && (
        <div className={`fixed left-4 right-4 top-16 z-30 mx-auto max-w-2xl break-words rounded border px-4 py-2 font-mono text-xs shadow-lg sm:left-1/2 sm:right-auto sm:w-max sm:max-w-[calc(100vw-2rem)] sm:-translate-x-1/2 ${
          saveMsgKind === 'error'
            ? 'border-red-400/20 bg-red-950/95 text-red-300'
            : saveMsgKind === 'success'
              ? 'border-cyber-green/20 bg-cyber-bg/95 text-cyber-green'
              : 'border-sky-300/20 bg-cyber-bg/95 text-sky-200/75'
        }`}>
          {saveMsg}
        </div>
      )}

      {/* Form content */}
      <div className="mx-auto max-w-5xl px-4 py-5 sm:px-6 sm:py-8">
        <div className="space-y-6">
          {unavailableConfiguration.length > 0 && (
            <div className="flex items-start gap-3 rounded border border-amber-300/25 bg-amber-300/5 p-4 text-xs font-mono text-amber-100/75">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="font-medium text-amber-100/90">存在不可用的旧配置，当前禁止保存</p>
                <p className="mt-1 break-words text-[10px] leading-5">
                  {unavailableConfiguration.join('；')}。原字段不会被静默替换，请在对应位置切换类型。
                </p>
              </div>
            </div>
          )}

          {validationWarnings.length > 0 && (
            <div className="flex items-start gap-3 rounded border border-sky-300/15 bg-sky-300/5 p-4 text-[10px] font-mono text-sky-100/60">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <p className="min-w-0 break-words">{validationWarnings.join('；')}</p>
            </div>
          )}

          {/* Basic info card */}
          <div className="space-y-4 rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-4 sm:p-6">
            <h2 className="font-mono text-sm text-cyber-green/70 flex items-center gap-2">
              <Zap size={14} />
              基本信息
            </h2>

            <div className="border-b border-cyber-green/10 pb-4">
              <div className="flex flex-col sm:flex-row sm:items-end gap-3">
                <div className="flex-1">
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">系统模板</label>
                  <select
                    value={selectedTemplateId}
                    onChange={e => setSelectedTemplateId(e.target.value)}
                    disabled={templatesLoading}
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none disabled:opacity-50"
                  >
                    <option value="">{templatesLoading ? '加载模板中...' : '不使用模板'}</option>
                    {templates.map(template => (
                      <option key={template.template_id} value={template.template_id}>
                        {template.category ? `[${template.category}] ` : ''}{template.template_name}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={handleApplyTemplate}
                  disabled={!selectedTemplate || templatesLoading}
                  className="flex min-h-[44px] items-center justify-center gap-1 rounded border border-cyber-green/30 px-3 text-xs font-mono text-cyber-green/70 transition-colors hover:border-cyber-green/50 hover:text-cyber-green disabled:opacity-40 disabled:hover:border-cyber-green/30 disabled:hover:text-cyber-green/70"
                >
                  <Wand2 size={14} />
                  应用模板
                </button>
              </div>
              {templatesError && (
                <p className="mt-2 text-[10px] font-mono text-red-400/70">{templatesError}</p>
              )}
              {selectedTemplate?.description && (
                <p className="mt-2 text-[10px] font-mono text-cyber-green/35">{selectedTemplate.description}</p>
              )}
              {selectedTemplate && (
                <div className="mt-3 border-t border-cyber-green/10 pt-3">
                  <p className="mb-2 text-[10px] font-mono uppercase tracking-[0.15em] text-cyber-green/30">
                    模板预览
                  </p>
                  <PipelinePreview
                    triggerCondition={selectedTemplate.trigger_config}
                    effects={selectedTemplate.effects_config || []}
                  />
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">事件 ID *</label>
                <input
                  type="text"
                  value={form.event_id}
                  onChange={e => updateField('event_id', e.target.value)}
                  disabled={!!(eventId && eventId !== 'new')}
                  placeholder="evt_charactername_eventname"
                  className="min-h-[44px] w-full rounded border border-cyber-green/30 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/60 focus:outline-none disabled:opacity-40"
                />
              </div>
              <div>
                <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">事件名称 *</label>
                <input
                  type="text"
                  value={form.event_name}
                  onChange={e => updateField('event_name', e.target.value)}
                  placeholder="例如：初次见面的惊喜"
                  className="min-h-[44px] w-full rounded border border-cyber-green/30 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/60 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">描述</label>
              <textarea
                value={form.description}
                onChange={e => updateField('description', e.target.value)}
                placeholder="事件的简要描述..."
                rows={2}
                className="w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
              />
            </div>

            {/* Advanced */}
            <button
              onClick={() => setAdvancedOpen(!advancedOpen)}
              type="button"
              aria-expanded={advancedOpen}
              className="flex min-h-11 items-center gap-1 text-[10px] font-mono text-cyber-green/40 transition-colors hover:text-cyber-green/70"
            >
              {advancedOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              高级设置
            </button>
            {advancedOpen && (
              <div className="grid grid-cols-1 gap-4 pt-2 sm:grid-cols-2 lg:grid-cols-3">
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">关联角色 ID</label>
                  <input
                    type="text"
                    value={form.character_id}
                    onChange={e => updateField('character_id', e.target.value)}
                    placeholder="留空=全局事件"
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">优先级</label>
                  <input
                    type="number"
                    value={form.priority}
                    onChange={e => updateField('priority', Number(e.target.value))}
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">互斥组</label>
                  <input
                    type="text"
                    value={form.exclusive_group}
                    onChange={e => updateField('exclusive_group', e.target.value)}
                    placeholder="同组每轮仅触发最高优先级"
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">每轮最多触发</label>
                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={form.max_triggers_per_turn}
                    onChange={e => updateField('max_triggers_per_turn', Number(e.target.value))}
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
                  />
                </div>
                <div className="sm:col-span-2 lg:col-span-2">
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">调度 Cron（5 字段）</label>
                  <input
                    type="text"
                    value={form.schedule}
                    onChange={e => updateField('schedule', e.target.value)}
                    placeholder="0 9 * * *；必须绑定角色"
                    className="min-h-[44px] w-full rounded border border-cyber-green/20 bg-cyber-surface px-3 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none"
                  />
                </div>
                <div className="flex flex-col justify-end gap-2 sm:flex-row sm:items-center lg:flex-col lg:items-start">
                  <label className="flex min-h-11 cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={e => updateField('is_active', e.target.checked)}
                      className="accent-cyber-green"
                    />
                    <span className="text-[10px] font-mono text-cyber-green/40">启用事件</span>
                  </label>
                  <label className="flex min-h-11 cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.stop_processing}
                      onChange={e => updateField('stop_processing', e.target.checked)}
                      className="accent-cyber-green"
                    />
                    <span className="text-[10px] font-mono text-cyber-green/40">触发后停止处理后续事件</span>
                  </label>
                </div>
              </div>
            )}
          </div>

          {/* Trigger condition card */}
          <div className="space-y-4 rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-4 sm:p-6">
            <h2 className="font-mono text-sm text-cyber-green/70">触发条件</h2>
            {eventsLoading && (
              <p className="text-[10px] font-mono text-cyber-green/30">正在加载事件依赖...</p>
            )}
            {eventsError && (
              <p className="break-words text-[10px] font-mono text-red-300/70">{eventsError}</p>
            )}
            <TriggerConditionForm
              condition={form.trigger_condition}
              onChange={v => updateField('trigger_condition', v)}
              eventOptions={eventOptions}
            />
          </div>

          {/* Pipeline preview */}
          <div className="rounded-lg border border-cyber-green/10 bg-cyber-surface/20 p-4">
            <p className="text-[10px] font-mono text-cyber-green/30 mb-2 uppercase tracking-[0.15em]">Pipeline Preview</p>
            <PipelinePreview
              triggerCondition={form.trigger_condition}
              effects={form.effects}
            />
          </div>

          {/* Effects card */}
          <div className="space-y-4 rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-4 sm:p-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="font-mono text-sm text-cyber-green/70">事件效果</h2>
              <button
                onClick={() => updateField('effects', [...form.effects, { ...DEFAULT_EFFECT }])}
                className="flex min-h-11 items-center justify-center gap-1 rounded border border-cyber-green/20 px-3 text-[10px] font-mono text-cyber-green/50 transition-colors hover:text-cyber-green"
              >
                <Plus size={12} /> 添加效果
              </button>
            </div>
            {form.effects.length === 0 && (
              <p className="text-xs text-cyber-green/30 font-mono">暂无效果配置，点击上方按钮添加</p>
            )}
            {form.effects.map((eff, i) => (
              <EffectEditor
                key={i}
                index={i}
                effect={eff}
                eventOptions={eventOptions}
                onChange={v => {
                  const effects = [...form.effects];
                  effects[i] = v;
                  updateField('effects', effects);
                }}
                onDelete={() => {
                  updateField('effects', form.effects.filter((_, j) => j !== i));
                }}
              />
            ))}
          </div>

          {isExistingEvent && loadedEventId === eventId && (
            <EventOperationsPanel eventId={eventId} characterId={form.character_id} />
          )}

          {/* Bottom save */}
          <div className="flex justify-stretch sm:justify-end">
            <button
              onClick={handleSave}
              disabled={saveDisabled}
              className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded border border-cyber-green/30 bg-cyber-green/10 px-6 text-sm font-mono text-cyber-green transition-colors hover:bg-cyber-green/20 disabled:opacity-50 sm:w-auto"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save Event
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
