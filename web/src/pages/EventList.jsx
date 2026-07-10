import { useState, useEffect, useMemo } from 'react';
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
  ChevronRight,
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
  SlidersHorizontal,
} from 'lucide-react';
import { eventAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import SideRays from '../components/SideRays';

const EVENT_RAYS_PROPS = {
  speed: 1.7,
  rayColor1: '#A7EF9E',
  rayColor2: '#9AD7FF',
  intensity: 2.2,
  spread: 2.1,
  origin: 'top-right',
  tilt: -8,
  saturation: 1.35,
  blend: 0.62,
  falloff: 1.5,
  opacity: 0.55,
};

const TRIGGER_TYPES = [
  { value: 'affinity_threshold', label: '好感度阈值', Icon: Heart },
  { value: 'trust_threshold', label: '信任度阈值', Icon: ShieldCheck },
  { value: 'keyword_match', label: '关键词匹配', Icon: Hash },
  { value: 'dialogue_count', label: '对话次数', Icon: MessageSquare },
  { value: 'time_based', label: '时间条件', Icon: Timer },
  { value: 'mood_match', label: '情绪匹配', Icon: Smile },
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

function EventStat({ label, value, tone = 'default' }) {
  const toneClass = tone === 'warning'
    ? 'border-amber-400/15 bg-amber-400/[0.04] text-amber-200/80'
    : tone === 'muted'
    ? 'border-white/[0.06] bg-white/[0.025] text-zinc-300/65'
    : 'border-cyber-green/15 bg-cyber-green/[0.045] text-cyber-green/80';

  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="text-lg font-bold leading-none">{value}</div>
      <div className="mt-1 text-[10px] font-mono uppercase tracking-[0.12em] opacity-60">{label}</div>
    </div>
  );
}

export default function EventList() {
  const navigate = useNavigate();
  const dialog = useDialog();
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

  useEffect(() => { loadEvents(); }, []);

  async function loadEvents({ soft = false } = {}) {
    try {
      if (soft) setRefreshing(true);
      else setLoading(true);
      setError(null);
      const list = await eventAdmin.list();
      setEvents(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e.message || '事件列表加载失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function handleToggle(evt) {
    setBusyEventId(evt.event_id);
    setNotice('');
    try {
      await eventAdmin.toggle(evt.event_id, !evt.is_active);
      setEvents(prev => prev.map(e =>
        e.event_id === evt.event_id ? { ...e, is_active: !e.is_active } : e
      ));
      setNotice(!evt.is_active ? '事件已启用' : '事件已禁用');
      window.setTimeout(() => setNotice(''), 1800);
    } catch (e) {
      setError(e.message || '切换事件状态失败');
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
      setError(e.message || '删除事件失败');
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

  const activeCount = events.filter(e => e.is_active).length;
  const disabledCount = Math.max(0, events.length - activeCount);
  const totalTriggers = events.reduce((sum, evt) => sum + (Number(evt.trigger_count) || 0), 0);
  const hasFilters = filter !== 'all' || triggerFilter !== 'all' || !!search.trim();

  return (
    <div className="relative min-h-screen overflow-x-hidden memoria-page">
      <SideRays {...EVENT_RAYS_PROPS} className="side-rays-event" />

      <div className="sticky top-0 z-20 border-b border-cyber-green/10 bg-[#0b0b0c]/88 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <button
            onClick={() => navigate('/')}
            className="flex min-h-[40px] items-center gap-2 rounded-lg px-2.5 text-sm font-mono text-cyber-green/55 transition-all hover:bg-cyber-green/5 hover:text-cyber-green"
          >
            <ArrowLeft size={16} />
            Home
          </button>

          <div className="min-w-0 text-center">
            <h1 className="font-display text-sm text-cyber-green tracking-[0.2em] sm:text-base">EVENT MANAGEMENT</h1>
            <p className="mt-0.5 text-[10px] font-mono tracking-[0.14em] text-cyber-green/35">
              {events.length} TOTAL · {activeCount} ACTIVE
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => loadEvents({ soft: true })}
              disabled={loading || refreshing}
              className="flex min-h-[40px] items-center gap-2 rounded-lg border border-cyber-green/15 px-3 text-xs font-mono text-cyber-green/60 transition-all hover:border-cyber-green/30 hover:bg-cyber-green/5 hover:text-cyber-green disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              <span className="hidden sm:inline">刷新</span>
            </button>
            <button
              onClick={() => navigate('/events/new')}
              className="flex min-h-[40px] items-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/12 px-4 text-xs font-bold text-cyber-green transition-all hover:bg-cyber-green/20 hover:shadow-[0_0_24px_rgba(167,239,158,0.12)] active:scale-[0.98]"
            >
              <Plus size={14} />
              New
            </button>
          </div>
        </div>

        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 pb-3 sm:px-6 lg:flex-row lg:items-center">
          <div className="flex flex-wrap items-center gap-2">
            {[
              { value: 'all', label: '全部', count: events.length },
              { value: 'active', label: '启用', count: activeCount },
              { value: 'disabled', label: '禁用', count: disabledCount },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value)}
                className={`min-h-[34px] rounded-lg border px-3 text-[11px] font-mono transition-all ${
                  filter === opt.value
                    ? 'border-cyber-green/35 bg-cyber-green/12 text-cyber-green'
                    : 'border-cyber-green/10 bg-cyber-surface/45 text-cyber-green/45 hover:border-cyber-green/25 hover:text-cyber-green/75'
                }`}
              >
                {opt.label} <span className="text-cyber-green/35">{opt.count}</span>
              </button>
            ))}
          </div>

          <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center lg:justify-end">
            <div className="relative min-w-0 sm:w-72">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyber-green/30" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="搜索名称、ID、角色、描述..."
                className="min-h-[38px] w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 pl-9 pr-9 text-xs font-mono text-cyber-green/85 outline-none transition-all placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-cyber-green/35 transition-colors hover:bg-cyber-green/8 hover:text-cyber-green"
                  aria-label="清空搜索"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            <select
              value={triggerFilter}
              onChange={e => setTriggerFilter(e.target.value)}
              className="min-h-[38px] rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 text-xs font-mono text-cyber-green/70 outline-none transition-all focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10"
            >
              <option value="all">全部触发类型</option>
              {TRIGGER_TYPES.map(type => (
                <option key={type.value} value={type.value}>{type.label}</option>
              ))}
            </select>

            <select
              value={sort}
              onChange={e => setSort(e.target.value)}
              className="min-h-[38px] rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 text-xs font-mono text-cyber-green/70 outline-none transition-all focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10"
            >
              {SORT_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {notice && (
        <div className="fixed left-1/2 top-20 z-30 -translate-x-1/2 rounded-lg border border-cyber-green/20 bg-[#0d0d14]/95 px-4 py-2 text-sm font-mono text-cyber-green shadow-[0_0_32px_rgba(167,239,158,0.12)]">
          {notice}
        </div>
      )}

      <main className="relative z-10 mx-auto max-w-7xl px-4 py-5 sm:px-6">
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <EventStat label="事件总数" value={events.length} />
          <EventStat label="启用中" value={activeCount} />
          <EventStat label="已禁用" value={disabledCount} tone="muted" />
          <EventStat label="累计触发" value={totalTriggers} tone="warning" />
        </div>

        {error && (
          <div className="mb-5 flex flex-col gap-3 rounded-xl border border-red-400/18 bg-red-400/[0.055] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-mono text-red-200/80">{error}</p>
            <button
              onClick={() => loadEvents()}
              className="inline-flex min-h-[38px] items-center justify-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-mono text-red-200/80 transition-all hover:bg-red-400/10"
            >
              <RefreshCw size={14} />
              重试
            </button>
          </div>
        )}

        {loading && (
          <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-cyber-green/10 bg-cyber-surface/25">
            <div className="flex items-center gap-3 text-cyber-green/45">
              <Loader2 className="animate-spin" size={18} />
              <span className="font-mono text-sm">Loading events...</span>
            </div>
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="animate-fade-up flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-cyber-green/10 bg-cyber-surface/20 px-5 text-center">
            <Activity size={44} className="text-cyber-green/18" />
            <p className="mt-4 text-sm font-mono text-cyber-green/35">
              {events.length === 0 ? '暂无事件定义' : '没有符合条件的事件'}
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              {events.length === 0 ? (
                <button
                  onClick={() => navigate('/events/new')}
                  className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-cyber-green/25 bg-cyber-green/10 px-4 text-xs font-bold text-cyber-green transition-colors hover:bg-cyber-green/20"
                >
                  <Plus size={14} /> 创建第一个事件
                </button>
              ) : (
                <button
                  onClick={() => { setSearch(''); setFilter('all'); setTriggerFilter('all'); }}
                  className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-cyber-green/18 px-4 text-xs font-mono text-cyber-green/65 transition-colors hover:bg-cyber-green/8 hover:text-cyber-green"
                >
                  <X size={14} /> 清空筛选
                </button>
              )}
            </div>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-3">
            {hasFilters && (
              <div className="flex items-center justify-between rounded-lg border border-cyber-green/8 bg-cyber-surface/20 px-3 py-2">
                <div className="flex items-center gap-2 text-[11px] font-mono text-cyber-green/42">
                  <SlidersHorizontal size={13} />
                  当前显示 {filtered.length} / {events.length}
                </div>
                <button
                  onClick={() => { setSearch(''); setFilter('all'); setTriggerFilter('all'); }}
                  className="text-[11px] font-mono text-cyber-green/45 transition-colors hover:text-cyber-green"
                >
                  清空筛选
                </button>
              </div>
            )}

            {filtered.map((evt, i) => {
              const TriggerIcon = TRIGGER_ICONS[evt.trigger_type] || Activity;
              const busy = busyEventId === evt.event_id;
              return (
                <div
                  key={evt.event_id}
                  onClick={() => navigate(`/events/${evt.event_id}`)}
                  className={`group relative cursor-pointer overflow-hidden rounded-xl border transition-all duration-200 animate-fade-up ${
                    evt.is_active
                      ? 'border-cyber-green/12 bg-[#10131a]/72 hover:border-cyber-green/32 hover:bg-[#121720]/88 hover:shadow-[0_0_36px_rgba(167,239,158,0.08)]'
                      : 'border-white/[0.055] bg-[#0d0d14]/55 opacity-70 hover:opacity-90'
                  }`}
                  style={{ animationDelay: `${Math.min(i, 14) * 22}ms` }}
                >
                  <div className={`absolute inset-y-3 left-0 w-1 rounded-r-full ${evt.is_active ? 'bg-cyber-green/45' : 'bg-zinc-500/25'}`} />
                  <div className="grid gap-3 px-4 py-4 md:grid-cols-[auto_minmax(0,1fr)_auto_auto] md:items-center">
                    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border transition-all group-hover:scale-[1.03] ${
                      evt.is_active ? 'border-cyber-green/18 bg-cyber-green/8 text-cyber-green' : 'border-white/[0.06] bg-white/[0.025] text-zinc-500'
                    }`}>
                      <TriggerIcon size={18} />
                    </div>

                    <div className="min-w-0">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <h3 className={`truncate text-sm font-bold ${evt.is_active ? 'text-zinc-100' : 'text-zinc-500'}`}>
                          {evt.event_name || evt.event_id}
                        </h3>
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-mono ${
                          evt.is_active ? 'border-cyber-green/18 bg-cyber-green/8 text-cyber-green/70' : 'border-white/[0.06] text-zinc-500'
                        }`}>
                          {evt.is_active ? 'ACTIVE' : 'DISABLED'}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-mono text-cyber-green/30">
                        <span className="max-w-[260px] truncate">{evt.event_id}</span>
                        {evt.character_id && <span className="max-w-[160px] truncate">@{evt.character_id}</span>}
                        <span>{TRIGGER_LABELS[evt.trigger_type] || evt.trigger_type || '未知触发'}</span>
                      </div>
                      {evt.description && (
                        <p className="mt-2 line-clamp-2 text-xs leading-5 text-zinc-400/70">{evt.description}</p>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-[10px] font-mono text-cyber-green/35 sm:flex sm:items-center sm:gap-3">
                      <span className="inline-flex items-center gap-1 rounded-lg border border-cyber-green/8 bg-cyber-green/[0.035] px-2 py-1">
                        <Clock size={11} />
                        {evt.trigger_count || 0}
                      </span>
                      <span className="inline-flex items-center justify-center rounded-lg border border-cyber-green/8 bg-cyber-green/[0.035] px-2 py-1">
                        P{evt.priority || 0}
                      </span>
                    </div>

                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={e => { e.stopPropagation(); handleToggle(evt); }}
                        disabled={busy}
                        title={evt.is_active ? '禁用' : '启用'}
                        className={`flex h-9 w-9 items-center justify-center rounded-lg transition-all active:scale-95 disabled:cursor-not-allowed disabled:opacity-45 ${
                          evt.is_active
                            ? 'text-cyber-green/55 hover:bg-cyber-green/10 hover:text-cyber-green'
                            : 'text-zinc-500 hover:bg-cyber-green/8 hover:text-cyber-green/70'
                        }`}
                      >
                        {busy ? <Loader2 size={15} className="animate-spin" /> : evt.is_active ? <PowerOff size={15} /> : <Power size={15} />}
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(evt); }}
                        disabled={busy}
                        title="删除"
                        className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition-all hover:bg-red-400/8 hover:text-red-300 active:scale-95 disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        <Trash2 size={15} />
                      </button>
                      <ChevronRight size={16} className="text-cyber-green/15 transition-colors group-hover:text-cyber-green/55" />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
