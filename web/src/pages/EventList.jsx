import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Edit2,
  GitBranch,
  Hash,
  Heart,
  Layers3,
  Loader2,
  MessageSquare,
  Network,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  Search,
  ShieldCheck,
  Smile,
  Timer,
  Trash2,
  X,
  Zap,
} from 'lucide-react';

import ArchiveWorkspace from '@/archive/ArchiveWorkspace';
import { useArchiveShell } from '@/archive/ArchiveShell';
import FadeContent from '@/components/FadeContent';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { eventAdmin } from '@/api/memoria';
import { useDialog } from '@/context/DialogContext';
import { useUser } from '@/context/UserContext';
import { eventEditorPath } from '@/utils/navigationState';
import {
  describeEventTrigger,
  eventEffectLabel,
  eventTriggerLabel,
  mergeEventDetail,
  summarizeEventEffect,
} from './eventDetailSummary';

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
const STATUS_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '停用' },
];
const AUTH_ERROR_PATTERN = /认证|未登录|401|token/i;

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
    if (sort === 'name_asc') {
      return String(a.event_name || '').localeCompare(String(b.event_name || ''));
    }
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

function DetailItem({ label, value, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`mt-1 break-words text-sm leading-6 text-foreground ${mono ? 'font-archive-mono text-xs tabular-nums' : ''}`}>
        {value}
      </dd>
    </div>
  );
}

