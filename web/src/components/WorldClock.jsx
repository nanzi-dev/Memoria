import { useEffect, useMemo, useState } from 'react';
import { Bell, Clock3, Pause, X } from 'lucide-react';
import { useUser } from '../context/UserContext';

function deriveWorldNow(clock, realMilliseconds) {
  if (!clock?.world_now || !clock?.real_now) return null;
  const worldAnchor = Date.parse(clock.world_now);
  const realAnchor = Date.parse(clock.real_now);
  if (!Number.isFinite(worldAnchor) || !Number.isFinite(realAnchor)) return null;
  return new Date(worldAnchor + (realMilliseconds - realAnchor) * Number(clock.time_scale || 0));
}

export function useWorldNow() {
  const { worldClock } = useUser();
  const [realMilliseconds, setRealMilliseconds] = useState(Date.now());

  useEffect(() => {
    setRealMilliseconds(Date.now());
    const timer = setInterval(() => setRealMilliseconds(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [worldClock?.real_now, worldClock?.world_now, worldClock?.time_scale]);

  return {
    clock: worldClock,
    worldNow: deriveWorldNow(worldClock, realMilliseconds),
  };
}

export function WorldClockDisplay({ className = '' }) {
  const { clock, worldNow } = useWorldNow();
  const formatted = useMemo(() => {
    if (!clock || !worldNow) return null;
    const date = new Intl.DateTimeFormat('zh-CN', {
      timeZone: clock.timezone,
      month: 'numeric',
      day: 'numeric',
      weekday: 'short',
    }).format(worldNow);
    const time = new Intl.DateTimeFormat('zh-CN', {
      timeZone: clock.timezone,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(worldNow);
    return { date, time };
  }, [clock, worldNow]);

  if (!formatted) return null;
  const paused = clock.time_scale === 0;
  return (
    <div
      className={`flex min-w-0 shrink-0 items-center gap-1.5 text-[10px] text-zinc-400 ${className}`}
      title={`${clock.timezone} 世界时间`}
      aria-label={`${formatted.date} ${formatted.time}，${paused ? '已暂停' : `${clock.time_scale}倍速`}`}
    >
      {paused ? <Pause size={12} className="text-amber-400/80" /> : <Clock3 size={12} className="text-cyan-300/70" />}
      <span className="hidden md:inline whitespace-nowrap">{formatted.date}</span>
      <span className="tabular-nums whitespace-nowrap text-zinc-300">{formatted.time}</span>
      <span className={`whitespace-nowrap ${paused ? 'text-amber-400/80' : 'text-cyan-300/60'}`}>
        {paused ? '暂停' : `${clock.time_scale}x`}
      </span>
    </div>
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
    <div className="shrink-0 border-b border-amber-300/10 bg-amber-300/[0.035] px-3 py-2 space-y-1.5">
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
