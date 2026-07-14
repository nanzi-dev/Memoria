import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Clock3,
  Pause,
  RefreshCw,
  WifiOff,
  X,
} from 'lucide-react';
import { useUser } from '../context/UserContext';
import { narrativePeriod } from '../utils/worldClock';

export function useWorldNow() {
  const { worldClock, getWorldNow } = useUser();
  const [worldNow, setWorldNow] = useState(() => getWorldNow());

  useEffect(() => {
    setWorldNow(getWorldNow());
    const timer = setInterval(() => setWorldNow(getWorldNow()), 1000);
    return () => clearInterval(timer);
  }, [getWorldNow, worldClock?.clock_revision]);

  return { clock: worldClock, worldNow };
}

function ClockStatusIcon({ state }) {
  if (state === 'offline') return <WifiOff size={12} />;
  if (state === 'refreshing') return <RefreshCw size={12} className="animate-spin" />;
  if (['error', 'stale', 'conflict'].includes(state)) return <AlertTriangle size={12} />;
  return null;
}

export function WorldClockDisplay({ className = '', onClick }) {
  const { clockStatus } = useUser();
  const { clock, worldNow } = useWorldNow();
  const formatted = useMemo(() => {
    if (!clock || !worldNow) return null;
    const date = new Intl.DateTimeFormat('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      weekday: 'short',
      timeZone: clock.timezone,
    }).format(worldNow);
    const time = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: clock.timezone,
    }).format(worldNow);
    return {
      date,
      time,
      period: narrativePeriod(worldNow, clock.timezone),
    };
  }, [clock, worldNow]);

  if (!formatted) return null;
  const paused = Number(clock.time_scale) === 0;
  const hasWarning = !['idle', 'synced'].includes(clockStatus.state);
  const statusLabel = clockStatus.state === 'offline'
    ? '离线'
    : clockStatus.state === 'refreshing'
      ? '校准中'
      : hasWarning
        ? '待校准'
        : '';
  const content = (
    <>
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-white/8 bg-black/20">
        {paused
          ? <Pause size={14} className="text-amber-300" />
          : <Clock3 size={14} className="text-cyan-200" />}
      </span>
      <span className="min-w-0 flex-1 text-left leading-tight">
        <span className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-zinc-300">
          <span>{formatted.date}</span>
          <span className="tabular-nums text-xs font-semibold text-zinc-100">{formatted.time}</span>
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[10px]">
          <span className="text-amber-200/75">{formatted.period}</span>
          <span className={paused ? 'text-amber-300' : 'text-cyan-200/75'}>
            {paused ? '暂停' : `${clock.time_scale}x`}
          </span>
          {statusLabel && (
            <span className="inline-flex items-center gap-1 text-amber-300" title={clockStatus.message}>
              <ClockStatusIcon state={clockStatus.state} />
              {statusLabel}
            </span>
          )}
        </span>
      </span>
    </>
  );
  const label = `${formatted.date} ${formatted.time}，${formatted.period}，${paused ? '已暂停' : `${clock.time_scale}倍速`}${statusLabel ? `，${statusLabel}` : ''}`;
  const classes = `flex min-h-[44px] min-w-0 shrink-0 items-center gap-2 rounded-md px-1.5 text-zinc-400 ${className}`;

  if (!onClick) {
    return <div className={classes} aria-label={label}>{content}</div>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${classes} transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/35`}
      aria-label={`${label}，打开世界时间设置`}
      title="打开世界时间设置"
    >
      {content}
    </button>
  );
}

export function EventInboxBanner({ characterId = null, sessionId = null }) {
  const { eventInbox, markEventRead } = useUser();
  const visibleItems = eventInbox
    .filter(item => {
      if (item.session_id && sessionId) return item.session_id === sessionId;
      if (item.character_id && characterId) return item.character_id === characterId;
      return !item.session_id && !item.character_id;
    })
    .slice(0, 2);

  if (!visibleItems.length) return null;
  return (
    <div className="shrink-0 space-y-1.5 border-b border-amber-300/10 bg-amber-300/[0.035] px-3 py-2">
      {visibleItems.map(item => (
        <div key={item.id} className="flex min-w-0 items-start gap-2 text-[11px] leading-4 text-zinc-300">
          <Bell size={13} className="mt-0.5 shrink-0 text-amber-300/70" />
          <div className="min-w-0 flex-1">
            {item.title && <span className="mr-2 font-semibold text-amber-100/80">{item.title}</span>}
            <span className="break-words text-zinc-400">{item.content}</span>
          </div>
          <button
            type="button"
            onClick={() => markEventRead(item.id).catch(() => {})}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
            aria-label="标记事件通知为已读"
            title="标记已读"
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
