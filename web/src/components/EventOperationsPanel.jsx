import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  History,
  Loader2,
  Pause,
  Play,
  RotateCcw,
} from 'lucide-react';
import { eventAdmin } from '../api/memoria';

const TABS = [
  { id: 'simulate', label: '模拟', icon: Play },
  { id: 'schedule', label: '调度', icon: CalendarClock },
  { id: 'history', label: '指标与历史', icon: History },
];

const EMPTY_SIMULATION = {
  character_id: '',
  session_id: '',
  player_message: '',
  npc_response: '',
  current_affinity: 0,
  current_trust: 0,
  current_mood: 'neutral',
  previous_affinity: '',
  previous_trust: '',
  affinity_delta: '',
  trust_delta: '',
  dialogue_count: '',
  total_dialogue_count: '',
  session_duration_minutes: '',
  world_time: '',
  unlocked_content: '[]',
  character_relationships: '{}',
  event_history: '[]',
  event_data: '{}',
};

const METRIC_LABELS = [
  ['matched_count', '匹配'],
  ['succeeded_count', '成功'],
  ['failed_count', '失败'],
  ['partial_count', '部分成功'],
  ['skipped_count', '跳过'],
  ['deduplicated_count', '幂等拦截'],
  ['average_duration_ms', '平均耗时 ms'],
];

const MOODS = [
  'happy',
  'sad',
  'angry',
  'fearful',
  'surprised',
  'disgusted',
  'neutral',
  'excited',
  'nervous',
  'calm',
];

