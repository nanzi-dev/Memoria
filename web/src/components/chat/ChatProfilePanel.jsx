import {
  MOOD_EMOJI,
  MOOD_LABELS,
} from '../../utils/chatRoom';
import ChatAvatar from './ChatAvatar';
import ChatSummaryRow from './ChatSummaryRow';

function ArchiveMeter({ label, value, percent }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="font-archive-mono text-xs text-foreground tabular-nums">{value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-sm bg-muted">
        <div className="h-full rounded-sm bg-primary transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function ChatProfilePanel({
  mode,
  mobile = false,
  character,
  participants,
  groupName,
  multiSessionId,
  multiSessionStatus,
  groupHistoryReady,
  affinity,
  trust,
  mood,
  events,
  messages,
  isRecovered,
  isCharacterActive,
  normalizeParticipant,
}) {
  if (mode === 'group') {
    const resolvedParticipants = participants.map(participant => normalizeParticipant(participant));
    const activeParticipantCount = resolvedParticipants.filter(participant => isCharacterActive(participant)).length;
    return (
      <div className={`${mobile ? '' : 'min-h-0 flex-1 overflow-y-auto'} p-4`}>
        <div className="border-b border-border pb-4">
          <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Ensemble File</p>
          <h2 className="mt-1 truncate font-archive-serif text-lg font-semibold text-foreground">{groupName || '群聊'}</h2>
          <p className="mt-1 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
            {multiSessionId || '会话准备中'}
          </p>
        </div>

        <dl className="divide-y divide-border border-b border-border">
          <ChatSummaryRow label="会话状态" value={multiSessionStatus === 'active' ? '进行中' : '已结束'} />
          <ChatSummaryRow label="同步状态" value={groupHistoryReady ? '已同步' : '同步中'} />
          <ChatSummaryRow label="在线成员" value={`${activeParticipantCount}/${resolvedParticipants.length}`} />
          <ChatSummaryRow label="消息数" value={messages.length} />
        </dl>

        <section className="mt-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-archive-serif text-sm font-semibold text-foreground">群成员</h3>
            <span className="font-archive-mono text-[10px] text-muted-foreground tabular-nums">{resolvedParticipants.length}</span>
          </div>
          <div className="mt-2 space-y-1">
            {resolvedParticipants.map((participant, index) => {
              const active = isCharacterActive(participant);
              return (
                <div key={participant.character_id || index} className="flex min-h-12 items-center gap-3 border-b border-border py-2">
                  <span className="w-5 shrink-0 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <ChatAvatar entity={participant} sizeClass="h-9 w-9" extraClass={active ? '' : 'grayscale opacity-55'} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-archive-serif text-sm text-foreground">{participant.name}</span>
                    <span className="block text-[10px] text-muted-foreground">{active ? '在线' : '离线'}</span>
                  </span>
                  <span className={`h-2 w-2 rounded-sm ${active ? 'bg-primary' : 'bg-muted-foreground/45'}`} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </section>
      </div>
    );
  }

  const affinityPercent = Math.min(100, Math.max(0, Math.round((affinity + 100) / 2)));
  const trustValue = Math.min(100, Math.max(0, Math.round(Number(trust) || 0)));
  const identitySummary = character?.identity?.core_identity_summary || character?.core_identity;
  return (
    <div className={`${mobile ? '' : 'min-h-0 flex-1 overflow-y-auto'} p-4`}>
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <ChatAvatar entity={character} sizeClass="h-14 w-14" />
        <div className="min-w-0 flex-1">
          <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Character File</p>
          <h2 className="truncate font-archive-serif text-lg font-semibold text-foreground">{character?.name}</h2>
          {identitySummary && <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{identitySummary}</p>}
        </div>
      </div>

      {character?.status_labels?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-border py-3">
          {character.status_labels.filter(Boolean).slice(0, 4).map((label, index) => (
            <span key={`${label}-${index}`} className="rounded-md border border-border bg-muted px-2 py-1 text-[10px] text-muted-foreground">
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="space-y-4 border-b border-border py-4">
        <ArchiveMeter label="好感度" value={affinity} percent={affinityPercent} />
        <ArchiveMeter label="信任度" value={trustValue} percent={trustValue} />
      </div>

      <dl className="divide-y divide-border border-b border-border">
        <ChatSummaryRow label="当前心情" value={`${MOOD_EMOJI[mood] || MOOD_EMOJI.neutral} ${MOOD_LABELS[mood] || MOOD_LABELS.neutral}`} />
        <ChatSummaryRow label="会话状态" value={isCharacterActive(character) ? '进行中' : '离线只读'} />
        <ChatSummaryRow label="历史恢复" value={isRecovered ? '已恢复' : '新会话'} />
        <ChatSummaryRow label="消息数" value={messages.length} />
      </dl>

      {events.length > 0 && (
        <section className="mt-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-archive-serif text-sm font-semibold text-foreground">事件记录</h3>
            <span className="font-archive-mono text-[10px] text-muted-foreground tabular-nums">{events.length}</span>
          </div>
          <div className="mt-2 space-y-2">
            {events.map((event, index) => (
              <div key={event.id || index} className="rounded-md border border-border bg-background p-2 text-xs leading-5 text-muted-foreground">
                {event.description || event.name || event.event_name || '事件已触发'}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default ChatProfilePanel;
