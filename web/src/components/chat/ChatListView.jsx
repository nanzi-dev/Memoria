import { Fragment } from 'react';
import {
  MessageSquare,
  Plus,
  Search,
} from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs';
import { formatChatTime } from '../../utils/chatRoom';
import ChatAvatar from './ChatAvatar';
import ChatErrorNotice from './ChatErrorNotice';
import ChatSummaryRow from './ChatSummaryRow';

export function ChatSessionDirectory({
  embedded = false,
  className = '',
  activeTab,
  onTabChange,
  searchQuery,
  onSearchChange,
  chatItems,
  allChars,
  error,
  onDismissError,
  isCharacterActive,
  normalizeParticipant,
  onEnterGroupSetup,
  onRequestSingleChat,
  onEnterGroupChat,
  onOfflineContact,
}) {
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredItems = chatItems.filter(item => {
    if (!normalizedQuery) return true;
    const name = item.type === 'single' ? item.name : item.group_name || '';
    return (
      name.toLowerCase().includes(normalizedQuery)
      || String(item.last_message || '').toLowerCase().includes(normalizedQuery)
    );
  });
  const contacts = allChars.filter(char => {
    if (!normalizedQuery) return true;
    return String(char.name || '').toLowerCase().includes(normalizedQuery);
  });

  function renderDirectoryItem(item, index) {
    const timeLabel = formatChatTime(item.last_message_at);
    if (item.type === 'group') {
      const groupParts = (item.participants || []).map(participant => normalizeParticipant(participant));
      const unreadCount = Math.max(0, Number(item.unread_count || 0));
      return (
        <button
          type="button"
          key={`group-${item.group_thread_id || item.session_id || index}`}
          onClick={() => onEnterGroupChat(item, groupParts)}
          className="flex min-h-16 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex shrink-0 -space-x-2">
            {groupParts.slice(0, 3).map((participant, participantIndex) => (
              <Fragment key={participant.character_id || participantIndex}>
                <ChatAvatar entity={participant} sizeClass="h-9 w-9" extraClass="border-card" />
              </Fragment>
            ))}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-archive-serif text-sm font-semibold text-foreground">
              {item.group_name || '群聊'}
            </span>
            <span className="block truncate text-xs text-muted-foreground">{item.last_message || '暂无消息'}</span>
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
            <span>{timeLabel}</span>
            {unreadCount > 0 && (
              <span className="rounded-md border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-primary" aria-label={`${unreadCount} 条未读消息`}>
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </span>
        </button>
      );
    }

    const active = isCharacterActive(item);
    return (
      <button
        type="button"
        key={item.session_id || index}
        onClick={() => onRequestSingleChat(item)}
        className="flex min-h-16 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChatAvatar entity={item} sizeClass="h-10 w-10" extraClass={active ? '' : 'grayscale opacity-55'} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate font-archive-serif text-sm font-semibold text-foreground">{item.name}</span>
            {!active && <span className="rounded-md border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">离线</span>}
          </span>
          <span className="block truncate text-xs text-muted-foreground">{item.last_message || '暂无消息'}</span>
        </span>
        <span className="shrink-0 font-archive-mono text-[10px] text-muted-foreground tabular-nums">{timeLabel}</span>
      </button>
    );
  }

  return (
    <section className={`${embedded ? 'hidden lg:flex' : 'flex'} ${className} min-h-0 min-w-0 flex-col border-r border-border bg-card`}>
      <div className="flex min-h-16 items-center gap-2 border-b border-border px-3">
        <div className="min-w-0 flex-1">
          <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Dialogue Archive</p>
          <h1 className="truncate font-archive-serif text-base font-semibold text-foreground">会话目录</h1>
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={onEnterGroupSetup}
          aria-label="新建群聊"
          title="新建群聊"
        >
          <Plus aria-hidden="true" />
        </Button>
      </div>

      <div className="space-y-3 border-b border-border p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            value={searchQuery}
            onChange={event => onSearchChange(event.target.value)}
            placeholder={activeTab === 'chat' ? '搜索对话' : '搜索联系人'}
            className="pl-9"
          />
        </div>
        <Tabs
          value={activeTab}
          onValueChange={onTabChange}
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="chat">对话</TabsTrigger>
            <TabsTrigger value="contacts">联系人</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <ChatErrorNotice error={error} onDismiss={onDismissError} />
        {activeTab === 'chat' && (
          <div className="mt-2 space-y-1">
            {filteredItems.length === 0 ? (
              <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center text-muted-foreground">
                <MessageSquare className="h-5 w-5" aria-hidden="true" />
                <p className="font-archive-serif text-sm">暂无对话记录</p>
              </div>
            ) : filteredItems.map((item, index) => renderDirectoryItem(item, index))}
          </div>
        )}
        {activeTab === 'contacts' && (
          <div className="mt-2 space-y-1">
            {contacts.map((char, index) => {
              const active = isCharacterActive(char);
              return (
                <button
                  type="button"
                  key={char.character_id}
                  onClick={() => active
                    ? onRequestSingleChat(char)
                    : onOfflineContact()}
                  className="flex min-h-14 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}
                >
                  <ChatAvatar entity={char} sizeClass="h-10 w-10" extraClass={active ? '' : 'grayscale opacity-55'} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-archive-serif text-sm font-semibold text-foreground">{char.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{char.core_identity || (active ? '在线' : '离线')}</span>
                  </span>
                  <span className={`h-2 w-2 rounded-sm ${active ? 'bg-primary' : 'bg-muted-foreground/45'}`} aria-hidden="true" />
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

export function ChatArchiveSummary({
  chatItems,
  allChars,
  isCharacterActive,
  onRequestSingleChat,
}) {
  const activeContacts = allChars.filter(char => isCharacterActive(char)).length;
  const groupCount = chatItems.filter(item => item.type === 'group').length;
  return (
    <aside className="hidden min-h-0 flex-col bg-background lg:flex">
      <div className="min-h-16 border-b border-border px-4 py-3">
        <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Archive Status</p>
        <h2 className="font-archive-serif text-base font-semibold text-foreground">叙事索引</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <dl className="divide-y divide-border border-y border-border">
          <ChatSummaryRow label="全部会话" value={chatItems.length} />
          <ChatSummaryRow label="群聊会话" value={groupCount} />
          <ChatSummaryRow label="在线角色" value={activeContacts} />
          <ChatSummaryRow label="角色总数" value={allChars.length} />
        </dl>
        <div className="mt-5">
          <h3 className="font-archive-serif text-sm font-semibold text-foreground">在线联系人</h3>
          <div className="mt-2 space-y-1">
            {allChars.filter(char => isCharacterActive(char)).slice(0, 8).map(char => (
              <button
                type="button"
                key={char.character_id}
                onClick={() => onRequestSingleChat(char)}
                className="flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ChatAvatar entity={char} sizeClass="h-8 w-8" />
                <span className="min-w-0 flex-1 truncate font-archive-serif text-sm text-foreground">{char.name}</span>
                <span className="h-2 w-2 rounded-sm bg-primary" aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

export default function ChatListView(props) {
  return (
    <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
      <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
        <ChatSessionDirectory {...props} className="lg:col-span-2" />
        <ChatArchiveSummary
          chatItems={props.chatItems}
          allChars={props.allChars}
          isCharacterActive={props.isCharacterActive}
          onRequestSingleChat={props.onRequestSingleChat}
        />
      </div>
    </div>
  );
}