export default function EventList() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { setPrimaryAction } = useArchiveShell();
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
      setSelectedEvent(prev => mergeEventDetail(
        prev?.event_id === eventId ? prev : {},
        detail,
      ));
      setEvents(prev => prev.map(event => (
        event.event_id === eventId ? mergeEventDetail(event, detail) : event
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
    if (!evt) return;
    setBusyEventId(evt.event_id);
    setNotice('');
    try {
      await eventAdmin.toggle(evt.event_id, !evt.is_active);
      setEvents(prev => prev.map(e => (
        e.event_id === evt.event_id ? { ...e, is_active: !e.is_active } : e
      )));
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
    if (!evt) return;
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
  const openCreate = useCallback(() => navigate('/events/new'), [navigate]);

  const primaryAction = useMemo(() => (
    <Button type="button" size="lg" onClick={openCreate} disabled={isAuthBlocked || loading}>
      <Plus aria-hidden="true" />
      新建事件
    </Button>
  ), [isAuthBlocked, loading, openCreate]);

  useEffect(() => {
    setPrimaryAction(primaryAction);
    return () => setPrimaryAction(null);
  }, [primaryAction, setPrimaryAction]);

  function clearFilters() {
    setSearch('');
    setFilter('all');
    setTriggerFilter('all');
  }

  const noticeNode = notice ? (
    <div
      role="status"
      aria-live="polite"
      className="fixed right-3 top-20 z-[950] flex max-w-[calc(100vw-1.5rem)] items-center gap-2 rounded-md border border-primary/30 bg-popover px-4 py-3 text-sm text-popover-foreground shadow-xl sm:right-5"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span>{notice}</span>
    </div>
  ) : null;

  return (
    <ArchiveWorkspace
      className="[&_button]:min-h-11"
      indexLabel="Archive index / event registry"
      title="事件档案"
      description="检索剧情事件，核对触发条件、执行效果与运行排期。"
      stats={[
        { icon: Layers3, label: '事件总数', value: events.length },
        { icon: Activity, label: '已启用', value: activeCount },
        { icon: PowerOff, label: '已停用', value: disabledCount },
        { icon: Clock, label: '累计触发', value: totalTriggers },
      ]}
      mobileAction={(
        <Button type="button" size="lg" onClick={openCreate} disabled={isAuthBlocked || loading}>
          <Plus aria-hidden="true" />
          新建事件
        </Button>
      )}
      notice={noticeNode}
      directory={(
        <EventDirectory
          events={events}
          filtered={filtered}
          loading={loading}
          error={error}
          isAuthError={isAuthError}
          refreshing={refreshing}
          search={search}
          filter={filter}
          triggerFilter={triggerFilter}
          sort={sort}
          selectedEventId={selectedEventId}
          hasFilters={hasFilters}
          isAuthBlocked={isAuthBlocked}
          onSearchChange={setSearch}
          onFilterChange={setFilter}
          onTriggerFilterChange={setTriggerFilter}
          onSortChange={setSort}
          onClearFilters={clearFilters}
          onRefresh={() => loadEvents({ soft: true })}
          onRecover={isAuthError ? () => navigate('/') : () => loadEvents()}
          onCreate={openCreate}
          onSelect={(evt) => {
            setSelectedEvent(evt);
            setSelectedEventId(evt.event_id);
          }}
        />
      )}
      detail={selectedEventId ? (
        <FadeContent key={selectedEventId}>
          <EventDetailPanel
            event={eventDetail}
            loading={detailLoading}
            error={detailError}
            busy={busyEventId === selectedEventId}
            worldClock={worldClock}
            onRefresh={() => loadEventDetail(selectedEventId)}
            onEdit={() => navigate(eventEditorPath(selectedEventId))}
            onToggle={() => handleToggle(eventDetail || selectedSummary)}
            onDelete={() => handleDelete(eventDetail || selectedSummary)}
          />
        </FadeContent>
      ) : (
        <EmptyDetail
          icon={Zap}
          title="选择一个事件"
          description="从目录中选择事件后，这里只显示事件摘要；完整配置请进入编辑页查看。"
        />
      )}
    />
  );
}

function EventDirectory({
  events,
  filtered,
  loading,
  error,
  isAuthError,
  refreshing,
  search,
  filter,
  triggerFilter,
  sort,
  selectedEventId,
  hasFilters,
  isAuthBlocked,
  onSearchChange,
  onFilterChange,
  onTriggerFilterChange,
  onSortChange,
  onClearFilters,
  onRefresh,
  onRecover,
  onCreate,
  onSelect,
}) {
  return (
    <>
      <div className="border-b border-border p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-archive-serif text-base font-semibold text-foreground">事件目录</h2>
            <p className="mt-1 font-archive-mono text-[10px] tabular-nums text-muted-foreground">
              {filtered.length} records
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onRefresh}
            disabled={isAuthBlocked || loading || refreshing}
            aria-label="刷新事件列表"
            title="刷新事件列表"
          >
            <RefreshCw className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        </div>

        <label htmlFor="event-search" className="mt-4 block text-xs font-medium text-foreground">
          搜索事件
        </label>
        <div className="relative mt-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            id="event-search"
            type="search"
            value={search}
            onChange={event => onSearchChange(event.target.value)}
            placeholder="名称、ID、角色或描述"
            className="pl-9 pr-11"
          />
          {search && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => onSearchChange('')}
              aria-label="清空搜索"
              title="清空搜索"
              className="absolute right-0 top-1/2 -translate-y-1/2"
            >
              <X aria-hidden="true" />
            </Button>
          )}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-1 rounded-md border border-border bg-muted/35 p-1" aria-label="按状态筛选">
          {STATUS_FILTERS.map(option => (
            <Button
              key={option.value}
              type="button"
              variant={filter === option.value ? 'secondary' : 'ghost'}
              onClick={() => onFilterChange(option.value)}
              aria-pressed={filter === option.value}
              className="h-11 px-2 text-xs"
            >
              {option.label}
            </Button>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          <Select value={triggerFilter} onValueChange={onTriggerFilterChange}>
            <SelectTrigger aria-label="触发类型筛选">
              <SelectValue placeholder="全部触发类型" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部触发类型</SelectItem>
              {TRIGGER_TYPES.map(type => (
                <SelectItem key={type.value} value={type.value}>{type.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={onSortChange}>
            <SelectTrigger aria-label="事件排序">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map(option => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {error && (
        <div role="alert" className="m-3 rounded-md border border-destructive/35 bg-destructive/10 p-3">
          <div className="flex items-start gap-2 text-sm leading-6 text-destructive">
            <AlertCircle className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
            <p className="break-words">{error}</p>
          </div>
          <Button type="button" variant="outline" onClick={onRecover} className="mt-3">
            {!isAuthError && <RefreshCw aria-hidden="true" />}
            {isAuthError ? '返回首页登录' : '重新加载'}
          </Button>
        </div>
      )}

      {loading && (
        <div className="space-y-2 p-3" aria-label="正在加载事件">
          {[0, 1, 2, 3].map(item => <Skeleton key={item} className="h-24" />)}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
          <Activity className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="mt-3 text-sm font-medium text-foreground">
            {events.length === 0 ? '还没有事件' : '没有匹配的事件'}
          </p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {events.length === 0 ? '创建后即可配置触发条件与执行效果' : '尝试调整关键词或筛选条件'}
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={events.length === 0 ? onCreate : onClearFilters}
            className="mt-4"
          >
            {events.length === 0 ? <Plus aria-hidden="true" /> : <X aria-hidden="true" />}
            {events.length === 0 ? '创建事件' : '清除筛选'}
          </Button>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="max-h-[620px] space-y-1 overflow-y-auto p-2 lg:max-h-[calc(100dvh-310px)]">
          {hasFilters && (
            <div className="flex min-h-11 items-center justify-between gap-2 px-2 text-[11px] text-muted-foreground">
              <span className="font-archive-mono tabular-nums">显示 {filtered.length} / {events.length}</span>
              <Button type="button" variant="ghost" size="sm" onClick={onClearFilters}>清除</Button>
            </div>
          )}
          {filtered.map((evt, index) => {
            const TriggerIcon = TRIGGER_ICONS[evt.trigger_type] || Activity;
            const isSelected = selectedEventId === evt.event_id;
            return (
              <FadeContent key={evt.event_id} delay={Math.min(index, 6) * 0.025}>
                <button
                  type="button"
                  onClick={() => onSelect(evt)}
                  aria-current={isSelected ? 'true' : undefined}
                  className={`relative min-h-[88px] w-full rounded-md border px-3 py-3 text-left transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    isSelected
                      ? 'border-primary/45 bg-primary/10'
                      : 'border-transparent hover:border-border hover:bg-accent'
                  } ${evt.is_active ? '' : 'opacity-70 hover:opacity-100'}`}
                >
                  <span className="flex min-w-0 items-start gap-3">
                    <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border ${
                      isSelected ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-muted/45 text-muted-foreground'
                    }`}>
                      <TriggerIcon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
                        <span className="min-w-0 break-words font-archive-serif text-sm font-semibold text-foreground">
                          {evt.event_name || evt.event_id}
                        </span>
                        <span className="shrink-0 text-[11px] font-medium text-muted-foreground">
                          {evt.is_active ? '● 启用' : '○ 停用'}
                        </span>
                      </span>
                      <span className="mt-1 block break-all font-archive-mono text-[10px] tabular-nums text-muted-foreground">
                        {evt.event_id}
                      </span>
                      <span className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
                        <span>{eventTriggerLabel(evt.trigger_type, TRIGGER_LABELS)}</span>
                        <span className="font-archive-mono tabular-nums">
                          P{evt.priority || 0} · {evt.trigger_count || 0} 次
                        </span>
                      </span>
                    </span>
                  </span>
                </button>
              </FadeContent>
            );
          })}
        </div>
      )}
    </>
  );
}

function EventDetailPanel({
  event,
  loading,
  error,
  busy,
  worldClock,
  onRefresh,
  onEdit,
  onToggle,
  onDelete,
}) {
  const TriggerIcon = TRIGGER_ICONS[event?.trigger_type] || Activity;
  const effects = Array.isArray(event?.effects) ? event.effects : [];
  const isTimeBased = event?.trigger_type === 'time_based';
  const hasScheduleDetails = !!event?.next_run_at
    || !!event?.next_due_real_at
    || Number(worldClock?.time_scale) === 0
    || Number(event?.missed_count) > 0;
  const hasRunRecords = !!event?.last_triggered_at
    || !!event?.updated_at
    || !!event?.template_id
    || !!event?.created_at;

  return (
    <section aria-labelledby="event-detail-title" className="min-w-0">
      <div className="flex min-w-0 flex-col gap-4 border-b border-border pb-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-muted/45 text-primary">
            <TriggerIcon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="event-detail-title" className="break-words font-archive-serif text-xl font-semibold text-foreground sm:text-2xl">
                {event?.event_name || '加载中...'}
              </h2>
              {event && (
                <span className="rounded border border-border bg-muted/45 px-2 py-1 text-[11px] font-medium text-foreground">
                  {event.is_active ? '● 已启用' : '○ 已停用'}
                </span>
              )}
            </div>
            {event && (
              <p className="mt-1 break-all font-archive-mono text-[10px] tabular-nums text-muted-foreground">
                {event.event_id}
              </p>
            )}
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              {event?.description || '暂无描述。可进入编辑器补充事件用途与剧情背景。'}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 self-end xl:self-auto">
          <Button type="button" variant="outline" onClick={onEdit} disabled={!event || busy}>
            <Edit2 aria-hidden="true" />
            编辑
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={onToggle}
            disabled={!event || busy}
            aria-label={event?.is_active ? '停用事件' : '启用事件'}
          >
            {busy
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : event?.is_active
                ? <PowerOff aria-hidden="true" />
                : <Power aria-hidden="true" />}
            {event?.is_active ? '停用' : '启用'}
          </Button>
          <Button type="button" variant="destructive" onClick={onDelete} disabled={!event || busy}>
            <Trash2 aria-hidden="true" />
            删除
          </Button>
        </div>
      </div>

      {loading && (
        <div className="space-y-4 py-5" aria-label="正在加载事件详情">
          <Skeleton className="h-20" />
          <Skeleton className="h-14" />
          <Skeleton className="h-44" />
        </div>
      )}

      {!loading && error && (
        <div role="alert" className="my-5 rounded-md border border-destructive/35 bg-destructive/10 p-4">
          <p className="break-words text-sm text-destructive">{error}</p>
          <Button type="button" variant="outline" onClick={onRefresh} className="mt-3">
            <RefreshCw aria-hidden="true" />
            重新加载
          </Button>
        </div>
      )}

      {!loading && !error && event && (
        <div>
          <dl className="grid grid-cols-2 divide-x divide-y divide-border border-b border-border sm:grid-cols-4 sm:divide-y-0">
            {[
              ['优先级', event.priority ?? 0],
              ['累计触发', event.trigger_count ?? 0],
              ['触发类型', eventTriggerLabel(event.trigger_type, TRIGGER_LABELS)],
              ['单轮上限', event.max_triggers_per_turn ?? 3],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0 px-3 py-4 sm:px-4">
                <dt className="text-[11px] text-muted-foreground">{label}</dt>
                <dd className="mt-1 break-words font-archive-mono text-sm font-semibold tabular-nums text-foreground">
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <ArchiveSection icon={Zap} title="触发配置" index="01">
            <p className="mb-4 line-clamp-2 font-archive-mono text-sm tabular-nums leading-7 text-foreground">
              {describeEventTrigger(
                event.trigger_condition,
                event.trigger_type,
                TRIGGER_LABELS,
              )}
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
          </ArchiveSection>

          {isTimeBased && (
            <ArchiveSection icon={CalendarClock} title="运行排期" index="02">
              {hasScheduleDetails ? (
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
                    <DetailItem
                      label="合并漏触发"
                      value={`${Number(event.missed_count)} 次`}
                      mono
                    />
                  )}
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">暂无可用排期。</p>
              )}
            </ArchiveSection>
          )}

          <ArchiveSection icon={Network} title="执行效果" index={isTimeBased ? '03' : '02'}>
            {effects.length === 0 ? (
              <p className="text-sm text-muted-foreground">尚未配置执行效果。</p>
            ) : (
              <div className="divide-y divide-border border-y border-border">
                {effects.map((effect, index) => (
                  <article key={`${effect.effect_type || 'effect'}-${index}`} className="py-4">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-border bg-muted/45 font-archive-mono text-xs tabular-nums text-primary">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <div className="min-w-0 flex-1">
                        <h4 className="font-archive-serif text-base font-semibold text-foreground">
                          {eventEffectLabel(effect.effect_type)}
                        </h4>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">
                          {summarizeEventEffect(effect)}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </ArchiveSection>

          <ArchiveSection icon={Clock} title="运行记录" index={isTimeBased ? '04' : '03'} last>
            {hasRunRecords ? (
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
            ) : (
              <p className="text-sm text-muted-foreground">暂无运行记录。</p>
            )}
          </ArchiveSection>
        </div>
      )}
    </section>
  );
}

function ArchiveSection({ icon: Icon, title, index, children, last = false }) {
  return (
    <section className={`py-5 ${last ? '' : 'border-b border-border'}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <h3 className="font-archive-serif text-lg font-semibold text-foreground">{title}</h3>
        </div>
        <span className="font-archive-mono text-[10px] tabular-nums text-muted-foreground">{index}</span>
      </div>
      {children}
    </section>
  );
}

function EmptyDetail({ icon: Icon, title, description }) {
  return (
    <div className="flex min-h-[480px] flex-col items-center justify-center border-y border-dashed border-border px-6 text-center">
      <Icon className="h-9 w-9 text-muted-foreground" aria-hidden="true" />
      <h2 className="mt-4 font-archive-serif text-lg font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}