function parseJsonField(value, label, expected) {
  let parsed;
  try {
    parsed = JSON.parse(value || (expected === 'array' ? '[]' : '{}'));
  } catch (error) {
    throw new Error(`${label} JSON 格式不正确`);
  }
  if (expected === 'array' && !Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 数组`);
  }
  if (expected === 'object' && (Array.isArray(parsed) || parsed == null || typeof parsed !== 'object')) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed;
}

function optionalNumber(value) {
  return value === '' || value == null ? undefined : Number(value);
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}

function JsonPreview({ value }) {
  if (value == null) return null;
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/30 p-3 font-archive-mono text-[10px] tabular-nums leading-5 text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function EventOperationsPanel({ eventId, characterId }) {
  const [activeTab, setActiveTab] = useState('simulate');
  const [simulation, setSimulation] = useState(() => ({
    ...EMPTY_SIMULATION,
    character_id: characterId || '',
  }));
  const [simulationResult, setSimulationResult] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const [simulationError, setSimulationError] = useState('');
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState('');
  const [schedules, setSchedules] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [executions, setExecutions] = useState([]);
  const [scheduleAction, setScheduleAction] = useState('');

  useEffect(() => {
    setSimulation(current => ({
      ...current,
      character_id: current.character_id || characterId || '',
    }));
  }, [characterId]);

  async function loadRuntimeData() {
    setRuntimeLoading(true);
    setRuntimeError('');
    try {
      const [scheduleRows, metricData, executionRows] = await Promise.all([
        eventAdmin.schedules(eventId),
        eventAdmin.metrics(eventId),
        eventAdmin.executions(eventId),
      ]);
      setSchedules(Array.isArray(scheduleRows) ? scheduleRows : []);
      setMetrics(metricData || null);
      setExecutions(Array.isArray(executionRows) ? executionRows : []);
    } catch (error) {
      setRuntimeError(error.message || '运行数据加载失败');
    } finally {
      setRuntimeLoading(false);
    }
  }

  useEffect(() => {
    if (activeTab !== 'simulate') loadRuntimeData();
  }, [activeTab, eventId]);

  const conditionTrace = useMemo(
    () => simulationResult?.evaluation?.condition || null,
    [simulationResult]
  );

  async function handleSimulate() {
    setSimulating(true);
    setSimulationError('');
    setSimulationResult(null);
    try {
      const payload = {
        character_id: simulation.character_id.trim() || undefined,
        session_id: simulation.session_id.trim() || undefined,
        player_message: simulation.player_message,
        npc_response: simulation.npc_response.trim() || undefined,
        current_affinity: optionalNumber(simulation.current_affinity),
        current_trust: optionalNumber(simulation.current_trust),
        current_mood: simulation.current_mood.trim() || undefined,
        previous_affinity: optionalNumber(simulation.previous_affinity),
        previous_trust: optionalNumber(simulation.previous_trust),
        affinity_delta: optionalNumber(simulation.affinity_delta),
        trust_delta: optionalNumber(simulation.trust_delta),
        dialogue_count: optionalNumber(simulation.dialogue_count),
        total_dialogue_count: optionalNumber(simulation.total_dialogue_count),
        session_duration_minutes: optionalNumber(simulation.session_duration_minutes),
        world_time: simulation.world_time.trim() || undefined,
        unlocked_content: parseJsonField(simulation.unlocked_content, '已解锁内容', 'array'),
        character_relationships: parseJsonField(
          simulation.character_relationships,
          '角色关系',
          'object'
        ),
        event_history: parseJsonField(simulation.event_history, '事件历史', 'array'),
        event_data: parseJsonField(simulation.event_data, '事件数据', 'object'),
      };
      setSimulationResult(await eventAdmin.simulate(eventId, payload));
    } catch (error) {
      setSimulationError(error.message || '模拟失败');
    } finally {
      setSimulating(false);
    }
  }

  async function handleScheduleAction(schedule) {
    const key = `${schedule.event_id}:${schedule.character_id}`;
    setScheduleAction(key);
    setRuntimeError('');
    try {
      if (schedule.status === 'paused') {
        await eventAdmin.resumeSchedule(schedule.event_id, schedule.character_id);
      } else {
        await eventAdmin.pauseSchedule(schedule.event_id, schedule.character_id);
      }
      await loadRuntimeData();
    } catch (error) {
      setRuntimeError(error.message || '调度状态更新失败');
    } finally {
      setScheduleAction('');
    }
  }

  const updateSimulation = (key, value) => {
    setSimulation(current => ({ ...current, [key]: value }));
  };

  return (
    <section className="rounded-md border border-border bg-muted/25">
      <div className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-archive-mono text-sm text-foreground">
            <BarChart3 size={14} />
            运行工具
          </h2>
          <p className="mt-1 break-words text-[10px] font-archive-mono text-muted-foreground">
            {eventId}
          </p>
        </div>
        <div className="grid grid-cols-3 rounded-md border border-border p-0.5" role="tablist">
          {TABS.map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex min-h-11 items-center justify-center gap-1.5 rounded-md px-3 text-[10px] font-archive-mono transition-colors ${
                  activeTab === tab.id
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Icon size={13} aria-hidden="true" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === 'simulate' && (
        <div className="space-y-5 p-4 sm:p-6">
          <div className="flex items-start gap-2 border-l-2 border-primary/35 pl-3 text-[10px] font-archive-mono text-muted-foreground">
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            模拟只执行条件判定和效果规划，不写入数据库，不发送通知。
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ['character_id', '角色 ID', 'text'],
              ['session_id', '会话 ID（可选）', 'text'],
              ['current_affinity', '当前好感度', 'number'],
              ['previous_affinity', '上一轮好感度', 'number'],
              ['current_trust', '当前信任度', 'number'],
              ['previous_trust', '上一轮信任度', 'number'],
              ['affinity_delta', '好感度变化量', 'number'],
              ['trust_delta', '信任度变化量', 'number'],
              ['dialogue_count', '当前会话轮数', 'number'],
              ['total_dialogue_count', '历史总轮数', 'number'],
              ['session_duration_minutes', '会话时长（分钟）', 'number'],
              ['world_time', '世界时间 ISO', 'text'],
            ].map(([key, label, type]) => (
              <label key={key} className="min-w-0 text-[10px] font-archive-mono text-muted-foreground">
                <span className="mb-1 block">{label}</span>
                <input
                  type={type}
                  value={simulation[key]}
                  onChange={event => updateSimulation(key, event.target.value)}
                  className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
                />
              </label>
            ))}
            <label className="min-w-0 text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">当前情绪</span>
              <select
                value={simulation.current_mood}
                onChange={event => updateSimulation('current_mood', event.target.value)}
                className="min-h-11 w-full rounded border border-border bg-background px-3 text-xs text-primary focus:border-primary/40 focus:outline-none"
              >
                {MOODS.map(mood => (
                  <option key={mood} value={mood}>{mood}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">玩家消息</span>
              <textarea
                value={simulation.player_message}
                onChange={event => updateSimulation('player_message', event.target.value)}
                rows={3}
                className="w-full rounded border border-border bg-background px-3 py-2 text-xs text-primary focus:border-primary/40 focus:outline-none"
              />
            </label>
            <label className="text-[10px] font-archive-mono text-muted-foreground">
              <span className="mb-1 block">NPC 回复</span>
              <textarea
                value={simulation.npc_response}
                onChange={event => updateSimulation('npc_response', event.target.value)}
                rows={3}
                className="w-full rounded border border-border bg-background px-3 py-2 text-xs text-primary focus:border-primary/40 focus:outline-none"
              />
            </label>
          </div>

          <details className="border-t border-border pt-4">
            <summary className="cursor-pointer text-[10px] font-archive-mono text-muted-foreground">
              高级上下文 JSON
            </summary>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[
                ['unlocked_content', '已解锁内容 JSON'],
                ['character_relationships', '角色关系 JSON'],
                ['event_history', '事件历史 JSON'],
                ['event_data', '事件数据 JSON'],
              ].map(([key, label]) => (
                <label key={key} className="min-w-0 text-[10px] font-archive-mono text-muted-foreground">
                  <span className="mb-1 block">{label}</span>
                  <textarea
                    value={simulation[key]}
                    onChange={event => updateSimulation(key, event.target.value)}
                    rows={4}
                    spellCheck={false}
                    className="w-full rounded border border-border bg-background px-3 py-2 text-[11px] text-primary focus:border-primary/40 focus:outline-none"
                  />
                </label>
              ))}
            </div>
          </details>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={handleSimulate}
              disabled={simulating || !simulation.character_id.trim()}
              className="flex min-h-11 items-center justify-center gap-2 rounded-md border border-primary/35 bg-primary/10 px-5 text-xs font-archive-mono text-primary hover:bg-primary/15 disabled:opacity-40"
            >
              {simulating
                ? <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                : <Play size={14} aria-hidden="true" />}
              运行模拟
            </button>
            {simulationError && (
              <p
                className="min-w-0 break-words text-xs font-archive-mono text-destructive"
                role="alert"
                aria-live="assertive"
              >
                {simulationError}
              </p>
            )}
          </div>

          {simulationResult && (
            <div className="space-y-4 border-t border-border pt-5">
              <div className="flex items-center gap-2 text-xs font-archive-mono">
                {simulationResult.matched ? (
                  <CheckCircle2 size={15} className="text-primary" />
                ) : (
                  <AlertCircle size={15} className="text-primary" />
                )}
                <span className={simulationResult.matched ? 'text-primary' : 'text-foreground'}>
                  {simulationResult.matched ? '条件命中' : '条件未命中'}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="min-w-0">
                  <p className="mb-2 text-[10px] font-archive-mono text-muted-foreground">条件判定轨迹</p>
                  <JsonPreview value={conditionTrace} />
                </div>
                <div className="min-w-0">
                  <p className="mb-2 text-[10px] font-archive-mono text-muted-foreground">规划效果与状态变化</p>
                  <JsonPreview value={simulationResult.planned_result || { effects: [] }} />
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'schedule' && (
        <div className="p-4 sm:p-6">
          {runtimeLoading && !schedules.length ? (
            <Loader2 className="mx-auto animate-spin text-muted-foreground" size={24} />
          ) : schedules.length === 0 ? (
            <p className="text-xs font-archive-mono text-muted-foreground">该事件没有已注册调度。</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-[10px] font-archive-mono">
                <thead className="border-b border-border text-muted-foreground">
                  <tr>
                    <th className="px-2 py-2 font-normal">角色</th>
                    <th className="px-2 py-2 font-normal">Cron</th>
                    <th className="px-2 py-2 font-normal">状态</th>
                    <th className="px-2 py-2 font-normal">下次执行</th>
                    <th className="px-2 py-2 font-normal">最近执行</th>
                    <th className="px-2 py-2 font-normal">最近错误</th>
                    <th className="px-2 py-2 text-right font-normal">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-muted-foreground">
                  {schedules.map(schedule => {
                    const actionKey = `${schedule.event_id}:${schedule.character_id}`;
                    return (
                      <tr key={actionKey}>
                        <td className="max-w-[160px] break-all px-2 py-3">{schedule.character_id}</td>
                        <td className="px-2 py-3">{schedule.schedule}</td>
                        <td className="px-2 py-3">{schedule.status}</td>
                        <td className="px-2 py-3">{formatDate(schedule.next_run_at)}</td>
                        <td className="px-2 py-3">{formatDate(schedule.last_run_at)}</td>
                        <td className="max-w-[220px] break-words px-2 py-3 text-destructive">
                          {schedule.last_error || '—'}
                        </td>
                        <td className="px-2 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleScheduleAction(schedule)}
                            disabled={scheduleAction === actionKey}
                            aria-label={schedule.status === 'paused' ? '恢复调度' : '暂停调度'}
                            title={schedule.status === 'paused' ? '恢复调度' : '暂停调度'}
                            className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-border text-muted-foreground hover:border-primary/40 hover:text-primary disabled:opacity-40"
                          >
                            {scheduleAction === actionKey ? (
                              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                            ) : schedule.status === 'paused' ? (
                              <RotateCcw size={14} aria-hidden="true" />
                            ) : (
                              <Pause size={14} aria-hidden="true" />
                            )}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {runtimeError && (
            <p
              className="mt-4 break-words text-xs font-archive-mono text-destructive"
              role="alert"
              aria-live="assertive"
            >
              {runtimeError}
            </p>
          )}
        </div>
      )}

      {activeTab === 'history' && (
        <div className="space-y-6 p-4 sm:p-6">
          {runtimeLoading && !metrics ? (
            <Loader2 className="mx-auto animate-spin text-muted-foreground" size={24} />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-border bg-primary/10 sm:grid-cols-4 lg:grid-cols-7">
                {METRIC_LABELS.map(([key, label]) => (
                  <div key={key} className="min-w-0 bg-background px-3 py-3">
                    <p className="text-[9px] font-archive-mono text-muted-foreground">{label}</p>
                    <p className="mt-1 break-words text-sm font-archive-mono text-foreground">
                      {metrics?.[key] ?? 0}
                    </p>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-1 gap-2 text-[10px] font-archive-mono text-muted-foreground sm:grid-cols-2">
                <p>最近执行：{formatDate(metrics?.last_execution_at)}</p>
                <p className="break-words text-destructive">最近错误：{metrics?.last_error || '—'}</p>
              </div>
              <div className="overflow-x-auto border-t border-border pt-4">
                <table className="w-full min-w-[820px] text-left text-[10px] font-archive-mono">
                  <thead className="border-b border-border text-muted-foreground">
                    <tr>
                      <th className="px-2 py-2 font-normal">执行 ID</th>
                      <th className="px-2 py-2 font-normal">角色</th>
                      <th className="px-2 py-2 font-normal">会话</th>
                      <th className="px-2 py-2 font-normal">来源</th>
                      <th className="px-2 py-2 font-normal">状态</th>
                      <th className="px-2 py-2 font-normal">耗时 ms</th>
                      <th className="px-2 py-2 font-normal">完成时间</th>
                      <th className="px-2 py-2 font-normal">错误</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border text-muted-foreground">
                    {executions.map(item => (
                      <tr key={item.execution_id}>
                        <td className="max-w-[180px] break-all px-2 py-3">{item.execution_id}</td>
                        <td className="max-w-[140px] break-all px-2 py-3">{item.character_id}</td>
                        <td className="max-w-[160px] break-all px-2 py-3">{item.session_id}</td>
                        <td className="px-2 py-3">{item.trigger_source}</td>
                        <td className="px-2 py-3">{item.status}</td>
                        <td className="px-2 py-3">{item.duration_ms ?? '—'}</td>
                        <td className="px-2 py-3">{formatDate(item.completed_at)}</td>
                        <td className="max-w-[220px] break-words px-2 py-3 text-destructive">
                          {item.error || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!executions.length && (
                  <p className="py-6 text-center text-xs font-archive-mono text-muted-foreground">
                    暂无执行记录
                  </p>
                )}
              </div>
            </>
          )}
          {runtimeError && (
            <p
              className="break-words text-xs font-archive-mono text-destructive"
              role="alert"
              aria-live="assertive"
            >
              {runtimeError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
