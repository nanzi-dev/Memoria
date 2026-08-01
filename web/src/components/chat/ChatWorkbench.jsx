import { Fragment } from 'react';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { Button } from '../ui/button';
import UserSettingsModal from '../UserSettingsModal';
import { EventInboxBanner, WorldClockDisplay } from '../WorldClock';
import { MOOD_LABELS } from '../../utils/chatRoom';
import ChatAvatar from './ChatAvatar';
import ChatComposer from './ChatComposer';
import ChatMessageList from './ChatMessageList';
import ChatProfilePanel from './ChatProfilePanel';
import { ChatSessionDirectory } from './ChatListView';

export function ChatWorkbench({
  mode,
  activeTab,
  onTabChange,
  searchQuery,
  onSearchChange,
  chatItems,
  allChars,
  error,
  onDismissError,
  onEnterGroupSetup,
  onRequestSingleChat,
  onEnterGroupChat,
  onOfflineContact,
  character,
  participants,
  groupName,
  singleSessionId,
  multiSessionId,
  multiSessionStatus,
  groupHistoryReady,
  messages,
  input,
  affinity,
  trust,
  mood,
  events,
  isRecovered,
  sending,
  sendingMulti,
  showDetail,
  onToggleDetail,
  showClockSettings,
  onShowClockSettings,
  onCloseClockSettings,
  onGoToList,
  onInputChange,
  onInputKeyDown,
  onSend,
  loadingHistory,
  hasMoreHistory,
  onLoadMore,
  inputRef,
  messageScrollRef,
  bottomRef,
  speechStatus,
  speechError,
  isRecordingSupported,
  onStartRecording,
  onStopRecording,
  onDismissSpeechError,
  getAudioState,
  onToggleAudio,
  onRetryAudio,
  isCharacterActive,
  normalizeParticipant,
  getCharById,
  onClearEvents,
}) {
  const isSingle = mode === 'single';
  const singleReadOnly = isSingle && !isCharacterActive(character);
  const resolvedParticipants = participants.map(participant => normalizeParticipant(participant));
  const activeParticipantCount = resolvedParticipants.filter(participant => isCharacterActive(participant)).length;
  const title = isSingle ? character?.name : groupName || '群聊';
  const status = isSingle
    ? (singleReadOnly ? '离线 · 只读' : sending ? '正在回应' : MOOD_LABELS[mood])
    : (sendingMulti ? '角色思考中' : `${activeParticipantCount}/${resolvedParticipants.length} 在线`);

  return (
    <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
      <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
        <ChatSessionDirectory
          embedded
          activeTab={activeTab}
          onTabChange={onTabChange}
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
          chatItems={chatItems}
          allChars={allChars}
          error={error}
          onDismissError={onDismissError}
          isCharacterActive={isCharacterActive}
          normalizeParticipant={normalizeParticipant}
          onEnterGroupSetup={onEnterGroupSetup}
          onRequestSingleChat={onRequestSingleChat}
          onEnterGroupChat={onEnterGroupChat}
          onOfflineContact={onOfflineContact}
        />
        <section className="flex min-h-0 min-w-0 flex-col bg-background">
          <div className="flex min-h-16 items-center gap-2 border-b border-border px-2 sm:px-3">
            <Button type="button" variant="ghost" size="icon" onClick={onGoToList} className="lg:hidden" aria-label="返回会话目录">
              <ArrowLeft aria-hidden="true" />
            </Button>
            <button
              type="button"
              onClick={onToggleDetail}
              className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:pointer-events-none"
            >
              {isSingle
                ? <ChatAvatar entity={character} sizeClass="h-9 w-9" />
                : (
                  <span className="flex shrink-0 -space-x-2">
                    {resolvedParticipants.slice(0, 2).map(participant => (
                      <Fragment key={participant.character_id}>
                        <ChatAvatar entity={participant} sizeClass="h-9 w-9" extraClass="border-background" />
                      </Fragment>
                    ))}
                  </span>
                )}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-archive-serif text-base font-semibold text-foreground">{title}</span>
                <span className="block truncate font-archive-mono text-[10px] text-muted-foreground tabular-nums">{status}</span>
              </span>
            </button>
            <div className="hidden min-w-0 sm:block">
              <WorldClockDisplay
                className="max-w-[220px]"
                onClick={onShowClockSettings}
              />
            </div>
            {isSingle && events.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="relative text-destructive"
                onClick={onClearEvents}
                aria-label="清除事件通知"
                title="清除事件通知"
              >
                <AlertTriangle aria-hidden="true" />
                <span className="absolute right-1 top-1 min-w-4 rounded-sm bg-destructive px-1 font-archive-mono text-[9px] text-destructive-foreground tabular-nums">
                  {events.length}
                </span>
              </Button>
            )}
          </div>

          <EventInboxBanner
            characterId={isSingle ? character?.character_id : null}
            sessionId={isSingle ? singleSessionId : multiSessionId}
          />

          {showDetail && (
            <div className="max-h-[42dvh] overflow-y-auto border-b border-border bg-card p-3 lg:hidden">
              <ChatProfilePanel
                mode={mode}
                mobile
                character={character}
                participants={participants}
                groupName={groupName}
                multiSessionId={multiSessionId}
                multiSessionStatus={multiSessionStatus}
                groupHistoryReady={groupHistoryReady}
                affinity={affinity}
                trust={trust}
                mood={mood}
                events={events}
                messages={messages}
                isRecovered={isRecovered}
                isCharacterActive={isCharacterActive}
                normalizeParticipant={normalizeParticipant}
              />
            </div>
          )}

          <ChatMessageList
            messages={messages}
            isSingle={isSingle}
            character={character}
            getCharById={getCharById}
            getAudioState={getAudioState}
            onToggleAudio={onToggleAudio}
            onRetryAudio={onRetryAudio}
            sending={sending}
            error={error}
            onDismissError={onDismissError}
            loadingHistory={loadingHistory}
            hasMoreHistory={hasMoreHistory}
            onLoadMore={onLoadMore}
            messageScrollRef={messageScrollRef}
            bottomRef={bottomRef}
          />

          <ChatComposer
            input={input}
            inputRef={inputRef}
            onInputChange={onInputChange}
            onKeyDown={onInputKeyDown}
            singleReadOnly={singleReadOnly}
            sending={sending}
            sendingMulti={sendingMulti}
            speechStatus={speechStatus}
            speechError={speechError}
            isRecordingSupported={isRecordingSupported}
            onStartRecording={onStartRecording}
            onStopRecording={onStopRecording}
            onDismissSpeechError={onDismissSpeechError}
            onSend={onSend}
          />
        </section>
        <aside className="hidden min-h-0 flex-col border-l border-border bg-card lg:flex">
          <ChatProfilePanel
            mode={mode}
            character={character}
            participants={participants}
            groupName={groupName}
            multiSessionId={multiSessionId}
            multiSessionStatus={multiSessionStatus}
            groupHistoryReady={groupHistoryReady}
            affinity={affinity}
            trust={trust}
            mood={mood}
            events={events}
            messages={messages}
            isRecovered={isRecovered}
            isCharacterActive={isCharacterActive}
            normalizeParticipant={normalizeParticipant}
          />
        </aside>
      </div>
      {showClockSettings && <UserSettingsModal onClose={onCloseClockSettings} />}
    </div>
  );
}

export default ChatWorkbench;
