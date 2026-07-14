import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Plus,
  Power,
  PowerOff,
  Trash2,
  Loader2,
  Clock,
  Search,
  RefreshCw,
  X,
  Activity,
  Heart,
  ShieldCheck,
  MessageSquare,
  Timer,
  Smile,
  GitBranch,
  Network,
  Hash,
  Edit2,
  Zap,
  ListFilter,
  AlertCircle,
  CheckCircle2,
  CalendarClock,
  Layers3,
} from 'lucide-react';
import { eventAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import { useUser } from '../context/UserContext';
import FadeContent from '../components/FadeContent';

const TRIGGER_TYPES = [
  { value: 'affinity_threshold', label: '好感度阈值', Icon: Heart },
  { value: 'trust_threshold', label: '信任度阈值', Icon: ShieldCheck },
  { value: 'keyword_match', label: '关键词匹配', Icon: Hash },
  { value: 'npc_keyword_match', label: 'NPC 回复关键词', Icon: Hash },
  { value: 'dialogue_count', label: '对话次数', Icon: MessageSquare },
  { value: 'time_based', label: '时间条件', Icon: Timer },
  { value: 'mood_match', label: '情绪匹配', Icon: Smile },
  { value: 'state_delta', label: '状态变化量', Icon: Activity },
  { value: 'event_history', label: '事件历史', Icon: Clock },
  { value: 'world_time_window', label: '世界时间窗口', Icon: CalendarClock },
  { value: 'relationship_change', label: '关系变化', Icon: GitBranch },
  { value: 'composite', label: '复合条件', Icon: Network },
];

const TRIGGER_LABELS = Object.fromEntries(TRIGGER_TYPES.map(type => [type.value, type.label]));
const TRIGGER_ICONS = Object.fromEntries(TRIGGER_TYPES.map(type => [type.value, type.Icon]));

const SORT_OPTIONS = [
  { value: 'priority_desc', label: '优先级高' },
  { value: 'priority_asc', label: '优先级低' },
  { value: 'name_asc', label: '名称 A-Z' },
  { value: 'trigger_desc', label: '触发次数' },
];

const AUTH_ERROR_PATTERN = /认证|未登录|401|token/i;
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

function getSearchText(evt) {
  return [
    evt.event_name,
    evt.event_id,
    evt.description,
    evt.character_id,
    TRIGGER_LABELS[evt.trigger_type],
    evt.trigger_type,
  ].filter(Boolean).join(' ').toLowerCase();
}

function sortEvents(list, sort) {
  const sorted = [...list];
  sorted.sort((a, b) => {
    if (sort === 'priority_asc') return (a.priority || 0) - (b.priority || 0);
    if (sort === 'name_asc') return String(a.event_name || '').localeCompare(String(b.event_name || ''));
    if (sort === 'trigger_desc') return (b.trigger_count || 0) - (a.trigger_count || 0);
    return (b.priority || 0) - (a.priority || 0);
  });
  return sorted;
}

function formatScheduleTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function formatDateTime(value) {
  if (!value) return '暂无';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function describeTrigger(condition, fallbackType) {
  const source = condition || {};
  const type = source.trigger_type || fallbackType;
  if (!type) return '未配置触发条件';
  if (type === 'keyword_match' || type === 'npc_keyword_match') {
    const keywords = Array.isArray(source.keywords) ? source.keywords.filter(Boolean) : [];
    return keywords.length ? `关键词：${keywords.join('、')}` : '尚未配置关键词';
  }
  if (type === 'affinity_threshold' || type === 'trust_threshold' || type === 'dialogue_count') {
    const comparison = {
      gte: '大于等于',
      lte: '小于等于',
      gt: '大于',
      lt: '小于',
      eq: '等于',
    }[source.comparison] || '达到';
    return `${comparison} ${source.threshold ?? '未设置'}`;
  }
  if (type === 'mood_match') return `目标情绪：${source.mood || '未设置'}`;
  if (type === 'time_based') return source.schedule ? `计划：${source.schedule}` : '尚未配置时间计划';
  if (type === 'world_time_window') {
    return `${source.time_window_start || '--:--'} 至 ${source.time_window_end || '--:--'}`;
  }
  if (type === 'event_history') return `关联事件：${source.event_id || '未设置'}`;
  if (type === 'composite') {
    return `${Array.isArray(source.sub_conditions) ? source.sub_conditions.length : 0} 个子条件`;
  }
  return TRIGGER_LABELS[type] || type;
}

function SummaryMetric({ icon: Icon, label, value, tone = 'green' }) {
  const toneClass = tone === 'green'
    ? 'bg-cyber-green/10 text-cyber-green'
    : tone === 'amber'
    ? 'bg-amber-300/10 text-amber-200'
    : 'bg-white/[0.05] text-zinc-400';

  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${toneClass}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-semibold leading-none text-zinc-100 tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-zinc-500">{label}</p>
      </div>
    </div>
  );
}

export default function EventList() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { user, loading: userLoading, worldClock } = useUser();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [triggerFilter, setTriggerFilter] = useState('all');
  const [sort, setSort] = useState('priority_desc');
  const [search, setSearch] = useState('');
  const [busyEventId, setBusyEventId] = useState(null);
  const [notice, setNotice] = useState('');
  const loadRequestRef = useRef(0);
  const [selectedEventId, setSelectedEventId] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const detailRequestRef = useRef(0);

  const loadEvents = useCallback(async ({ soft = false } = {}) => {
    const requestId = ++loadRequestRef.current;
    if (userLoading) {
      if (soft) setRefreshing(true);
      else setLoading(true);
      return;
    }

    if (!user) {
      setEvents([]);
      setError('未提供认证信息');
      setLoading(false);
      setRefreshing(false);
      return;
    }

    try {
      if (soft) setRefreshing(true);
      else setLoading(true);
      setError(null);
      const list = await eventAdmin.list();
      if (loadRequestRef.current !== requestId) return;
      setEvents(Array.isArray(list) ? list : []);
    } catch (e) {
      if (loadRequestRef.current !== requestId) return;
      const message = e.message || '事件列表加载失败';
      setError(message);
      if (AUTH_ERROR_PATTERN.test(message)) setEvents([]);
    } finally {
      if (loadRequestRef.current === requestId) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [userLoading, user?.user_id]);

  useEffect(() => {
    loadEvents();
    return () => { loadRequestRef.current += 1; };
  }, [loadEvents]);

  const loadEventDetail = useCallback(async (eventId, { soft = false } = {}) => {
    if (!eventId) return;
    const requestId = ++detailRequestRef.current;
    if (!soft) {
      setDetailLoading(true);
      setDetailError('');
    }
    try {
      const detail = await eventAdmin.get(eventId);
      if (detailRequestRef.current !== requestId) return;
      setSelectedEvent(detail);
      setEvents(prev => prev.map(event => (
        event.event_id === eventId ? { ...event, ...detail } : event
      )));
    } catch (e) {
      if (!soft && detailRequestRef.current === requestId) {
        setDetailError(e.message || '事件详情加载失败');
      }
    } finally {
      if (detailRequestRef.current === requestId) setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedEventId) {
      loadEventDetail(selectedEventId);
    } else {
      detailRequestRef.current += 1;
      setSelectedEvent(null);
      setDetailError('');
      setDetailLoading(false);
    }
  }, [selectedEventId, loadEventDetail]);

  async function handleToggle(evt) {
    setBusyEventId(evt.event_id);
    setNotice('');
    try {
      await eventAdmin.toggle(evt.event_id, !evt.is_active);
      setEvents(prev => prev.map(e =>
        e.event_id === evt.event_id ? { ...e, is_active: !e.is_active } : e
      ));
      setSelectedEvent(prev => (
        prev?.event_id === evt.event_id ? { ...prev, is_active: !evt.is_active } : prev
      ));
      setNotice(!evt.is_active ? '事件已启用' : '事件已禁用');
      window.setTimeout(() => setNotice(''), 1800);
    } catch (e) {
      const message = e.message || '切换事件状态失败';
      setError(message);
      if (AUTH_ERROR_PATTERN.test(message)) setEvents([]);
    } finally {
      setBusyEventId(null);
    }
  }

  async function handleDelete(evt) {
    const ok = await dialog.confirm({
      title: '删除事件',
      message: `确定删除事件「${evt.event_name || evt.event_id}」吗？\n此操作不可撤销。`,
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;
    setBusyEventId(evt.event_id);
    setNotice('');
    try {
      await eventAdmin.delete(evt.event_id);
      setEvents(prev => prev.filter(e => e.event_id !== evt.event_id));
      setNotice('事件已删除');
      window.setTimeout(() => setNotice(''), 1800);
    } catch (e) {
      const message = e.message || '删除事件失败';
      setError(message);
      if (AUTH_ERROR_PATTERN.test(message)) setEvents([]);
    } finally {
      setBusyEventId(null);
    }
  }

  const filtered = useMemo(() => {
    let list = events;
    if (filter === 'active') list = list.filter(e => e.is_active);
    if (filter === 'disabled') list = list.filter(e => !e.is_active);
    if (triggerFilter !== 'all') list = list.filter(e => e.trigger_type === triggerFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(e => getSearchText(e).includes(q));
    }
    return sortEvents(list, sort);
  }, [events, filter, triggerFilter, search, sort]);

  useEffect(() => {
    if (loading) return;
    if (filtered.length === 0) {
      setSelectedEventId(null);
      setSelectedEvent(null);
      return;
    }
    if (!selectedEventId || !filtered.some(event => event.event_id === selectedEventId)) {
      setSelectedEvent(filtered[0]);
      setSelectedEventId(filtered[0].event_id);
    }
  }, [filtered, loading, selectedEventId]);

  const activeCount = events.filter(e => e.is_active).length;
  const disabledCount = Math.max(0, events.length - activeCount);
  const totalTriggers = events.reduce((sum, evt) => sum + (Number(evt.trigger_count) || 0), 0);
  const hasFilters = filter !== 'all' || triggerFilter !== 'all' || !!search.trim();
  const isAuthError = !!error && AUTH_ERROR_PATTERN.test(error);
  const isAuthBlocked = !user || isAuthError;
  const selectedSummary = events.find(event => event.event_id === selectedEventId) || null;
  const eventDetail = selectedEvent?.event_id === selectedEventId ? selectedEvent : selectedSummary;

  function clearFilters() {
    setSearch('');
    setFilter('all');
    setTriggerFilter('all');
  }

  return (
    <div className="memoria-page memoria-app-page relative min-h-dvh overflow-x-hidden font-character text-zinc-100">
      <a href="#event-workspace" className="memoria-skip-link">跳到事件工作区</a>

      <header className="memoria-app-header sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-[1480px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/')}
            aria-label="返回首页"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] text-zinc-400 transition-colors hover:border-cyber-green/25 hover:bg-cyber-green/[0.06] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40"
          >
            <ArrowLeft size={18} />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Zap size={17} className="shrink-0 text-cyber-green" />
              <h1 className="truncate text-lg font-semibold text-zinc-100 sm:text-xl">事件管理</h1>
            </div>
            <p className="mt-0.5 hidden text-xs text-zinc-500 sm:block">筛选事件、检查触发配置并管理运行状态</p>
          </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => loadEvents({ soft: true })}
              disabled={isAuthBlocked || loading || refreshing}
              aria-label="刷新事件列表"
              title="刷新"
              className="flex h-11 w-11 items-center justify-center rounded-lg border border-white/[0.08] text-zinc-400 transition-colors hover:border-cyber-green/25 hover:bg-cyber-green/[0.06] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            </button>
            <button
              type="button"
              onClick={() => navigate('/events/new')}
              disabled={isAuthBlocked || loading}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyber-green px-3.5 text-sm font-semibold text-[#09100b] transition-colors hover:bg-[#b8f7b0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#090d11] disabled:cursor-not-allowed disabled:opacity-40 sm:px-4"
            >
              <Plus size={17} />
              <span className="hidden sm:inline">新建事件</span>
              <span className="sm:hidden">新建</span>
            </button>
          </div>
        </div>
      </header>

      <main id="event-workspace" className="relative z-10 mx-auto max-w-[1480px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        {notice && (
          <div role="status" aria-live="polite" className="fixed right-4 top-20 z-50 flex items-center gap-2 rounded-lg border border-cyber-green/25 bg-[#111a15] px-4 py-3 text-sm text-cyber-green shadow-2xl animate-fade-up sm:right-6">
            <CheckCircle2 size={16} />
            <span>{notice}</span>
          </div>
        )}

        <FadeContent className="mb-5 border-b border-white/[0.07] pb-5">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
            <SummaryMetric icon={Layers3} label="事件总数" value={events.length} />
            <SummaryMetric icon={Activity} label="已启用" value={activeCount} />
            <SummaryMetric icon={PowerOff} label="已停用" value={disabledCount} tone="muted" />
            <SummaryMetric icon={Clock} label="累计触发" value={totalTriggers} tone="amber" />
          </div>
        </FadeContent>

        <div className="grid items-start gap-4 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)] lg:gap-5">
          <aside className="memoria-panel overflow-hidden">
            <div className="border-b border-white/[0.07] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-zinc-100">事件列表</h2>
                  <p className="mt-1 text-xs text-zinc-500">{filtered.length} 个结果</p>
                </div>
                <ListFilter size={18} className="text-cyber-green/65" />
              </div>

              <label htmlFor="event-search" className="mt-4 block text-xs font-medium text-zinc-400">搜索事件</label>
              <div className="relative mt-2">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                <input
                  id="event-search"
                  type="search"
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                  placeholder="名称、ID、角色或描述"
                  className="min-h-11 w-full rounded-lg border border-cyber-green/12 bg-black/25 pl-9 pr-10 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-600 focus:border-cyber-green/40 focus:ring-2 focus:ring-cyber-green/10"
                />
                {search && (
                  <button type="button" onClick={() => setSearch('')} aria-label="清空搜索" title="清空搜索" className="absolute right-0 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-white/[0.05] hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35">
                    <X size={15} />
                  </button>
                )}
              </div>

              <div className="mt-3 grid grid-cols-3 rounded-lg bg-black/25 p-1" aria-label="按状态筛选">
                {[
                  { value: 'all', label: '全部' },
                  { value: 'active', label: '启用' },
                  { value: 'disabled', label: '停用' },
                ].map(option => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setFilter(option.value)}
                    aria-pressed={filter === option.value}
                    className={`min-h-11 rounded-md px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 ${
                      filter === option.value
                        ? 'bg-cyber-green/[0.09] text-cyber-green shadow-sm'
                        : 'text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <select value={triggerFilter} onChange={event => setTriggerFilter(event.target.value)} aria-label="触发类型筛选" className="min-h-11 min-w-0 rounded-lg border border-white/[0.08] bg-black/25 px-2.5 text-xs text-zinc-400 outline-none focus:border-cyber-green/35 focus:ring-2 focus:ring-cyber-green/10">
                  <option value="all">全部触发类型</option>
                  {TRIGGER_TYPES.map(type => <option key={type.value} value={type.value}>{type.label}</option>)}
                </select>
                <select value={sort} onChange={event => setSort(event.target.value)} aria-label="事件排序" className="min-h-11 min-w-0 rounded-lg border border-white/[0.08] bg-black/25 px-2.5 text-xs text-zinc-400 outline-none focus:border-cyber-green/35 focus:ring-2 focus:ring-cyber-green/10">
                  {SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </div>
            </div>

            {error && (
              <div role="alert" className="m-3 rounded-lg border border-red-400/20 bg-red-400/[0.06] p-3">
                <div className="flex items-start gap-2 text-sm leading-5 text-red-100/85">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <p>{error}</p>
                </div>
                <button
                  type="button"
                  onClick={isAuthError ? () => navigate('/') : () => loadEvents()}
                  className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-medium text-red-100/80 transition-colors hover:bg-red-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300/35"
                >
                  {!isAuthError && <RefreshCw size={14} />}
                  {isAuthError ? '返回首页登录' : '重新加载'}
                </button>
              </div>
            )}

            {loading && (
              <div className="space-y-2 p-3" aria-label="正在加载事件">
                {[0, 1, 2, 3].map(item => <div key={item} className="h-[92px] animate-pulse rounded-lg bg-white/[0.035]" />)}
              </div>
            )}

            {!loading && !error && filtered.length === 0 && (
              <div className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
                <Activity size={30} className="text-zinc-700" />
                <p className="mt-3 text-sm font-medium text-zinc-300">
                  {events.length === 0 ? '还没有事件' : '没有匹配的事件'}
                </p>
                <p className="mt-1 text-xs leading-5 text-zinc-600">
                  {events.length === 0 ? '创建后即可配置触发条件与执行效果' : '尝试调整关键词或筛选条件'}
                </p>
                <button
                  type="button"
                  onClick={events.length === 0 ? () => navigate('/events/new') : clearFilters}
                  className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-white/[0.09] px-3 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35"
                >
                  {events.length === 0 ? <Plus size={14} /> : <X size={14} />}
                  {events.length === 0 ? '创建事件' : '清除筛选'}
                </button>
              </div>
            )}

            {!loading && filtered.length > 0 && (
              <div className="max-h-[580px] space-y-1.5 overflow-y-auto p-2 lg:max-h-[calc(100dvh-315px)]">
                {hasFilters && (
                  <div className="flex items-center justify-between px-2 py-1 text-[11px] text-zinc-600">
                    <span>显示 {filtered.length} / {events.length}</span>
                    <button type="button" onClick={clearFilters} className="min-h-11 rounded-md px-2 text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300">清除</button>
                  </div>
                )}
                {filtered.map((evt, index) => {
                  const TriggerIcon = TRIGGER_ICONS[evt.trigger_type] || Activity;
                  const isSelected = selectedEventId === evt.event_id;
                  return (
                    <FadeContent key={evt.event_id} delay={Math.min(index, 6) * 0.025}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedEvent(evt);
                          setSelectedEventId(evt.event_id);
                        }}
                        aria-current={isSelected ? 'true' : undefined}
                        className={`group relative w-full rounded-lg border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 ${
                          isSelected
                            ? 'border-cyber-green/25 bg-cyber-green/[0.07]'
                            : 'border-transparent hover:border-white/[0.07] hover:bg-white/[0.035]'
                        } ${evt.is_active ? '' : 'opacity-65 hover:opacity-90'}`}
                      >
                        <span className={`absolute inset-y-3 left-0 w-0.5 rounded-r-full ${evt.is_active ? 'bg-cyber-green' : 'bg-zinc-600'}`} />
                        <span className="flex items-start gap-3">
                          <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                            isSelected ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.045] text-zinc-500'
                          }`}>
                            <TriggerIcon size={16} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center justify-between gap-2">
                              <span className="truncate text-sm font-semibold text-zinc-100">{evt.event_name || evt.event_id}</span>
                              <span className={`shrink-0 text-[11px] font-medium ${evt.is_active ? 'text-cyber-green/80' : 'text-zinc-500'}`}>
                                {evt.is_active ? '启用' : '停用'}
                              </span>
                            </span>
                            <span className="mt-1 block truncate font-mono text-[11px] text-zinc-600">{evt.event_id}</span>
                            <span className="mt-2 flex items-center justify-between gap-3 text-[11px] text-zinc-600">
                              <span className="truncate">{TRIGGER_LABELS[evt.trigger_type] || evt.trigger_type || '未知触发'}</span>
                              <span className="shrink-0">P{evt.priority || 0} · {evt.trigger_count || 0} 次</span>
                            </span>
                          </span>
                        </span>
                      </button>
                    </FadeContent>
                  );
                })}
              </div>
            )}
          </aside>

          <section className="min-w-0">
            {selectedEventId ? (
              <FadeContent key={selectedEventId}>
                <EventDetailPanel
                  event={eventDetail}
                  loading={detailLoading}
                  error={detailError}
                  busy={busyEventId === selectedEventId}
                  worldClock={worldClock}
                  onRefresh={() => loadEventDetail(selectedEventId)}
                  onEdit={() => navigate(`/events/${selectedEventId}`)}
                  onToggle={() => handleToggle(eventDetail || selectedSummary)}
                  onDelete={() => handleDelete(eventDetail || selectedSummary)}
                />
              </FadeContent>
            ) : (
              <div className="memoria-panel-muted flex min-h-[560px] flex-col items-center justify-center border-dashed px-6 text-center">
                <Zap size={36} className="text-zinc-700" />
                <h2 className="mt-4 text-base font-semibold text-zinc-300">选择一个事件</h2>
                <p className="mt-2 max-w-sm text-sm leading-6 text-zinc-600">选中左侧事件后，可在这里查看触发配置、排期和运行状态。</p>
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function EventDetailPanel({ event, loading, error, busy, worldClock, onRefresh, onEdit, onToggle, onDelete }) {
  const TriggerIcon = TRIGGER_ICONS[event?.trigger_type] || Activity;
  const effects = Array.isArray(event?.effects) ? event.effects : [];
  const isTimeBased = event?.trigger_type === 'time_based';

  return (
    <section aria-labelledby="event-detail-title" className="memoria-panel overflow-hidden">
      <div className="border-b border-white/[0.07] px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${
              event?.is_active ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.05] text-zinc-500'
            }`}>
              <TriggerIcon size={19} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="event-detail-title" className="break-words text-lg font-semibold text-zinc-100 sm:text-xl">
                  {event?.event_name || '加载中...'}
                </h2>
                {event && (
                  <span className={`rounded-md px-2 py-1 text-[11px] font-medium ${
                    event.is_active ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.05] text-zinc-500'
                  }`}>
                    {event.is_active ? '已启用' : '已停用'}
                  </span>
                )}
              </div>
              {event && <p className="mt-1 truncate font-mono text-[11px] text-zinc-600">{event.event_id}</p>}
              <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
                {event?.description || '暂无描述。可进入编辑器补充事件用途与剧情背景。'}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1 self-end xl:self-auto">
            <button type="button" onClick={onEdit} disabled={!event || busy} aria-label="编辑事件" title="编辑" className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40">
              <Edit2 size={16} />
            </button>
            <button type="button" onClick={onToggle} disabled={!event || busy} aria-label={event?.is_active ? '停用事件' : '启用事件'} title={event?.is_active ? '停用' : '启用'} className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-cyber-green/[0.07] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40">
              {busy ? <Loader2 size={16} className="animate-spin" /> : event?.is_active ? <PowerOff size={16} /> : <Power size={16} />}
            </button>
            <button type="button" onClick={onDelete} disabled={!event || busy} aria-label="删除事件" title="删除" className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-red-400/[0.08] hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300/35 disabled:cursor-not-allowed disabled:opacity-40">
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div className="space-y-4 p-5" aria-label="正在加载事件详情">
          <div className="h-20 animate-pulse rounded-lg bg-white/[0.035]" />
          <div className="h-14 animate-pulse rounded-lg bg-white/[0.035]" />
          <div className="h-44 animate-pulse rounded-lg bg-white/[0.035]" />
        </div>
      )}

      {!loading && error && (
        <div role="alert" className="m-5 rounded-lg border border-red-400/20 bg-red-400/[0.06] p-4">
          <p className="text-sm text-red-100/85">{error}</p>
          <button type="button" onClick={onRefresh} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-medium text-red-100/80 hover:bg-red-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/40">
            <RefreshCw size={13} /> 重新加载
          </button>
        </div>
      )}

      {!loading && !error && event && (
        <div>
          <dl className="grid grid-cols-2 border-b border-white/[0.07] bg-black/10 sm:grid-cols-4">
            {[
              ['优先级', event.priority ?? 0],
              ['累计触发', event.trigger_count ?? 0],
              ['触发类型', TRIGGER_LABELS[event.trigger_type] || event.trigger_type || '未知'],
              ['单轮上限', event.max_triggers_per_turn ?? 3],
            ].map(([label, value], index) => (
              <div key={label} className={`px-4 py-3 sm:px-5 ${index % 2 === 0 ? 'border-r border-white/[0.06]' : ''} ${index < 2 ? 'border-b border-white/[0.06] sm:border-b-0' : ''} ${index === 1 ? 'sm:border-r' : ''}`}>
                <dt className="text-[11px] text-zinc-600">{label}</dt>
                <dd className="mt-1 truncate text-sm font-semibold text-zinc-200 tabular-nums" title={String(value)}>{value}</dd>
              </div>
            ))}
          </dl>

          <div className="border-b border-white/[0.07] p-4 sm:p-5">
            <button type="button" onClick={onEdit} disabled={busy} className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-cyber-green px-4 text-sm font-semibold text-[#09100b] transition-colors hover:bg-[#b8f7b0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/45 disabled:cursor-not-allowed disabled:opacity-45">
              <Edit2 size={16} />
              打开完整编辑器
            </button>
          </div>

          <section aria-labelledby="trigger-config-title" className="border-b border-white/[0.07] px-4 py-4 sm:px-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <Zap size={15} className="shrink-0 text-cyber-green/75" />
                <h3 id="trigger-config-title" className="text-sm font-semibold text-zinc-200">触发配置</h3>
              </div>
              <span className="text-xs text-zinc-600">{TRIGGER_LABELS[event.trigger_type] || event.trigger_type || '未知类型'}</span>
            </div>
            <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <DetailItem label="条件摘要" value={describeTrigger(event.trigger_condition, event.trigger_type)} />
              <DetailItem label="绑定角色" value={event.character_id || '全局事件'} mono />
              <DetailItem label="独占分组" value={event.exclusive_group || '未设置'} mono />
              <DetailItem label="命中后处理" value={event.stop_processing ? '停止后续事件匹配' : '继续匹配其他事件'} />
            </div>
          </section>

          {isTimeBased && (
            <section aria-labelledby="schedule-title" className="border-b border-white/[0.07] px-4 py-4 sm:px-5">
              <div className="flex items-center gap-2">
                <CalendarClock size={15} className="text-amber-200/80" />
                <h3 id="schedule-title" className="text-sm font-semibold text-zinc-200">运行排期</h3>
              </div>
              <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
                <DetailItem label="计划表达式" value={event.schedule || '尚未排期'} mono />
                <DetailItem label="世界时间触发" value={event.next_run_at ? formatScheduleTime(event.next_run_at) : '尚未计算'} />
                <DetailItem label="现实预计时间" value={event.next_due_real_at ? formatScheduleTime(event.next_due_real_at) : Number(worldClock?.time_scale) === 0 ? '世界时间已暂停' : '尚未计算'} />
                <DetailItem label="合并漏触发" value={`${Number(event.missed_count) || 0} 次`} />
              </div>
            </section>
          )}

          <section aria-labelledby="effects-title" className="border-b border-white/[0.07]">
            <div className="flex items-center justify-between gap-3 px-4 py-4 sm:px-5">
              <div className="flex items-center gap-2">
                <Network size={15} className="text-cyan-200/75" />
                <h3 id="effects-title" className="text-sm font-semibold text-zinc-200">执行效果</h3>
              </div>
              <span className="text-xs text-zinc-600">{effects.length} 项</span>
            </div>
            {effects.length === 0 ? (
              <div className="border-t border-white/[0.06] px-5 py-8 text-center text-sm text-zinc-600">尚未配置执行效果</div>
            ) : (
              <div className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
                {effects.map((effect, index) => (
                  <div key={`${effect.effect_type || 'effect'}-${index}`} className="flex items-start gap-3 px-4 py-3 sm:px-5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-300/[0.07] text-cyan-200/70">
                      <span className="text-xs font-semibold tabular-nums">{index + 1}</span>
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-zinc-300">{EFFECT_LABELS[effect.effect_type] || effect.effect_type || '未命名效果'}</p>
                      <p className="mt-1 truncate font-mono text-[11px] text-zinc-600">{effect.effect_type || 'unknown'}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section aria-labelledby="runtime-title" className="px-4 py-4 sm:px-5">
            <div className="flex items-center gap-2">
              <Clock size={15} className="text-zinc-500" />
              <h3 id="runtime-title" className="text-sm font-semibold text-zinc-200">运行记录</h3>
            </div>
            <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <DetailItem label="最后触发" value={formatDateTime(event.last_triggered_at)} />
              <DetailItem label="最后更新" value={formatDateTime(event.updated_at)} />
              <DetailItem label="模板" value={event.template_id || '未使用模板'} mono />
              <DetailItem label="创建时间" value={formatDateTime(event.created_at)} />
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function DetailItem({ label, value, mono = false }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] text-zinc-600">{label}</p>
      <p className={`mt-1 break-words text-sm leading-5 text-zinc-300 ${mono ? 'font-mono text-xs' : ''}`}>{value}</p>
    </div>
  );
}
