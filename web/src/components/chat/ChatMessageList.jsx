import { Fragment } from 'react';
import {
  Cpu,
  Loader2,
  Pause,
  RotateCw,
  Volume2,
} from 'lucide-react';
import { Button } from '../ui/button';
import { splitAssistantReply } from '../../utils/chatMessages';
import {
  formatWorldDate,
  formatWorldTime,
  worldDateKey,
} from '../../utils/chatRoom';
import ChatAvatar from './ChatAvatar';
import ChatErrorNotice from './ChatErrorNotice';

const INLINE_ACTION_PATTERN = /(\*[^*\n]{1,80}\*|【[^【】\n]{1,80}】|\[[^[\]\n]{1,80}\]|（[^（）\n]{1,80}）)/g;

function cleanActionText(value = '') {
  return String(value)
    .trim()
    .replace(/^\*+|\*+$/g, '')
    .replace(/^[【\[\(（]\s*/, '')
    .replace(/\s*[】\]\)）]$/, '')
    .trim();
}

function MessageAction({ children }) {
  const text = cleanActionText(children);
  if (!text) return null;

  return (
    <span
      data-stage-direction
      className="font-archive-serif text-[0.94em] italic text-muted-foreground"
    >
      （{text}）
    </span>
  );
}

function MessageContent({ content }) {
  const source = String(content ?? '');
  if (!source) return null;

  const parts = [];
  let lastIndex = 0;

  source.replace(INLINE_ACTION_PATTERN, (match, _whole, offset) => {
    if (offset > lastIndex) {
      parts.push({ type: 'text', value: source.slice(lastIndex, offset) });
    }
    parts.push({ type: 'action', value: match });
    lastIndex = offset + match.length;
    return match;
  });

  if (lastIndex < source.length) {
    parts.push({ type: 'text', value: source.slice(lastIndex) });
  }

  if (parts.length === 0) return source;

  return parts.map((part, index) => (
    part.type === 'action'
      ? <MessageAction key={`${part.type}-${index}`}>{part.value}</MessageAction>
      : <span key={`${part.type}-${index}`}>{part.value}</span>
  ));
}

function RelationshipDeltaLine({ affinityDelta = 0, trustDelta = 0 }) {
  const affinity = Number(affinityDelta) || 0;
  const trust = Number(trustDelta) || 0;
  if (affinity === 0 && trust === 0) return null;

  const formatDelta = (value) => (
    Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, '')
  );

  const renderDelta = (label, value) => (
    <span className={value > 0 ? 'text-primary' : 'text-destructive'}>
      {label} {value > 0 ? '+' : ''}{formatDelta(value)}
    </span>
  );

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-archive-mono text-[11px] leading-normal tabular-nums">
      {affinity !== 0 && renderDelta('好感', affinity)}
      {trust !== 0 && renderDelta('信任', trust)}
    </div>
  );
}

