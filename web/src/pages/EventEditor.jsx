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
  CheckCircle2,
  Activity,
  Settings2,
  GitBranch,
  Wand2,
} from 'lucide-react';
import { eventAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import SideRays from '../components/SideRays';

const TRIGGER_TYPES = [
  { value: 'affinity_threshold', label: '好感度阈值' },
  { value: 'trust_threshold', label: '信任度阈值' },
  { value: 'keyword_match', label: '关键词匹配' },
  { value: 'dialogue_count', label: '对话次数' },
  { value: 'time_based', label: '时间条件' },
  { value: 'mood_match', label: '情绪匹配' },
  { value: 'relationship_change', label: '关系变化' },
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
  { value: 'grant_item', label: '给予物品' },
  { value: 'start_quest', label: '开启任务' },
  { value: 'modify_relationship', label: '修改关系' },
  { value: 'trigger_event', label: '触发事件链' },
  { value: 'branch_event', label: '分支事件' },
  { value: 'npc_proactive_dialogue', label: 'NPC 主动发言' },
];
const EFFECT_LABELS = Object.fromEntries(EFFECT_TYPES.map(et => [et.value, et.label]));

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
  branch_conditions_text: '',
  target_session_id: '',
  proactive_character_id: '',
  proactive_prompt: '',
};

const DEFAULT_SUB_CONDITION = {
  trigger_type: 'keyword_match',
  threshold: null,
  comparison: 'gte',
  keywords: [],
  match_mode: 'any',
};

const cloneJson = value => JSON.parse(JSON.stringify(value ?? null));

const EDITOR_RAYS_PROPS = {
  speed: 1.45,
  rayColor1: '#A7EF9E',
  rayColor2: '#96c8ff',
  intensity: 1.75,
  spread: 2,
  origin: 'top-right',
  tilt: -10,
  saturation: 1.25,
  blend: 0.68,
  falloff: 1.65,
  opacity: 0.48,
};

const DEFAULT_FORM = {
  event_id: '',
  event_name: '',
  description: '',
  character_id: '',
  trigger_condition: { trigger_type: 'keyword_match', keywords: [], match_mode: 'any', cooldown_hours: 0 },
  effects: [],
  priority: 0,
  is_active: true,
  template_id: '',
};

function makeEventId(name) {
  const slug = String(name || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
  return `evt_${slug || 'custom_event'}`;
}

function snapshotForm(form) {
  return JSON.stringify(form);
}

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
    trigger_condition: form.trigger_condition || DEFAULT_FORM.trigger_condition,
    effects: (form.effects || []).map(sanitizeEffect),
  };
}

function validateEventForm(form) {
  const errors = [];
  const condition = form.trigger_condition || {};
  const triggerType = condition.trigger_type;

  if (!String(form.event_id || '').trim()) errors.push('事件 ID 必填');
  if (!String(form.event_name || '').trim()) errors.push('事件名称必填');

  if (triggerType === 'keyword_match' && !(condition.keywords || []).length) {
    errors.push('关键词触发需要至少 1 个关键词');
  }
  if ((triggerType === 'affinity_threshold' || triggerType === 'trust_threshold') && condition.threshold == null) {
    errors.push('阈值触发需要填写阈值');
  }
  if (triggerType === 'dialogue_count' && !condition.count) {
    errors.push('对话次数触发需要填写次数');
  }
  if (triggerType === 'time_based' && !condition.duration_minutes && !condition.schedule) {
    errors.push('时间触发需要填写分钟数或计划表达式');
  }
  if (triggerType === 'composite' && !(condition.sub_conditions || []).length) {
    errors.push('复合条件需要至少 1 个子条件');
  }

  (form.effects || []).forEach((effect, index) => {
    const label = `效果 #${index + 1}`;
    if (effect.effect_type === 'trigger_event' && !String(effect.next_event_id || '').trim()) {
      errors.push(`${label} 需要填写后续事件 ID`);
    }
    if (effect.effect_type === 'branch_event' && effect.branch_conditions_text) {
      try {
        JSON.parse(effect.branch_conditions_text);
      } catch (err) {
        errors.push(`${label} 的分支 JSON 格式不正确`);
      }
    }
    if (effect.effect_type === 'npc_proactive_dialogue' && !String(effect.proactive_prompt || '').trim()) {
      errors.push(`${label} 需要填写主动发言提示`);
    }
  });

  const warnings = [];
  if (!form.effects?.length) warnings.push('当前事件没有效果，触发后不会产生动作');
  if (!form.description?.trim()) warnings.push('建议补充描述，便于后续维护');

  return { errors, warnings };
}


