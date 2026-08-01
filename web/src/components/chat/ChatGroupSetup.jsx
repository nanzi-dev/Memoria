import { ArrowLeft, Users, X } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import ChatAvatar from './ChatAvatar';
import ChatErrorNotice from './ChatErrorNotice';

export function ChatGroupSetup({
  groupName,
  onGroupNameChange,
  groupNameExists,
  error,
  onDismissError,
  allChars,
  participants,
  isCharacterActive,
  onToggleParticipant,
  onStartGroupChat,
  onGoToList,
}) {
  const activeCharacters = allChars.filter(char => isCharacterActive(char));
  return (
    <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
      <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
        <section className="flex min-h-0 min-w-0 flex-col border-r border-border bg-background lg:col-span-2">
          <div className="flex min-h-16 items-center gap-2 border-b border-border px-3 sm:px-4">
            <Button type="button" variant="ghost" size="icon" onClick={onGoToList} aria-label="返回会话目录">
              <ArrowLeft aria-hidden="true" />
            </Button>
            <div className="min-w-0 flex-1">
              <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">New Ensemble</p>
              <h1 className="font-archive-serif text-base font-semibold text-foreground">创建群聊</h1>
            </div>
            <span className="font-archive-mono text-xs text-muted-foreground tabular-nums">
              {participants.length}/{activeCharacters.length}
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
            <div className="mx-auto max-w-3xl space-y-5">
              <ChatErrorNotice error={error} onDismiss={onDismissError} />
              <section className="rounded-lg border border-border bg-card p-4">
                <label htmlFor="group-name" className="mb-2 block font-archive-serif text-sm font-semibold text-foreground">
                  群聊名称
                </label>
                <Input
                  id="group-name"
                  type="text"
                  value={groupName}
                  onChange={event => onGroupNameChange(event.target.value)}
                  maxLength={40}
                  placeholder="输入唯一群名"
                  aria-invalid={groupNameExists}
                  className={groupNameExists ? 'border-destructive focus-visible:ring-destructive' : ''}
                />
                {groupNameExists && <p className="mt-2 text-xs text-destructive">群聊名称已存在，请换一个名称</p>}
              </section>

              <section className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="font-archive-serif text-sm font-semibold text-foreground">选择角色</h2>
                  <span className="font-archive-mono text-xs text-muted-foreground tabular-nums">{participants.length} 已选择</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {activeCharacters.map(char => {
                    const selected = participants.some(participant => participant.character_id === char.character_id);
                    return (
                      <button
                        type="button"
                        key={char.character_id}
                        onClick={() => onToggleParticipant(char)}
                        aria-pressed={selected}
                        className={`flex min-h-14 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                          selected
                            ? 'border-primary/60 bg-primary/10'
                            : 'border-border bg-background hover:bg-accent'
                        }`}
                      >
                        <ChatAvatar entity={char} sizeClass="h-9 w-9" />
                        <span className="min-w-0 flex-1 truncate font-archive-serif text-sm font-semibold text-foreground">{char.name}</span>
                        {selected && <X className="h-4 w-4 text-primary" aria-hidden="true" />}
                      </button>
                    );
                  })}
                </div>
              </section>

              {participants.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {participants.map(participant => (
                    <span key={participant.character_id} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-muted px-2 text-sm text-foreground">
                      {participant.name}
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => onToggleParticipant(participant)}
                        aria-label={`移除 ${participant.name}`}
                      >
                        <X aria-hidden="true" />
                      </Button>
                    </span>
                  ))}
                </div>
              )}

              <Button
                type="button"
                size="lg"
                className="w-full"
                onClick={onStartGroupChat}
                disabled={participants.length < 2 || !groupName.trim() || groupNameExists}
              >
                <Users aria-hidden="true" />
                开始群聊
                <span className="font-archive-mono tabular-nums">({participants.length}人)</span>
              </Button>
            </div>
          </div>
        </section>

        <aside className="hidden min-h-0 flex-col bg-card lg:flex">
          <div className="min-h-16 border-b border-border px-4 py-3">
            <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Cast Sheet</p>
            <h2 className="font-archive-serif text-base font-semibold text-foreground">群像名单</h2>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {participants.length === 0 ? (
              <p className="font-archive-serif text-sm text-muted-foreground">尚未选择角色</p>
            ) : (
              <div className="space-y-2">
                {participants.map((participant, index) => (
                  <div key={participant.character_id} className="flex items-center gap-3 border-b border-border pb-2">
                    <span className="w-6 shrink-0 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <ChatAvatar entity={participant} sizeClass="h-9 w-9" />
                    <span className="min-w-0 flex-1 truncate font-archive-serif text-sm text-foreground">{participant.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

export default ChatGroupSetup;