function WorldDateSeparator({ value }) {
  const label = formatWorldDate(value);
  if (!label) return null;
  return (
    <div className="flex items-center gap-3 py-2" role="separator" aria-label={`世界日期 ${label}`}>
      <span className="h-px flex-1 bg-border" />
      <span className="shrink-0 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
        {label} · 世界时间
      </span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function MessageWorldTime({ value, align = 'left', pending = false }) {
  const label = formatWorldTime(value);
  if (!label && !pending) return null;
  return (
    <div className={`mt-1.5 flex items-center gap-2 font-archive-mono text-[10px] text-muted-foreground tabular-nums ${align === 'right' ? 'justify-end' : 'justify-start'}`}>
      {label && <time dateTime={value}>{label}</time>}
      {pending && <span>待发送</span>}
    </div>
  );
}

function MessageAudioControl({
  messageId,
  messageSessionId,
  getAudioState,
  onToggle,
  onRetry,
}) {
  const audioState = getAudioState(messageId, messageSessionId);
  const status = audioState.status || 'idle';
  const isLoading = status === 'loading';
  const isPlaying = status === 'playing';
  const isError = status === 'error';
  const label = isLoading
    ? '正在生成语音'
    : isPlaying
      ? '暂停语音'
      : isError
        ? '重试语音'
        : status === 'paused'
          ? '继续播放语音'
          : '播放语音';

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={() => (
        isError
          ? onRetry(messageId, messageSessionId)
          : onToggle(messageId, messageSessionId)
      )}
      disabled={isLoading}
      className={`mt-1 border border-border ${isError ? 'text-destructive' : 'text-muted-foreground hover:text-foreground'}`}
      aria-label={label}
      title={audioState.error || label}
    >
      {isLoading ? <Loader2 size={15} className="animate-spin" />
        : isPlaying ? <Pause size={15} />
          : isError ? <RotateCw size={15} />
            : <Volume2 size={15} />}
    </Button>
  );
}

export function ChatMessageList({
  messages,
  isSingle,
  character,
  getCharById,
  getAudioState,
  onToggleAudio,
  onRetryAudio,
  sending,
  error,
  onDismissError,
  loadingHistory,
  hasMoreHistory,
  onLoadMore,
  messageScrollRef,
  bottomRef,
}) {
  return (
    <div
      ref={messageScrollRef}
      style={{ overflowAnchor: 'none' }}
      className="relative min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5"
      onScroll={event => {
        if (event.target.scrollTop < 60 && !loadingHistory && hasMoreHistory) onLoadMore();
      }}
    >
      <div className="mx-auto max-w-3xl space-y-4">
        <ChatErrorNotice error={error} onDismiss={onDismissError} />
        {messages.flatMap((message, messageIndex) => {
          const isUser = message.role === 'user';
          const charInfo = message.charId ? getCharById(message.charId) : null;
          const replyParagraphs = isUser ? [message.content] : splitAssistantReply(message.content);
          const currentWorldDate = worldDateKey(message.world_created_at);
          const previousWorldDate = worldDateKey(messages[messageIndex - 1]?.world_created_at);
          const showWorldDate = Boolean(currentWorldDate && currentWorldDate !== previousWorldDate);

          return replyParagraphs.map((paragraph, paragraphIndex) => {
            const isLastParagraph = paragraphIndex === replyParagraphs.length - 1;
            const speaker = isSingle
              ? character?.name
              : message.charName || charInfo?.name || '未知角色';
            return (
              <Fragment key={`${message.message_id ?? message.client_id ?? messageIndex}-${paragraphIndex}`}>
                {paragraphIndex === 0 && showWorldDate && <WorldDateSeparator value={message.world_created_at} />}
                <div
                  data-message-layout={isUser ? 'chat' : 'script'}
                  className={isUser ? 'flex justify-end' : 'min-w-0'}
                >
                  {isUser ? (
                    <div className="max-w-[84%] sm:max-w-[70%]">
                      <div className="rounded-md border border-primary/25 bg-primary/10 px-3 py-2 text-sm leading-6 text-foreground">
                        <MessageContent content={paragraph} />
                      </div>
                      {isLastParagraph && (
                        <MessageWorldTime
                          value={message.world_created_at}
                          align="right"
                          pending={message._pending}
                        />
                      )}
                    </div>
                  ) : (
                    <div className="flex min-w-0 gap-3">
                      <ChatAvatar entity={charInfo || character} sizeClass="h-9 w-9" extraClass="mt-0.5" />
                      <article data-archive-script-message className="min-w-0 flex-1 border-l border-border pl-3">
                        <div data-scene-speaker className="font-archive-mono text-[10px] font-semibold uppercase text-primary">
                          {speaker}
                        </div>
                        {paragraphIndex === 0 && message.action && (
                          <div className="mt-1 leading-6">
                            <MessageAction>{message.action}</MessageAction>
                          </div>
                        )}
                        <p className="mt-1 whitespace-pre-wrap break-words font-archive-serif text-[15px] leading-7 text-foreground">
                          <MessageContent content={paragraph} />
                        </p>
                        {message.showRelationshipDelta && isLastParagraph && (
                          <RelationshipDeltaLine
                            affinityDelta={message.affinity_delta}
                            trustDelta={message.trust_delta}
                          />
                        )}
                        {isLastParagraph && (
                          <MessageWorldTime
                            value={message.world_created_at}
                          />
                        )}
                        {isLastParagraph && message.message_id != null && (
                          <MessageAudioControl
                            messageId={message.message_id}
                            messageSessionId={message.session_id}
                            getAudioState={getAudioState}
                            onToggle={onToggleAudio}
                            onRetry={onRetryAudio}
                          />
                        )}
                      </article>
                    </div>
                  )}
                </div>
              </Fragment>
            );
          });
        })}

        {sending && (
          <div className="flex min-w-0 gap-3" role="status">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted">
              <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
            </span>
            <div data-archive-script-message className="min-w-0 flex-1 border-l border-border pl-3">
              <div data-scene-speaker className="font-archive-mono text-[10px] font-semibold uppercase text-primary">
                {isSingle ? character?.name : '群像'}
              </div>
              <div className="mt-1 flex items-center gap-2 font-archive-serif text-sm italic text-muted-foreground">
                <Cpu className="h-4 w-4 animate-pulse" aria-hidden="true" />
                <span data-stage-direction>（正在组织回应）</span>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {loadingHistory && (
        <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
          <span className="rounded-md border border-border bg-card p-2 text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            <span className="sr-only">正在加载历史消息</span>
          </span>
        </div>
      )}
    </div>
  );
}

export default ChatMessageList;