// ─── Key-Value Pair Editor ───────────────────────────────────────────────
function KeyValueEditor({ data, onChange, keyLabel, valueLabel }) {
  const entries = Object.entries(data || {});

  function handleAdd() {
    onChange({ ...data, '': '' });
  }

  function handleChange(oldKey, newKey, newValue) {
    const result = {};
    for (const [k, v] of Object.entries(data)) {
      if (k === oldKey) {
        if (newKey.trim()) result[newKey.trim()] = newValue;
      } else {
        result[k] = v;
      }
    }
    onChange(result);
  }

  function handleDelete(key) {
    const result = { ...data };
    delete result[key];
    onChange(result);
  }

  return (
    <div className="space-y-1">
      {entries.length === 0 && (
        <p className="text-[10px] font-mono text-cyber-green/15 italic">暂无条目</p>
      )}
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center gap-1.5 group">
          <input
            type="text"
            value={key}
            onChange={e => handleChange(key, e.target.value, value)}
            placeholder={keyLabel || '键'}
            className="flex-1 bg-cyber-surface border border-cyber-green/15 text-cyber-green text-[11px] font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/40 placeholder:text-cyber-green/15"
          />
          <span className="text-cyber-green/20 text-[10px]">=</span>
          <input
            type="text"
            value={value}
            onChange={e => handleChange(key, key, e.target.value)}
            placeholder={valueLabel || '值'}
            className="flex-1 bg-cyber-surface border border-cyber-green/15 text-cyber-green text-[11px] font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/40 placeholder:text-cyber-green/15"
          />
          <button
            type="button"
            onClick={() => handleDelete(key)}
            className="text-cyber-green/15 hover:text-red-400/60 transition-colors shrink-0 opacity-0 group-hover:opacity-100"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={handleAdd}
        className="text-[10px] font-mono text-cyber-green/35 hover:text-cyber-green/70 flex items-center gap-1 transition-colors"
      >
        <Plus size={10} /> 添加条目
      </button>
    </div>
  );
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

function SubConditionEditor({ condition, onChange, onDelete, depth = 0 }) {
  return (
    <div className="ml-4 pl-4 border-l-2 border-cyber-green/10 rounded">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-mono text-cyber-green/40">子条件</span>
        <button type="button" onClick={onDelete} className="text-cyber-green/20 hover:text-red-400 transition-colors">
          <Trash2 size={10} />
        </button>
      </div>
      <TriggerConditionForm
        condition={condition}
        onChange={onChange}
        isSub={true}
        depth={depth + 1}
      />
    </div>
  );
}

function TriggerConditionForm({ condition, onChange, isSub = false, depth = 0 }) {
  const update = (k, v) => onChange({ ...condition, [k]: v });
  const t = condition.trigger_type;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={t}
          onChange={e => onChange({ ...DEFAULT_SUB_CONDITION, trigger_type: e.target.value })}
          className="bg-cyber-surface border border-cyber-green/30 text-cyber-green text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:border-cyber-green/60"
        >
          {TRIGGER_TYPES.filter(tt => isSub ? tt.value !== 'composite' : true).map(tt => (
            <option key={tt.value} value={tt.value}>{tt.label}</option>
          ))}
        </select>
      </div>

      {/* Threshold-based: affinity, trust, dialogue_count, time_based */}
      {(t === 'affinity_threshold' || t === 'trust_threshold' || t === 'dialogue_count' || t === 'time_based') && (
        <div className="flex items-center gap-2">
          <select
            value={condition.comparison || 'gte'}
            onChange={e => update('comparison', e.target.value)}
            className="bg-cyber-surface border border-cyber-green/20 text-cyber-green/70 text-xs font-mono rounded px-2 py-1"
          >
            {COMPARISONS.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <input
            type="number"
            value={t === 'time_based' ? (condition.duration_minutes || '') : (t === 'dialogue_count' ? (condition.count || '') : (condition.threshold ?? ''))}
            onChange={e => {
              const v = e.target.value === '' ? null : Number(e.target.value);
              if (t === 'time_based') update('duration_minutes', v);
              else if (t === 'dialogue_count') update('count', v);
              else update('threshold', v);
            }}
            placeholder="数值"
            className="bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 w-24 focus:outline-none focus:border-cyber-green/50"
          />
        </div>
      )}

      {/* Keywords */}
      {t === 'keyword_match' && (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <select
              value={condition.match_mode || 'any'}
              onChange={e => update('match_mode', e.target.value)}
              className="bg-cyber-surface border border-cyber-green/20 text-cyber-green/70 text-xs font-mono rounded px-2 py-0.5"
            >
              <option value="any">任一匹配</option>
              <option value="all">全部匹配</option>
            </select>
          </div>
          <TagInput
            tags={condition.keywords || []}
            onChange={v => update('keywords', v)}
            placeholder="输入关键词按 Enter 添加"
          />
        </div>
      )}

      {/* Mood */}
      {t === 'mood_match' && (
        <select
          value={condition.mood || 'neutral'}
          onChange={e => update('mood', e.target.value)}
          className="bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1"
        >
          {MOODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      )}

      {/* Relationship change */}
      {t === 'relationship_change' && (
        <div className="text-xs text-cyber-green/40 font-mono">关系变化触发（自动检测）</div>
      )}

      {/* Cooldown */}
      <div className="flex items-center gap-2">
        <label className="text-[10px] font-mono text-cyber-green/40">冷却时间</label>
        <input
          type="number"
          value={condition.cooldown_hours ?? 0}
          onChange={e => update('cooldown_hours', Math.max(0, Number(e.target.value)))}
          className="bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 w-16 focus:outline-none focus:border-cyber-green/50"
        />
        <span className="text-[10px] text-cyber-green/30">小时 (0=一次性)</span>
      </div>

      {/* Composite: recurse */}
      {t === 'composite' && !isSub && (
        <div className="space-y-2 mt-3">
          <div className="flex items-center gap-2">
            <select
              value={condition.logic_operator || 'and'}
              onChange={e => update('logic_operator', e.target.value)}
              className="bg-cyber-surface border border-cyber-green/20 text-cyber-green/70 text-xs font-mono rounded px-2 py-1"
            >
              <option value="and">AND（全部满足）</option>
              <option value="or">OR（任一满足）</option>
            </select>
            <button
              type="button"
              onClick={() => {
                const subs = [...(condition.sub_conditions || []), { ...DEFAULT_SUB_CONDITION }];
                update('sub_conditions', subs);
              }}
              className="flex items-center gap-1 text-[10px] font-mono text-cyber-green/50 hover:text-cyber-green border border-cyber-green/20 rounded px-2 py-0.5 transition-colors"
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

function EffectEditor({ effect, onChange, onDelete, index }) {
  const update = (k, v) => onChange({ ...effect, [k]: v });
  const t = effect.effect_type;

  return (
    <div className="p-4 bg-cyber-surface/40 rounded border border-cyber-green/10 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-cyber-green/40">效果 #{index + 1}</span>
          <select
            value={t}
            onChange={e => onChange({ ...DEFAULT_EFFECT, effect_type: e.target.value })}
            className="bg-cyber-surface border border-cyber-green/30 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/60"
          >
            {EFFECT_TYPES.map(et => (
              <option key={et.value} value={et.value}>{et.label}</option>
            ))}
          </select>
        </div>
        <button type="button" onClick={onDelete} className="text-cyber-green/20 hover:text-red-400 transition-colors">
          <Trash2 size={14} />
        </button>
      </div>

      {/* Modify state */}
      {t === 'modify_state' && (
        <KeyValueEditor
          data={effect.state_changes || {}}
          onChange={v => update('state_changes', v)}
          keyLabel="状态名"
          valueLabel="值"
        />
      )}

      {/* Unlock content */}
      {t === 'unlock_content' && (
        <TagInput
          tags={effect.unlock_keys || []}
          onChange={v => update('unlock_keys', v)}
          placeholder="解锁内容标识"
        />
      )}

      {/* Trigger dialogue */}
      {t === 'trigger_dialogue' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.dialogue_text || ''}
            onChange={e => update('dialogue_text', e.target.value)}
            placeholder="对话内容"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <input
            type="text"
            value={effect.dialogue_action || ''}
            onChange={e => update('dialogue_action', e.target.value)}
            placeholder="动作描述"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
        </div>
      )}

      {/* Add memory */}
      {t === 'add_memory' && (
        <div className="space-y-2">
          <textarea
            value={effect.memory_text || ''}
            onChange={e => update('memory_text', e.target.value)}
            placeholder="记忆内容"
            rows={2}
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-mono text-cyber-green/40">重要性</label>
            <input
              type="number"
              value={effect.memory_importance ?? 5}
              onChange={e => update('memory_importance', Number(e.target.value))}
              min={1} max={10}
              className="bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 w-16 focus:outline-none focus:border-cyber-green/50"
            />
          </div>
        </div>
      )}

      {/* Change mood */}
      {t === 'change_mood' && (
        <select
          value={effect.target_mood || 'neutral'}
          onChange={e => update('target_mood', e.target.value)}
          className="bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1"
        >
          {MOODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      )}

      {/* Notify player */}
      {t === 'notify_player' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.notification_message || ''}
            onChange={e => update('notification_message', e.target.value)}
            placeholder="通知消息"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <select
            value={effect.notification_type || 'info'}
            onChange={e => update('notification_type', e.target.value)}
            className="bg-cyber-surface border border-cyber-green/20 text-cyber-green/70 text-xs font-mono rounded px-2 py-1"
          >
            <option value="info">Info</option>
            <option value="success">Success</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </div>
      )}

      {/* Grant item */}
      {t === 'grant_item' && (
        <input
          type="text"
          value={effect.item_id || ''}
          onChange={e => update('item_id', e.target.value)}
          placeholder="物品 ID"
          className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
        />
      )}

      {/* Start quest */}
      {t === 'start_quest' && (
        <input
          type="text"
          value={effect.quest_id || ''}
          onChange={e => update('quest_id', e.target.value)}
          placeholder="任务 ID"
          className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
        />
      )}

      {/* Modify relationship */}
      {t === 'modify_relationship' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.target_character_id || ''}
            onChange={e => update('target_character_id', e.target.value)}
            placeholder="目标角色 ID"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <KeyValueEditor
            data={effect.relationship_change || {}}
            onChange={v => update('relationship_change', v)}
            keyLabel="关系属性"
            valueLabel="变化值"
          />
        </div>
      )}

      {/* Trigger another event */}
      {t === 'trigger_event' && (
        <input
          type="text"
          value={effect.next_event_id || ''}
          onChange={e => update('next_event_id', e.target.value)}
          placeholder="后续事件 ID"
          className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
        />
      )}

      {/* Branch event */}
      {t === 'branch_event' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.next_event_id || ''}
            onChange={e => update('next_event_id', e.target.value)}
            placeholder="默认后续事件 ID"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <textarea
            value={effect.branch_conditions_text || JSON.stringify(effect.branch_conditions || [], null, 2)}
            onChange={e => {
              const value = e.target.value;
              try {
                onChange({
                  ...effect,
                  branch_conditions: value.trim() ? JSON.parse(value) : [],
                  branch_conditions_text: value,
                });
              } catch (err) {
                update('branch_conditions_text', value);
              }
            }}
            rows={3}
            placeholder='分支 JSON，例如 [{"event_id":"evt_next","condition":{...}}]'
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50 placeholder:text-cyber-green/18"
          />
        </div>
      )}

      {/* NPC proactive dialogue */}
      {t === 'npc_proactive_dialogue' && (
        <div className="space-y-2">
          <input
            type="text"
            value={effect.proactive_character_id || ''}
            onChange={e => update('proactive_character_id', e.target.value)}
            placeholder="主动发言角色 ID（可选）"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <input
            type="text"
            value={effect.target_session_id || ''}
            onChange={e => update('target_session_id', e.target.value)}
            placeholder="目标会话 ID（可选）"
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
          <textarea
            value={effect.proactive_prompt || ''}
            onChange={e => update('proactive_prompt', e.target.value)}
            placeholder="主动发言提示"
            rows={2}
            className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-cyber-green/50"
          />
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
  const [loadError, setLoadError] = useState('');
  const [loadedEventId, setLoadedEventId] = useState(isExistingEvent ? null : 'new');
  const [reloadVersion, setReloadVersion] = useState(0);
  const [form, setForm] = useState(cloneDefaultForm);

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');

  const selectedTemplate = useMemo(
    () => templates.find(t => t.template_id === selectedTemplateId),
    [templates, selectedTemplateId]
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
    const requestId = ++eventRequestRef.current;
    let cancelled = false;

    setSaveMsg('');
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
          is_active: detail.is_active,
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
      return;
    }
    const validationErrors = validateEventForm(form);
    if (validationErrors.length) {
      setSaveMsg(validationErrors.join('；'));
      return;
    }
    setSaving(true);
    setSaveMsg('');
    try {
      const payload = cloneJson(sanitizeEventPayload(form));
      payload.template_id = sanitizeOptionalString(payload.template_id);
      if (isExistingEvent) {
        await eventAdmin.update(eventId, payload);
      } else {
        await eventAdmin.create(payload);
      }
      setSaveMsg('保存成功！');
      setTimeout(() => navigate('/events'), 600);
    } catch (e) {
      setSaveMsg(`保存失败: ${e.message}`);
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
    try {
      await eventAdmin.delete(eventId);
      navigate('/events');
    } catch (e) {
      setSaveMsg(`删除失败: ${e.message}`);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-cyber-bg flex items-center justify-center">
        <Loader2 className="animate-spin text-cyber-green" size={32} />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-cyber-bg flex items-center justify-center px-6">
        <div className="w-full max-w-md rounded-lg border border-red-400/20 bg-cyber-surface/50 p-6 text-center">
          <AlertCircle className="mx-auto text-red-400/80" size={32} />
          <h1 className="mt-4 font-display text-base text-cyber-green tracking-[0.16em]">
            EVENT LOAD FAILED
          </h1>
          <p className="mt-2 break-words text-xs font-mono text-red-300/80">{loadError}</p>
          <div className="mt-5 flex justify-center gap-3">
            <button
              onClick={() => navigate('/events')}
              className="flex min-h-[40px] items-center gap-2 rounded border border-cyber-green/20 px-4 py-2 text-xs font-mono text-cyber-green/70 hover:border-cyber-green/40 hover:text-cyber-green"
            >
              <ArrowLeft size={14} />
              返回
            </button>
            <button
              onClick={() => setReloadVersion(value => value + 1)}
              className="min-h-[40px] rounded border border-cyber-green/30 bg-cyber-green/10 px-4 py-2 text-xs font-mono text-cyber-green hover:bg-cyber-green/20"
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
  };

  return (
    <div className="min-h-screen bg-cyber-bg">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-cyber-bg/95 backdrop-blur border-b border-cyber-green/15">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <button
            onClick={() => navigate('/events')}
            className="flex items-center gap-1 text-cyber-green/60 hover:text-cyber-green transition-colors font-mono text-sm"
          >
            <ArrowLeft size={16} />
            Events
          </button>
          <div className="text-center">
            <h1 className="font-display text-base text-cyber-green tracking-[0.25em]">
              {eventId && eventId !== 'new' ? 'EDIT EVENT' : 'NEW EVENT'}
            </h1>
            {form.event_id && (
              <p className="text-[10px] font-mono text-cyber-green/30 mt-0.5">{form.event_id}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {eventId && eventId !== 'new' && (
              <button
                onClick={handleDelete}
                disabled={actionPending || loadedEventId !== eventId}
                className="px-3 py-1 text-xs font-mono text-red-400/60 hover:text-red-400 border border-red-400/20 hover:border-red-400/40 rounded transition-colors"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={saveDisabled}
              className="flex items-center gap-1 px-4 py-1.5 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save
            </button>
          </div>
        </div>
      </div>

      {/* Save message */}
      {saveMsg && (
        <div className={`fixed top-16 left-1/2 -translate-x-1/2 z-30 px-4 py-2 rounded font-mono text-sm ${
          saveMsg.includes('失败') ? 'bg-red-900/80 text-red-300' : 'bg-cyber-green/20 text-cyber-green'
        }`}>
          {saveMsg}
        </div>
      )}

      {/* Form content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="space-y-6">
          {/* Basic info card */}
          <div className="rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-6 space-y-4">
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
                    className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/50 disabled:opacity-50"
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
                  className="flex items-center justify-center gap-1 px-3 py-1.5 border border-cyber-green/30 text-cyber-green/70 hover:text-cyber-green hover:border-cyber-green/50 rounded text-xs font-mono transition-colors disabled:opacity-40 disabled:hover:text-cyber-green/70 disabled:hover:border-cyber-green/30"
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
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">事件 ID *</label>
                <input
                  type="text"
                  value={form.event_id}
                  onChange={e => updateField('event_id', e.target.value)}
                  disabled={!!(eventId && eventId !== 'new')}
                  placeholder="evt_charactername_eventname"
                  className="w-full bg-cyber-surface border border-cyber-green/30 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/60 disabled:opacity-40"
                />
              </div>
              <div>
                <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">事件名称 *</label>
                <input
                  type="text"
                  value={form.event_name}
                  onChange={e => updateField('event_name', e.target.value)}
                  placeholder="例如：初次见面的惊喜"
                  className="w-full bg-cyber-surface border border-cyber-green/30 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/60"
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
                className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/50"
              />
            </div>

            {/* Advanced */}
            <button
              onClick={() => setAdvancedOpen(!advancedOpen)}
              className="flex items-center gap-1 text-[10px] font-mono text-cyber-green/40 hover:text-cyber-green/70 transition-colors"
            >
              {advancedOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              高级设置
            </button>
            {advancedOpen && (
              <div className="grid grid-cols-3 gap-4 pt-2">
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">关联角色 ID</label>
                  <input
                    type="text"
                    value={form.character_id}
                    onChange={e => updateField('character_id', e.target.value)}
                    placeholder="留空=全局事件"
                    className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/50"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-mono text-cyber-green/40 mb-1">优先级</label>
                  <input
                    type="number"
                    value={form.priority}
                    onChange={e => updateField('priority', Number(e.target.value))}
                    className="w-full bg-cyber-surface border border-cyber-green/20 text-cyber-green text-xs font-mono rounded px-3 py-1.5 focus:outline-none focus:border-cyber-green/50"
                  />
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={e => updateField('is_active', e.target.checked)}
                      className="accent-cyber-green"
                    />
                    <span className="text-[10px] font-mono text-cyber-green/40">启用事件</span>
                  </label>
                </div>
              </div>
            )}
          </div>

          {/* Trigger condition card */}
          <div className="rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-6 space-y-4">
            <h2 className="font-mono text-sm text-cyber-green/70">触发条件</h2>
            <TriggerConditionForm
              condition={form.trigger_condition}
              onChange={v => updateField('trigger_condition', v)}
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
          <div className="rounded-lg border border-cyber-green/15 bg-cyber-surface/40 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-mono text-sm text-cyber-green/70">事件效果</h2>
              <button
                onClick={() => updateField('effects', [...form.effects, { ...DEFAULT_EFFECT }])}
                className="flex items-center gap-1 text-[10px] font-mono text-cyber-green/50 hover:text-cyber-green border border-cyber-green/20 rounded px-2 py-1 transition-colors"
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

          {/* Bottom save */}
          <div className="flex justify-end">
            <button
              onClick={handleSave}
              disabled={saveDisabled}
              className="flex items-center gap-2 px-6 py-2 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 transition-colors disabled:opacity-50"
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
