import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { useSearchParams, useNavigate } from 'react-router-dom';

import { useUser } from '../context/UserContext';

import { dialogue, multiDialogue, characterAdmin } from '../api/memoria';

import { EventInboxBanner, WorldClockDisplay } from '../components/WorldClock';
import UserSettingsModal from '../components/UserSettingsModal';
import { useArchiveShell } from '../archive/ArchiveShell';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';

import { splitAssistantReply } from '../utils/chatMessages';
import { beginOwnedRequest, createRequestEpoch } from '../utils/asyncRequestState';
import {
  canApplySingleHistory,
  createPendingUserMessage,
  removePendingMessage,
  restoreFailedDraft,
  settlePendingMessage,
} from './chatOptimisticState';
import {
  appendDialogueDelta,
  completeCharacter,
  reconcileTurn,
  startCharacter,
} from '../utils/dialogueStreamState';
import { retryDialogueTurnConflict } from '../utils/dialogueFallback';
import useBrowserSpeech from '../hooks/useBrowserSpeech';

import {

  Send, ArrowLeft, AlertTriangle, Loader2, User, X, Plus, Users,

  Search, Cpu, MessageSquare, Mic, Square, Volume2,
  Pause, RotateCw

} from 'lucide-react';



// ═══════════════════════════════════════════════

// Constants

// ═══════════════════════════════════════════════

const MOOD_LABELS = {

  happy: '开心', neutral: '平静', sad: '悲伤', angry: '愤怒',

  surprised: '惊讶', fearful: '恐惧', disgusted: '厌恶',

};

const MOOD_EMOJI = { happy: '😊', neutral: '😐', sad: '😢', angry: '😠', surprised: '😲', fearful: '😨', disgusted: '😖' };

const IDLE_SESSION_END_MS = 5 * 60 * 1000;
const HISTORY_PAGE_SIZE = 20;
const GROUP_POLL_INTERVAL_MS = 3 * 1000;

export function applyDialogueStreamEvent(messages, event) {
  switch (event?.type) {
    case 'character_started':
      return startCharacter(messages, event);
    case 'dialogue_delta':
      return appendDialogueDelta(messages, event);
    case 'character_completed':
      return completeCharacter(messages, event);
    case 'turn_completed':
      return reconcileTurn(messages, event);
    default:
      return messages;
  }
}

export function removeDialogueStreamPlaceholders(messages, streamIds) {
  const ownedStreamIds = streamIds instanceof Set
    ? streamIds
    : new Set(streamIds || []);
  if (!ownedStreamIds.size) return messages;
  return messages.filter(message => !ownedStreamIds.has(message.stream_id));
}

export function shouldFallbackFromDialogueStream(hasReceivedDelta) {
  return true;
}
const toDelta = (value) => {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
};

const currentDelta = (currentValue, previousValue, fallbackDelta = 0) => {
  if (currentValue == null) return toDelta(fallbackDelta);
  const current = Number(currentValue);
  const previous = Number(previousValue ?? 0);
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return toDelta(fallbackDelta);
  const delta = current - previous;
  return Number.isFinite(delta) ? Number(delta.toFixed(6)) : toDelta(fallbackDelta);
};

function normalizeDialogueMessage(message, options = {}) {
  return {
    role: message.role,
    content: message.content,
    action: message.action || '',
    affinity_delta: toDelta(message.affinity_delta),
    trust_delta: toDelta(message.trust_delta),
    showRelationshipDelta: options.showRelationshipDelta === true,
    created_at: message.created_at,
    world_created_at: message.world_created_at,
    message_id: message.message_id ?? message.id,
    session_id: message.session_id,
  };
}

function normalizeGroupMessage(message, knownParticipants = [], options = {}) {
  const charId = message.charId ?? message.character_id ?? message.speaker_id ?? '';
  const participant = charId
    ? knownParticipants.find(p => p.character_id === charId || p.charId === charId)
    : null;
  const role = message.role ?? (charId ? 'assistant' : 'user');
  const charName = message.charName ?? message.character_name ?? participant?.name ?? participant?.display_name ?? '';

  return {
    role,
    charId: charId === '' ? undefined : charId,
    charName: role === 'assistant' ? (charName || charId || '未知') : undefined,
    content: message.content ?? message.dialogue ?? message.message ?? '',
    action: message.action ?? '',
    affinity_delta: toDelta(message.affinity_delta),
    trust_delta: toDelta(message.trust_delta),
    showRelationshipDelta: options.showRelationshipDelta === true,
    created_at: message.created_at ?? message.world_created_at,
    world_created_at: message.world_created_at,
    message_id: message.message_id ?? message.id,
    session_id: message.session_id,
    reply_to_message_id: message.reply_to_message_id,
    reply_to_character_id: message.reply_to_character_id,
    intent: message.intent,
    topic: message.topic,
    trigger_source: message.trigger_source,
    client_id: message.client_id,
    _pending: message._pending,
  };
}

function stableGroupMessageKey(message) {
  return message?.message_id == null ? null : String(message.message_id);
}

function mergeGroupMessageFields(current, incoming) {
  const merged = { ...current };
  Object.entries(incoming).forEach(([key, value]) => {
    if (value !== undefined) merged[key] = value;
  });
  if (current.action && !incoming.action) merged.action = current.action;
  if (current.showRelationshipDelta === true && incoming.showRelationshipDelta !== true) {
    merged.affinity_delta = current.affinity_delta;
    merged.trust_delta = current.trust_delta;
  }
  merged.showRelationshipDelta = current.showRelationshipDelta === true || incoming.showRelationshipDelta === true;
  return merged;
}

function mergeGroupMessages(currentMessages, incomingMessages, options = {}) {
  const prepend = options.prepend === true;
  const replacePending = options.replacePending !== false && !prepend;
  const combined = prepend
    ? [...incomingMessages, ...currentMessages]
    : [...currentMessages, ...incomingMessages];
  const merged = [];
  const messageIndexById = new Map();

  combined.forEach(message => {
    const messageId = stableGroupMessageKey(message);
    if (messageId != null && messageIndexById.has(messageId)) {
      const existingIndex = messageIndexById.get(messageId);
      merged[existingIndex] = mergeGroupMessageFields(merged[existingIndex], message);
      return;
    }

    if (replacePending && messageId != null && message.role === 'user') {
      const pendingIndex = merged.findIndex(candidate => (
        candidate._pending === true
        && candidate.role === 'user'
        && candidate.content === message.content
      ));
      if (pendingIndex >= 0) {
        merged[pendingIndex] = {
          ...mergeGroupMessageFields(merged[pendingIndex], message),
          _pending: false,
        };
        messageIndexById.set(messageId, pendingIndex);
        return;
      }
    }

    if (messageId != null) messageIndexById.set(messageId, merged.length);
    merged.push(message);
  });

  if (merged.some(message => message._pending === true)) return merged;

  return merged
    .map((message, index) => ({ message, index }))
    .sort((left, right) => {
      const leftId = Number(left.message.message_id);
      const rightId = Number(right.message.message_id);
      if (Number.isFinite(leftId) && Number.isFinite(rightId) && leftId !== rightId) {
        return leftId - rightId;
      }
      return left.index - right.index;
    })
    .map(item => item.message);
}

function maxGroupMessageId(messages, fallback = 0) {
  return messages.reduce((latest, message) => {
    const messageId = Number(message?.message_id);
    return Number.isFinite(messageId) ? Math.max(latest, messageId) : latest;
  }, fallback);
}

function createRequestId(prefix = 'request') {
  return globalThis.crypto?.randomUUID?.()
    ?? `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function createClientMessageId() {
  return createRequestId('group-message');
}

function formatChatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function worldDateKey(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

function formatWorldDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(date);
}

function formatWorldTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
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

function MessageWorldTime({ value, align = 'left', messageId, pending = false }) {
  const label = formatWorldTime(value);
  if (!label && messageId == null && !pending) return null;
  return (
    <div className={`mt-1.5 flex items-center gap-2 font-archive-mono text-[10px] text-muted-foreground tabular-nums ${align === 'right' ? 'justify-end' : 'justify-start'}`}>
      {label && <time dateTime={value}>{label}</time>}
      {messageId != null && <span>#{messageId}</span>}
      {pending && <span>待发送</span>}
    </div>
  );
}

function sortMessagesChronologically(messages) {
  return [...messages].sort((a, b) => {
    const timeA = a.created_at ? new Date(a.created_at).getTime() : NaN;
    const timeB = b.created_at ? new Date(b.created_at).getTime() : NaN;
    const hasTimeA = !Number.isNaN(timeA);
    const hasTimeB = !Number.isNaN(timeB);

    if (hasTimeA && hasTimeB && timeA !== timeB) return timeA - timeB;
    if (hasTimeA !== hasTimeB) return hasTimeA ? -1 : 1;

    const idA = Number(a.message_id);
    const idB = Number(b.message_id);
    if (!Number.isNaN(idA) && !Number.isNaN(idB) && idA !== idB) return idA - idB;

    return 0;
  });
}

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

function SpeechRecorderButton({ status, supported, disabled, onStart, onStop }) {
  const isRecording = status === 'recording';
  const isTranscribing = status === 'transcribing';
  const label = isRecording
    ? '停止录音并转写'
    : isTranscribing
      ? '正在转写录音'
      : supported
        ? '开始语音输入'
        : '当前浏览器不支持录音';

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      onClick={isRecording ? onStop : onStart}
      disabled={disabled || isTranscribing || (!supported && !isRecording)}
      className={`shrink-0 ${isRecording ? 'border-destructive/60 bg-destructive/10 text-destructive' : 'text-muted-foreground'}`}
      aria-label={label}
      title={label}
    >
      {isTranscribing ? <Loader2 size={16} className="animate-spin" />
        : isRecording ? <Square size={15} fill="currentColor" />
          : <Mic size={17} />}
    </Button>
  );
}

function SpeechErrorNotice({ error, onDismiss, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-2 flex items-center gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 text-xs leading-5 text-destructive">
      <AlertTriangle size={13} className="shrink-0" />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      <Button type="button" variant="ghost" size="icon" onClick={onRetry} className="shrink-0 text-destructive" aria-label="重试语音输入" title="重试语音输入">
        <RotateCw size={14} />
      </Button>
      <Button type="button" variant="ghost" size="icon" onClick={onDismiss} className="shrink-0 text-destructive" aria-label="关闭语音错误">
        <X size={15} />
      </Button>
    </div>
  );
}

// ═══════════════════════════════════════════════

// ChatRoom — Main Container

// ═══════════════════════════════════════════════

export default function ChatRoom() {

  const [searchParams] = useSearchParams();

  const navigate = useNavigate();
  const { setPrimaryAction } = useArchiveShell();

  const { user, loading: userLoading, worldClock, getWorldNow } = useUser();



  const characterIdParam = searchParams.get('character');



  const PLAYER_ID = user?.user_id || '';

  const PLAYER_NAME = user?.username || '';



  // ── View state ──

  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'contacts'

  const [view, setView] = useState('list'); // 'list' | 'single-loading' | 'single' | 'group-setup' | 'group'



  // ── Shared state ──

  const [allChars, setAllChars] = useState([]);

  const [chatItems, setChatItems] = useState([]); // session-based chat list

  const [sessionsLoaded, setSessionsLoaded] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');

  const [error, setError] = useState(null);

  // ── History loading ──

  const [historyOffset, setHistoryOffset] = useState(0);

  const [hasMoreHistory, setHasMoreHistory] = useState(true);

  const [loadingHistory, setLoadingHistory] = useState(false);
  const [isRecovered, setIsRecovered] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showClockSettings, setShowClockSettings] = useState(false);



  // ── Single chat state ──

  const [character, setCharacter] = useState(null);

  const [singleSessionId, setSingleSessionId] = useState(null);

  const [affinity, setAffinity] = useState(0);

  const [trust, setTrust] = useState(0);

  const [mood, setMood] = useState('neutral');

  const [events, setEvents] = useState([]);



  // ── Group chat state ──

  const [participants, setParticipants] = useState([]);

  const [multiSessionId, setMultiSessionId] = useState(null);

  const [multiSessionStatus, setMultiSessionStatus] = useState('active');

  const [groupHistoryReady, setGroupHistoryReady] = useState(false);

  const [groupName, setGroupName] = useState('');
  const cleanGroupName = groupName.trim();
  const groupNameExists = cleanGroupName
    ? chatItems.some(item => item.type === 'group' && (item.group_name || '').trim().toLowerCase() === cleanGroupName.toLowerCase())
    : false;



  // ── Chat state ──

  const [messages, setMessages] = useState([]);

  const [input, setInput] = useState('');

  const [sending, setSending] = useState(false);

  const [sendingMulti, setSendingMulti] = useState(false);

  const bottomRef = useRef(null);

  const inputRef = useRef(null);

  const messageScrollRef = useRef(null);

  const activeSessionRef = useRef(null);

  const idleEndTimersRef = useRef(new Map());

  const sessionKindRef = useRef(new Map());

  const skipAutoScrollRef = useRef(false);

  const pendingInitialSingleScrollRef = useRef(false);

  const pendingInitialGroupScrollRef = useRef(false);

  const pendingHistoryScrollRef = useRef(null);

  const latestGroupMessageIdRef = useRef(0);

  const loadedGroupMessageIdsRef = useRef(new Set());

  const groupPollInFlightRef = useRef(null);

  const activeGroupThreadIdRef = useRef(null);

  const activeGroupSessionIdRef = useRef(null);

  const groupRequestGenerationRef = useRef(0);

  const singleRequestGenerationRef = useRef(0);
  const activeSingleCharacterIdRef = useRef(null);

  const activeSendRequestRef = useRef(null);
  const activeStreamAbortControllerRef = useRef(null);

  const sendMessageRef = useRef(null);

  const directCharacterHandledRef = useRef(null);
  const playerIdRef = useRef(PLAYER_ID);
  const sessionListEpochRef = useRef(null);
  playerIdRef.current = PLAYER_ID;
  if (!sessionListEpochRef.current) sessionListEpochRef.current = createRequestEpoch();

  const handleTranscription = useCallback((text) => {
    const cleanText = String(text || '').trim();
    if (!cleanText) return;
    setInput(cleanText);
    if (user?.stt_auto_send) {
      queueMicrotask(() => sendMessageRef.current?.(cleanText));
    }
  }, [user?.stt_auto_send]);

  const {
    speechStatus,
    speechError,
    isRecordingSupported,
    startRecording,
    stopRecording,
    cancelRecording,
    clearSpeechError,
    getAudioState,
    toggleAudio,
    retryAudio,
    enqueueAutoplay,
    stopAudio,
  } = useBrowserSpeech({
    sessionId: view === 'single' ? singleSessionId : view === 'group' ? multiSessionId : null,
    mode: view === 'single' ? 'single' : view === 'group' ? 'group' : null,
    onTranscription: handleTranscription,
  });



  function isCharacterActive(char) {
    return char?.is_active == null || char?.is_active === true || char?.is_active === 1;
  }

  function getCharacterCard(char, charList = allChars) {
    if (!char?.character_id) return null;
    return charList.find(c => c.character_id === char.character_id) || null;
  }

  function normalizeParticipant(participant, charList = allChars) {
    const card = getCharacterCard(participant, charList);
    const participantActive = isCharacterActive(participant);
    const cardActive = card ? isCharacterActive(card) : true;

    return {
      ...participant,
      character_id: participant?.character_id || card?.character_id,
      name: participant?.name || card?.name || participant?.character_id || '未知',
      avatar_url: participant?.avatar_url || card?.avatar_url || null,
      is_active: participantActive && cardActive,
    };
  }

  function resetGroupSyncState() {
    groupRequestGenerationRef.current += 1;
    latestGroupMessageIdRef.current = 0;
    loadedGroupMessageIdsRef.current = new Set();
    groupPollInFlightRef.current = null;
    activeGroupThreadIdRef.current = null;
    activeGroupSessionIdRef.current = null;
    pendingInitialGroupScrollRef.current = false;
    setGroupHistoryReady(false);
  }

  function invalidatePendingSend() {
    activeStreamAbortControllerRef.current?.abort();
    activeStreamAbortControllerRef.current = null;
    activeSendRequestRef.current = null;
    setSending(false);
    setSendingMulti(false);
  }

  function nextSingleRequestGeneration() {
    singleRequestGenerationRef.current += 1;
    activeSingleCharacterIdRef.current = null;
    invalidatePendingSend();
    return singleRequestGenerationRef.current;
  }

  function registerLoadedGroupMessages(groupMessages) {
    let added = 0;
    groupMessages.forEach(message => {
      const messageId = stableGroupMessageKey(message);
      if (messageId == null || loadedGroupMessageIdsRef.current.has(messageId)) return;
      loadedGroupMessageIdsRef.current.add(messageId);
      added += 1;
    });
    return added;
  }



  function clearIdleSessionEnd(sessionId = null) {

    if (sessionId) {

      const timer = idleEndTimersRef.current.get(sessionId);

      if (timer) clearTimeout(timer);

      idleEndTimersRef.current.delete(sessionId);

      return;

    }

    idleEndTimersRef.current.forEach(timer => clearTimeout(timer));

    idleEndTimersRef.current.clear();

  }



  function scheduleIdleSessionEnd(sessionId) {

    if (!sessionId) return;

    clearIdleSessionEnd(sessionId);

    const timer = setTimeout(() => {

      const endSession = sessionKindRef.current.get(sessionId) === 'group'
        ? multiDialogue.endSession
        : dialogue.endSession;

      endSession(sessionId)

        .catch(() => {})

        .finally(() => {

          if (activeSessionRef.current === sessionId) activeSessionRef.current = null;

          sessionKindRef.current.delete(sessionId);

          idleEndTimersRef.current.delete(sessionId);

          loadSessions();

        });

    }, IDLE_SESSION_END_MS);

    idleEndTimersRef.current.set(sessionId, timer);

  }



  function closeTrackedSessionsOnUnload() {
    activeStreamAbortControllerRef.current?.abort();
    activeStreamAbortControllerRef.current = null;

    idleEndTimersRef.current.forEach(timer => clearTimeout(timer));

    const sessionIds = Array.from(new Set([activeSessionRef.current, ...idleEndTimersRef.current.keys()].filter(Boolean)));

    sessionIds.forEach(sessionId => {
      if (sessionKindRef.current.get(sessionId) === 'group') {
        multiDialogue.endSessionOnUnload(sessionId);
      } else {
        dialogue.endSessionOnUnload(sessionId);
      }
    });

    activeSessionRef.current = null;

    sessionKindRef.current.clear();

    idleEndTimersRef.current.clear();

  }



  useEffect(() => {

    const handlePageHide = () => closeTrackedSessionsOnUnload();

    window.addEventListener('pagehide', handlePageHide);

    return () => {

      window.removeEventListener('pagehide', handlePageHide);

      closeTrackedSessionsOnUnload();

    };

  }, []);



  // ── Load all characters on mount, then load sessions ──

  useEffect(() => {

    if (userLoading || !PLAYER_ID) {
      setAllChars([]);
      setChatItems([]);
      setSessionsLoaded(false);
      return;
    }

    let cancelled = false;
    const requestScope = sessionListEpochRef.current.advance(PLAYER_ID);
    const isCurrentRequest = () => (
      !cancelled
      && sessionListEpochRef.current.isCurrent(requestScope, playerIdRef.current)
    );
    setSessionsLoaded(false);

    (async () => {

      // Load all characters for contacts + group setup

      let chars = [];

      try {

        const list = await characterAdmin.list(false);

        const enriched = list.map((c) => ({
          character_id: c.character_id,
          name: c.name || c.display_name || c.character_id,
          display_name: c.display_name || c.name || c.character_id,
          avatar_url: c.avatar_url || null,
          is_active: c.is_active,
          core_identity: '',
          traits: [],
          gender: null,
          age: null,
          race: null,
        }));

        enriched.sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0));

        chars = enriched;

        if (isCurrentRequest()) setAllChars(enriched);

      } catch (e) { if (isCurrentRequest()) setError(e.message); }

      // Load sessions after characters are loaded (so we can resolve names/avatars from cache)

      if (isCurrentRequest()) await loadSessions(chars, requestScope);

      if (isCurrentRequest()) setSessionsLoaded(true);

    })();

    return () => {
      cancelled = true;
      sessionListEpochRef.current.invalidate();
    };

  }, [userLoading, PLAYER_ID]);



  // ── Load player sessions for chat list ──

  async function loadSessions(charsOverride, existingScope = null) {

    const playerId = existingScope?.ownerId ?? PLAYER_ID;
    if (!playerId || playerIdRef.current !== playerId) return;
    const requestScope = existingScope || beginOwnedRequest(
      sessionListEpochRef.current,
      playerId,
      playerIdRef.current,
    );
    if (!requestScope) return;
    const isCurrentRequest = () => (
      sessionListEpochRef.current.isCurrent(requestScope, playerIdRef.current)
    );

    const chars = charsOverride || allChars;
    const getActivityTime = (item) => item.last_message_at || item.ended_at || item.created_at || '';

    try {

      const sessions = await dialogue.listPlayerSessions(playerId);
      if (!isCurrentRequest()) return;
      const sortedSessions = [...sessions].sort((a, b) => new Date(getActivityTime(b) || 0) - new Date(getActivityTime(a) || 0));

      const items = [];
      const seenSingleChars = new Set();

      for (const s of sortedSessions) {
        if (!isCurrentRequest()) return;

        if (s.is_multi_character) {

          // Fetch group chat participants for proper display
          let groupParticipants = [];
          let info = null;
          try {
            info = await multiDialogue.getSessionInfo(s.session_id);
            if (!isCurrentRequest()) return;
            groupParticipants = (info.participants || []).map(p => normalizeParticipant(p, chars));
          } catch {}

          const resolvedGroupName = (s.group_name || info?.group_name || '').trim() || '未命名群聊';
          const groupItem = {
            type: 'group',
            session_id: s.session_id,
            status: s.status,
            created_at: s.created_at,
            ended_at: s.ended_at,
            group_thread_id: s.group_thread_id || info?.group_thread_id || s.session_id,
            last_message_at: s.last_message_at,
            last_message: s.last_message,
            latest_message_id: s.latest_message_id,
            message_count: s.message_count,
            unread_count: Number(s.unread_count || 0),
            participants: groupParticipants,
            group_name: resolvedGroupName,
          };
          items.push(groupItem);

        } else {

          // Deduplicate: only keep the most recent session per character
          if (seenSingleChars.has(s.character_id)) continue;
          seenSingleChars.add(s.character_id);

          // Use cached character data to avoid repeated API calls
          const cached = chars.find(c => c.character_id === s.character_id);

          items.push({

            type: 'single',

            session_id: s.session_id,

            status: s.status,

            character_id: s.character_id,

            last_message: s.last_message,

            message_count: s.message_count,

            created_at: s.created_at,

            ended_at: s.ended_at,

            last_message_at: s.last_message_at,

            name: cached?.name || s.name || s.display_name || s.character_id,

            avatar_url: cached?.avatar_url || s.avatar_url || null,

            core_identity: cached?.core_identity || '',

            is_active: cached?.is_active ?? 1,

          });

        }

      }

      const nextItems = [...items];
      nextItems.sort((a, b) => new Date(getActivityTime(b) || 0) - new Date(getActivityTime(a) || 0));
      if (isCurrentRequest()) setChatItems(nextItems);

    } catch {}

  }



  // ── Auto-scroll ──

  useLayoutEffect(() => {
    const pending = pendingHistoryScrollRef.current;
    const container = messageScrollRef.current;
    if (!pending || !container) return;

    container.scrollTop = pending.scrollTop + (container.scrollHeight - pending.scrollHeight);
    pendingHistoryScrollRef.current = null;
  }, [messages]);

  useEffect(() => {

    if (view !== 'single' && view !== 'group') return;
    if (view === 'group' && !groupHistoryReady) return;

    if (skipAutoScrollRef.current) {

      skipAutoScrollRef.current = false;

      return;

    }

    const isInitialSingleScroll = view === 'single' && pendingInitialSingleScrollRef.current;
    const isInitialGroupScroll = view === 'group'
      && pendingInitialGroupScrollRef.current;
    const isInitialScroll = isInitialSingleScroll || isInitialGroupScroll;
    const frame = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({
        behavior: isInitialScroll ? 'auto' : 'smooth',
        block: 'end',
      });
      if (isInitialSingleScroll) pendingInitialSingleScrollRef.current = false;
      if (isInitialGroupScroll) pendingInitialGroupScrollRef.current = false;
    });

    return () => cancelAnimationFrame(frame);

  }, [messages, view, groupHistoryReady]);

  useEffect(() => { if (view === 'single' || view === 'group') inputRef.current?.focus(); }, [view]);



  // ── Navigation helpers ──

  function goToList() {

    const sessionToIdle = singleSessionId || multiSessionId || activeSessionRef.current;

    nextSingleRequestGeneration();
    resetGroupSyncState();
    cancelRecording();

    stopAudio();

    setMessages([]); setCharacter(null); setSingleSessionId(null);

    setMultiSessionId(null); setParticipants([]); setGroupName(''); setAffinity(0); setTrust(0);

    setMood('neutral'); setEvents([]); setView('list'); setError(null);

    setMultiSessionStatus('active');

    setHistoryOffset(0); setHasMoreHistory(true); setLoadingHistory(false);

    scheduleIdleSessionEnd(sessionToIdle);

    loadSessions();

  }



  const enterSingleChat = useCallback(async (char) => {

    if (!PLAYER_ID) { setError('请先登录后使用对话功能'); return; }

    if (!isCharacterActive(char) && !char.session_id) {
      setError('角色已离线，不能新建聊天');
      return;
    }

    const generation = nextSingleRequestGeneration();
    activeSingleCharacterIdRef.current = char.character_id;
    resetGroupSyncState();

    cancelRecording();

    stopAudio();

    setError(null);

    setView('single-loading');

    setCharacter(char);
    setMessages([]);
    setIsRecovered(false);
    pendingInitialSingleScrollRef.current = true;

    try {

      const detail = await characterAdmin.get(char.character_id);
      if (generation !== singleRequestGenerationRef.current) return;

      const cd = detail.card_data || {};

      const nextCharacter = {

        ...char,

        identity: cd.identity || {},

        personality: cd.personality || {},

        traits: cd.personality?.traits || [],

        status_labels: cd.identity?.status_labels || [cd.personality?.core_personality_summary || ''],

        is_active: detail.is_active ?? char.is_active,

      };

      setCharacter(nextCharacter);

      if (!isCharacterActive(nextCharacter)) {
        const hist = await dialogue.getHistory(char.character_id, PLAYER_ID, 0, 20);
        if (generation !== singleRequestGenerationRef.current) return;
        if (hist?.messages?.length) {
          setMessages(sortMessagesChronologically(hist.messages.map(normalizeDialogueMessage)));
          setIsRecovered(true);
          setHistoryOffset(hist.messages.length);
          setHasMoreHistory(hist.has_more);
        } else {
          setMessages([]);
          setHistoryOffset(0);
          setHasMoreHistory(false);
        }
        setSingleSessionId(char.session_id);
        activeSessionRef.current = null;
        setAffinity(0);
        setTrust(0);
        setMood('neutral');
        setView('single');
        return;
      }

      const session = await dialogue.startSession(
        char.character_id,
        PLAYER_ID,
        PLAYER_NAME,
      );
      if (generation !== singleRequestGenerationRef.current) return;

      setSingleSessionId(session.session_id);
      activeSessionRef.current = session.session_id;
      sessionKindRef.current.set(session.session_id, 'single');
      clearIdleSessionEnd(session.session_id);
      let nextHistoryOffset = 0;
      let nextHasMoreHistory = true;

      const hist = await dialogue.getHistory(char.character_id, PLAYER_ID, 0, 20);
      if (generation !== singleRequestGenerationRef.current) return;
      if (hist?.messages?.length) {
        setMessages(sortMessagesChronologically(hist.messages.map(normalizeDialogueMessage)));
        setIsRecovered(session.recovered || hist.messages.length > 0);
        nextHistoryOffset = hist.messages.length;
        nextHasMoreHistory = hist.has_more;
      } else if (session.recovered && session.messages?.length) {
        setMessages(sortMessagesChronologically(session.messages.map(normalizeDialogueMessage)));
        setIsRecovered(true);
        nextHistoryOffset = session.messages.length;
      } else if (session.opening_line) {
        setMessages([{
          role: 'assistant',
          content: session.opening_line,
          action: session.action || '',
          world_created_at: session.world_created_at,
          message_id: session.assistant_message_id,
        }]);
      }

      setAffinity(session.current_affinity || 0);
      setTrust(session.current_trust ?? 0);

      setHistoryOffset(nextHistoryOffset); setHasMoreHistory(nextHasMoreHistory);

      setView('single');

    } catch (e) {
      if (generation === singleRequestGenerationRef.current) {
        setError(e.message);
        setView('list');
      }
    }

  }, [PLAYER_ID, PLAYER_NAME, cancelRecording, stopAudio]);

  const requestSingleChat = useCallback((char) => {
    if (!isCharacterActive(char)) {
      if (char.session_id) {
        enterSingleChat(char);
      } else {
        setError('角色已离线，不能新建聊天');
      }
      return;
    }
    const activeItem = chatItems.find(item => (
      item.type === 'single'
      && item.character_id === char.character_id
      && item.status === 'active'
    ));
    if (activeItem) {
      enterSingleChat(activeItem);
      return;
    }
    enterSingleChat(char);
  }, [chatItems, enterSingleChat]);

  // ── Direct single chat from URL param ──

  useEffect(() => {
    if (!characterIdParam) {
      directCharacterHandledRef.current = null;
      return;
    }
    if (!PLAYER_ID || !sessionsLoaded || allChars.length === 0) return;

    const directKey = `${PLAYER_ID}:${characterIdParam}`;
    if (directCharacterHandledRef.current === directKey) return;

    const nextCharacter = allChars.find(char => char.character_id === characterIdParam);
    if (!nextCharacter) return;

    directCharacterHandledRef.current = directKey;
    requestSingleChat(nextCharacter);
  }, [PLAYER_ID, allChars, characterIdParam, requestSingleChat, sessionsLoaded]);



  const enterGroupSetup = useCallback(() => {
    if (!PLAYER_ID) { setError('请先登录后使用对话功能'); return; }
    nextSingleRequestGeneration();
    resetGroupSyncState();
    cancelRecording();
    stopAudio();
    setMessages([]); setParticipants([]); setGroupName(''); setView('group-setup');
  }, [PLAYER_ID, cancelRecording, stopAudio]);

  async function markActiveGroupRead(groupThreadId, generation) {
    if (!groupThreadId || generation !== groupRequestGenerationRef.current) return;
    try {
      await multiDialogue.markThreadRead(groupThreadId);
      if (generation === groupRequestGenerationRef.current) loadSessions();
    } catch (err) {
      console.error('[markActiveGroupRead] failed:', err);
    }
  }

  async function enterGroupChat(item, initialParticipants = []) {
    if (!item?.session_id) return;

    nextSingleRequestGeneration();
    cancelRecording();
    stopAudio();
    clearIdleSessionEnd(item.session_id);
    const generation = groupRequestGenerationRef.current + 1;
    const initialThreadId = item.group_thread_id || item.session_id;
    groupRequestGenerationRef.current = generation;
    latestGroupMessageIdRef.current = 0;
    loadedGroupMessageIdsRef.current = new Set();
    groupPollInFlightRef.current = null;
    activeGroupThreadIdRef.current = initialThreadId;
    activeGroupSessionIdRef.current = item.session_id;

    setGroupHistoryReady(false);
    pendingInitialGroupScrollRef.current = true;
    setMessages([]);
    setGroupName(item.group_name || '');
    setParticipants(initialParticipants);
    setMultiSessionId(item.session_id);
    setMultiSessionStatus(item.status || 'active');
    setHistoryOffset(0);
    setHasMoreHistory(true);
    activeSessionRef.current = item.session_id;
    sessionKindRef.current.set(item.session_id, 'group');
    setView('group');

    let loadedParticipants = initialParticipants;
    try {
      const info = await multiDialogue.getSessionInfo(item.session_id);
      if (generation !== groupRequestGenerationRef.current) return;
      const resolvedThreadId = info.group_thread_id || initialThreadId;
      activeGroupThreadIdRef.current = resolvedThreadId;
      setMultiSessionStatus(info.status || item.status || 'active');
      setGroupName(info.group_name || item.group_name || '');
      loadedParticipants = info.participants?.map(p => normalizeParticipant(p)) || loadedParticipants;
      setParticipants(loadedParticipants);
    } catch {
      if (generation !== groupRequestGenerationRef.current) return;
      setParticipants(loadedParticipants);
    }

    try {
      const hist = await multiDialogue.getHistory(item.session_id, 0, HISTORY_PAGE_SIZE);
      if (generation !== groupRequestGenerationRef.current) return;

      const sessionInfo = hist?.session_info || {};
      const currentSessionId = sessionInfo.current_session_id || item.session_id;
      const groupThreadId = sessionInfo.group_thread_id || activeGroupThreadIdRef.current || initialThreadId;
      const normalizedMessages = (hist?.messages || []).map(message => (
        normalizeGroupMessage(message, [...loadedParticipants, ...allChars])
      ));

      activeGroupSessionIdRef.current = currentSessionId;
      activeGroupThreadIdRef.current = groupThreadId;
      setMultiSessionId(currentSessionId);
      activeSessionRef.current = currentSessionId;
      sessionKindRef.current.set(currentSessionId, 'group');
      setMessages(mergeGroupMessages([], normalizedMessages));
      registerLoadedGroupMessages(normalizedMessages);
      setHistoryOffset(normalizedMessages.length);
      setHasMoreHistory(Boolean(hist?.has_more));
      latestGroupMessageIdRef.current = Math.max(
        Number(hist?.latest_message_id || 0),
        maxGroupMessageId(normalizedMessages),
      );
      setGroupHistoryReady(true);
      await markActiveGroupRead(groupThreadId, generation);
    } catch (err) {
      if (generation !== groupRequestGenerationRef.current) return;
      console.error('[enterGroupChat] history failed:', err);
      setGroupHistoryReady(true);
    }
  }

  const syncGroupHistory = useCallback(() => {
    if (groupPollInFlightRef.current) return groupPollInFlightRef.current;

    const generation = groupRequestGenerationRef.current;
    const sessionId = activeGroupSessionIdRef.current;
    const groupThreadId = activeGroupThreadIdRef.current;
    if (!sessionId || !groupThreadId) return Promise.resolve(false);

    let pollPromise;
    pollPromise = (async () => {
      let cursor = latestGroupMessageIdRef.current;
      let caughtUpWithNewMessages = false;

      while (true) {
        const hist = await multiDialogue.getHistory(sessionId, 0, HISTORY_PAGE_SIZE, cursor);
        if (generation !== groupRequestGenerationRef.current) return false;

        const normalizedMessages = (hist?.messages || []).map(message => (
          normalizeGroupMessage(message, [...participants, ...allChars])
        ));
        if (normalizedMessages.length > 0) {
          const nextCursor = maxGroupMessageId(normalizedMessages, cursor);
          if (nextCursor <= cursor) break;
          const addedMessages = registerLoadedGroupMessages(normalizedMessages);
          setMessages(prev => mergeGroupMessages(prev, normalizedMessages));
          if (addedMessages > 0) setHistoryOffset(prev => prev + addedMessages);
          cursor = nextCursor;
          latestGroupMessageIdRef.current = cursor;
          caughtUpWithNewMessages = true;
        }

        if (!hist?.has_more) break;
        if (normalizedMessages.length === 0) break;
      }

      if (caughtUpWithNewMessages && generation === groupRequestGenerationRef.current) {
        await markActiveGroupRead(groupThreadId, generation);
      }
      return caughtUpWithNewMessages;
    })()
      .catch(err => {
        if (generation === groupRequestGenerationRef.current) {
          console.error('[syncGroupHistory] failed:', err);
        }
        return false;
      })
      .finally(() => {
        if (groupPollInFlightRef.current === pollPromise) {
          groupPollInFlightRef.current = null;
        }
      });

    groupPollInFlightRef.current = pollPromise;
    return pollPromise;
  }, [participants, allChars]);

  useEffect(() => {
    if (view !== 'group' || !multiSessionId || !groupHistoryReady) return undefined;

    let intervalId = null;
    const stopPolling = () => {
      if (intervalId != null) window.clearInterval(intervalId);
      intervalId = null;
    };
    const startPolling = () => {
      stopPolling();
      if (document.visibilityState !== 'visible') return;
      syncGroupHistory();
      intervalId = window.setInterval(syncGroupHistory, GROUP_POLL_INTERVAL_MS);
    };
    const handleVisibilityChange = () => startPolling();

    startPolling();
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [view, multiSessionId, groupHistoryReady, syncGroupHistory]);



  // ── Load more history on scroll up ──

  const loadMoreHistory = useCallback(async () => {

    if (!PLAYER_ID || loadingHistory || !hasMoreHistory) return;

    if (view === 'single' && character) {

      const historyRequest = {
        generation: singleRequestGenerationRef.current,
        playerId: PLAYER_ID,
        characterId: character.character_id,
      };
      const isCurrentHistoryRequest = () => canApplySingleHistory(
        historyRequest,
        {
          generation: singleRequestGenerationRef.current,
          playerId: playerIdRef.current,
          characterId: activeSingleCharacterIdRef.current,
        },
      );
      setLoadingHistory(true);

      try {

        const hist = await dialogue.getHistory(character.character_id, PLAYER_ID, historyOffset, HISTORY_PAGE_SIZE);
        if (!isCurrentHistoryRequest()) return;
        if (hist?.messages && hist.messages.length > 0) {

          skipAutoScrollRef.current = true;
          const container = messageScrollRef.current;
          if (container) {
            pendingHistoryScrollRef.current = {
              scrollTop: container.scrollTop,
              scrollHeight: container.scrollHeight,
            };
          }

          setMessages(prev => [...sortMessagesChronologically(hist.messages.map(normalizeDialogueMessage)), ...prev]);

          setHistoryOffset(prev => prev + hist.messages.length);

          setHasMoreHistory(hist.has_more);

        } else {

          setHasMoreHistory(false);

        }

      } catch (err) {
        if (isCurrentHistoryRequest()) {
          console.error('[loadMoreHistory] single failed:', err);
        }
      } finally {
        if (isCurrentHistoryRequest()) setLoadingHistory(false);
      }

    } else if (view === 'group' && multiSessionId) {

      const generation = groupRequestGenerationRef.current;
      setLoadingHistory(true);

      try {

        const sessionId = activeGroupSessionIdRef.current || multiSessionId;
        const hist = await multiDialogue.getHistory(sessionId, historyOffset, HISTORY_PAGE_SIZE);
        if (generation !== groupRequestGenerationRef.current) return;

        if (hist?.messages && hist.messages.length > 0) {

          skipAutoScrollRef.current = true;
          const container = messageScrollRef.current;
          if (container) {
            pendingHistoryScrollRef.current = {
              scrollTop: container.scrollTop,
              scrollHeight: container.scrollHeight,
            };
          }

          const normalizedMessages = hist.messages.map(message => (
            normalizeGroupMessage(message, [...participants, ...allChars])
          ));
          const addedMessages = registerLoadedGroupMessages(normalizedMessages);
          setMessages(prev => mergeGroupMessages(prev, normalizedMessages, { prepend: true }));

          if (addedMessages > 0) setHistoryOffset(prev => prev + addedMessages);
          setHasMoreHistory(hist.has_more);

        } else {

          setHasMoreHistory(false);

        }

      } catch (err) {
        if (generation === groupRequestGenerationRef.current) {
          console.error('[loadMoreHistory] group failed:', err);
        }
      } finally {
        if (generation === groupRequestGenerationRef.current) setLoadingHistory(false);
      }

    }

  }, [historyOffset, PLAYER_ID, view, character, multiSessionId, loadingHistory, hasMoreHistory, participants, allChars]);

  const loadMoreRef = useRef(loadMoreHistory);
  useEffect(() => { loadMoreRef.current = loadMoreHistory; }, [loadMoreHistory]);



  // ── Group: toggle participant ──

  const toggleParticipant = (char) => {

    if (!isCharacterActive(char)) return;

    setParticipants(prev =>

      prev.find(p => p.character_id === char.character_id)

        ? prev.filter(p => p.character_id !== char.character_id)

        : [...prev, char]

    );

  };

  const startGroupChat = async () => {

    if (!PLAYER_ID) { setError('请先登录后使用对话功能'); return; }

    const cleanGroupName = groupName.trim();

    if (!cleanGroupName) { setError('请输入群聊名称'); return; }
    if (groupNameExists) { setError('群聊名称已存在，请换一个名称'); return; }
    if (participants.length < 2) { setError('至少选择2个角色'); return; }
    const selectedParticipants = participants.map(p => normalizeParticipant(p));
    if (selectedParticipants.some(p => !isCharacterActive(p))) { setError('离线角色不能用于新建群聊'); return; }

    nextSingleRequestGeneration();
    const requestPlayerId = PLAYER_ID;
    const generation = groupRequestGenerationRef.current + 1;
    groupRequestGenerationRef.current = generation;
    setError(null); setView('single-loading');

    try {

      const res = await multiDialogue.startSession(
        requestPlayerId,
        PLAYER_NAME,
        selectedParticipants.map(p => p.character_id),
        cleanGroupName,
      );

      if (
        generation !== groupRequestGenerationRef.current
        || playerIdRef.current !== requestPlayerId
      ) return;

      const groupThreadId = res.group_thread_id || res.session_id;
      loadedGroupMessageIdsRef.current = new Set();
      groupPollInFlightRef.current = null;
      activeGroupThreadIdRef.current = groupThreadId;
      activeGroupSessionIdRef.current = res.session_id;

      setMultiSessionId(res.session_id);
      setMultiSessionStatus('active');
      activeSessionRef.current = res.session_id;
      sessionKindRef.current.set(res.session_id, 'group');
      clearIdleSessionEnd(res.session_id);

      const openingMessages = res.opening?.dialogue
        ? [normalizeGroupMessage(res.opening, [...selectedParticipants, ...allChars])]
        : [];
      setMessages(mergeGroupMessages([], openingMessages));
      registerLoadedGroupMessages(openingMessages);
      latestGroupMessageIdRef.current = maxGroupMessageId(openingMessages);

      setHistoryOffset(openingMessages.length);
      setHasMoreHistory(false);
      setGroupHistoryReady(true);
      pendingInitialGroupScrollRef.current = true;

      setView('group');

    } catch (e) {
      if (
        generation !== groupRequestGenerationRef.current
        || playerIdRef.current !== requestPlayerId
      ) return;
      setError(e.message);
      setView('group-setup');
    }

  };



  // ── Send message ──

  const sendMessage = useCallback(async (textOverride = null) => {

    const text = String(textOverride ?? input).trim();

    if (!PLAYER_ID) { setError('请先登录后使用对话功能'); return; }

    if (!text || sending || sendingMulti) return;

    if (view === 'single' && (!singleSessionId || !isCharacterActive(character))) {
      setError('角色已离线，只能查看历史');
      return;
    }

    setError(null);

    const requestId = createRequestId('dialogue-turn');
    const requestMode = view;
    const requestToken = { requestId, mode: requestMode };
    const streamAbortController = new AbortController();
    const singleGeneration = singleRequestGenerationRef.current;
    const singleSessionAtSend = singleSessionId;
    activeSendRequestRef.current = requestToken;
    activeStreamAbortControllerRef.current = streamAbortController;

    setInput(''); setSending(true); setSendingMulti(true);

    const optimisticWorldCreatedAt = getWorldNow()?.toISOString();
    const groupGeneration = groupRequestGenerationRef.current;
    const pendingGroupMessage = view === 'group'
      ? normalizeGroupMessage({
          role: 'user',
          content: text,
          world_created_at: optimisticWorldCreatedAt,
          client_id: createClientMessageId(),
          _pending: true,
        })
      : null;
    const pendingSingleMessage = view === 'single'
      ? createPendingUserMessage(
          text,
          optimisticWorldCreatedAt,
          createClientMessageId(),
        )
      : null;
    const dialogueStreamIds = new Set();
    let receivedDialogueDelta = false;
    const isCurrentSingleRequest = () => (
      requestMode === 'single'
      && singleGeneration === singleRequestGenerationRef.current
      && activeSessionRef.current === singleSessionAtSend
    );
    const isCurrentGroupRequest = () => (
      requestMode === 'group'
      && groupGeneration === groupRequestGenerationRef.current
    );
    const handleDialogueStreamEvent = (event, isCurrentRequest) => {
      if (!isCurrentRequest()) return;
      if (event?.type === 'character_started' && event.data?.stream_id) {
        dialogueStreamIds.add(event.data.stream_id);
      }
      if (event?.type === 'dialogue_delta') {
        receivedDialogueDelta = true;
      }
      setMessages(prev => applyDialogueStreamEvent(prev, event));
    };
    const clearDialogueStreamPlaceholders = () => {
      setMessages(prev => removeDialogueStreamPlaceholders(prev, dialogueStreamIds));
    };
    setMessages(prev => view === 'group'
      ? mergeGroupMessages(prev, [pendingGroupMessage])
      : [...prev, pendingSingleMessage]);

    try {

      if (view === 'single') {

        let res;
        try {
          res = await dialogue.streamMessage(
            singleSessionAtSend,
            text,
            requestId,
            event => handleDialogueStreamEvent(event, isCurrentSingleRequest),
            { signal: streamAbortController.signal },
          );
        } catch (streamError) {
          if (!isCurrentSingleRequest()) throw streamError;
          if (!shouldFallbackFromDialogueStream(receivedDialogueDelta)) throw streamError;
          res = await retryDialogueTurnConflict(
            () => dialogue.sendMessage(singleSessionAtSend, text, requestId),
            { shouldRetry: isCurrentSingleRequest },
          );
        }
        if (!isCurrentSingleRequest()) return;

        const affinityDelta = currentDelta(res.current_affinity, affinity, res.affinity_delta);
        const trustDelta = currentDelta(res.current_trust, trust, res.trust_delta);
        setMessages(prev => {
          const settled = settlePendingMessage(prev, pendingSingleMessage.client_id);
          const finalAssistantMessage = {
            role: 'assistant',
            content: res.dialogue,
            action: res.action || '',
            affinity_delta: affinityDelta,
            trust_delta: trustDelta,
            showRelationshipDelta: true,
            world_created_at: res.world_created_at,
            message_id: res.assistant_message_id,
          };
          const reconciled = reconcileTurn(settled, res);
          return reconciled.map(message => (
            message.message_id != null
            && res.assistant_message_id != null
            && String(message.message_id) === String(res.assistant_message_id)
              ? { ...message, ...finalAssistantMessage }
              : message
          ));
        });

        if (user?.tts_auto_play && res.assistant_message_id != null) {
          enqueueAutoplay(res.assistant_message_id, singleSessionAtSend, 'single');
        }

        setHistoryOffset(prev => prev + 2);

        setAffinity(res.current_affinity ?? affinity);
        setTrust(res.current_trust ?? trust);
        setMood(res.current_mood || 'neutral');

        if (res.triggered_events?.length || res.event_notification) {

          setEvents(prev => [

            ...prev,

            ...(res.triggered_events || []).map(e => ({ ...e, id: Date.now() + Math.random() })),

            ...(res.event_notification ? [{ id: Date.now() + Math.random() + 1, description: res.event_notification }] : []),

          ]);

        }

      } else if (view === 'group') {

        let res;
        let targetSessionId = multiSessionId;

        const continueGroupSession = async () => {
          const continued = await multiDialogue.continueSession(targetSessionId);
          if (groupGeneration !== groupRequestGenerationRef.current) return null;
          targetSessionId = continued.session_id;
          setMultiSessionId(continued.session_id);
          setMultiSessionStatus('active');
          setGroupName(continued.group_name || groupName);
          if (continued.participants?.length) {
            setParticipants(continued.participants.map(p => normalizeParticipant(p)));
          }
          activeSessionRef.current = continued.session_id;
          activeGroupSessionIdRef.current = continued.session_id;
          activeGroupThreadIdRef.current = continued.group_thread_id || activeGroupThreadIdRef.current;
          sessionKindRef.current.set(continued.session_id, 'group');
          clearIdleSessionEnd(continued.session_id);
          return continued.session_id;
        };

        const sendGroupTurn = async (sessionId) => {
          try {
            const response = await multiDialogue.streamDiscussMessage(
              sessionId,
              text,
              null,
              requestId,
              event => handleDialogueStreamEvent(event, isCurrentGroupRequest),
              { signal: streamAbortController.signal },
            );
            return response;
          } catch (streamError) {
            if (!isCurrentGroupRequest()) throw streamError;
            if (!shouldFallbackFromDialogueStream(receivedDialogueDelta)) throw streamError;
            return retryDialogueTurnConflict(
              () => multiDialogue.discussMessage(sessionId, text, null, requestId),
              { shouldRetry: isCurrentGroupRequest },
            );
          }
        };

        if (multiSessionStatus !== 'active') {
          targetSessionId = await continueGroupSession();
          if (!targetSessionId) return;
        }

        try {
          res = await sendGroupTurn(targetSessionId);
        } catch (err) {
          if (!String(err.message || '').includes('会话已结束')) throw err;
          targetSessionId = await continueGroupSession();
          if (!targetSessionId) return;
          res = await sendGroupTurn(targetSessionId);
        }

        if (!isCurrentGroupRequest()) return;
        const groupResponses = Array.isArray(res.responses) ? res.responses : [res];
        const normalizedResponses = groupResponses.map(response => (
          normalizeGroupMessage(response, [...participants, ...allChars], { showRelationshipDelta: true })
        ));
        const addedResponses = registerLoadedGroupMessages(normalizedResponses);
        setMessages(prev => {
          const reconciled = reconcileTurn(prev, res);
          return mergeGroupMessages(reconciled, normalizedResponses);
        });
        if (addedResponses > 0) setHistoryOffset(prev => prev + addedResponses);
        syncGroupHistory();

        const messageIds = groupResponses
          .map(response => response.message_id)
          .filter(messageId => messageId != null);
        if (user?.tts_auto_play && messageIds.length) {
          enqueueAutoplay(messageIds, targetSessionId, 'group');
        }

      }

    } catch (e) {
      const currentGroupRequest = isCurrentGroupRequest();
      if (currentGroupRequest && pendingGroupMessage?.client_id) {
        setMessages(prev => mergeGroupMessages(
          removeDialogueStreamPlaceholders(prev, dialogueStreamIds)
            .filter(message => message.client_id !== pendingGroupMessage.client_id),
          [],
          { replacePending: false },
        ));
        setInput(current => restoreFailedDraft(current, text));
      }
      const currentSingleRequest = isCurrentSingleRequest();
      if (currentSingleRequest && pendingSingleMessage?.client_id) {
        setMessages(prev => removePendingMessage(
          removeDialogueStreamPlaceholders(prev, dialogueStreamIds),
          pendingSingleMessage.client_id,
        ));
        setInput(current => restoreFailedDraft(current, text));
      }
      if (currentSingleRequest || currentGroupRequest) {
        setError(e.message);
      }
    }

    finally {
      if (activeSendRequestRef.current === requestToken) {
        if (activeStreamAbortControllerRef.current === streamAbortController) {
          activeStreamAbortControllerRef.current = null;
        }
        activeSendRequestRef.current = null;
        setSending(false);
        setSendingMulti(false);
      }
    }

  }, [input, sending, sendingMulti, view, singleSessionId, multiSessionId, multiSessionStatus, groupName, affinity, trust, character, participants, allChars, PLAYER_ID, PLAYER_NAME, getWorldNow, syncGroupHistory, user?.tts_auto_play, enqueueAutoplay]);

  sendMessageRef.current = sendMessage;



  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };



  // ── Archive workbench rendering ──

  const getCharById = (id) => (
    participants.find(p => p.character_id === id)
    || allChars.find(c => c.character_id === id)
  );

  const archivePrimaryAction = useMemo(() => {
    if (view !== 'list' || userLoading || !PLAYER_ID) return null;
    return (
      <Button type="button" size="lg" onClick={enterGroupSetup}>
        <Plus aria-hidden="true" />
        新建群聊
      </Button>
    );
  }, [PLAYER_ID, enterGroupSetup, userLoading, view]);

  useEffect(() => {
    setPrimaryAction(archivePrimaryAction);
    return () => setPrimaryAction(null);
  }, [archivePrimaryAction, setPrimaryAction]);

  if (userLoading) {
    return (
      <div className="flex h-[calc(100dvh-4rem)] items-center justify-center bg-background text-muted-foreground" role="status">
        <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
        <span className="sr-only">正在确认登录状态</span>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex h-[calc(100dvh-4rem)] items-center justify-center bg-background px-4 font-archive-sans">
        <section className="w-full max-w-sm rounded-lg border border-border bg-card p-6 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
            <User aria-hidden="true" />
          </span>
          <h1 className="mt-4 font-archive-serif text-lg font-semibold text-foreground">请先登录后使用对话功能</h1>
          <Button type="button" className="mt-5 w-full" onClick={() => navigate('/')}>
            <ArrowLeft aria-hidden="true" />
            返回登录
          </Button>
        </section>
      </div>
    );
  }

  if (view === 'single-loading') {
    return (
      <div className="flex h-[calc(100dvh-4rem)] items-center justify-center bg-background font-archive-sans">
        <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-5 py-4 text-muted-foreground" role="status">
          {renderAvatar(character, 'h-10 w-10')}
          <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
          <span className="text-sm">正在连接 {character?.name || '角色'}</span>
        </div>
      </div>
    );
  }

  if (view === 'list') return renderListView();
  if (view === 'group-setup') return renderGroupSetup();
  if (view === 'single') return renderChatWorkbench('single');
  if (view === 'group') return renderChatWorkbench('group');
  return null;

  function renderAvatar(entity, sizeClass = 'h-10 w-10', extraClass = '') {
    const label = entity?.name || entity?.display_name || entity?.username || '';
    return (
      <span className={`${sizeClass} ${extraClass} flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted font-archive-serif text-sm font-semibold text-muted-foreground`}>
        {entity?.avatar_url
          ? <img src={entity.avatar_url} alt="" className="h-full w-full object-cover" />
          : label.charAt(0).toUpperCase() || <User className="h-4 w-4" aria-hidden="true" />}
      </span>
    );
  }

  function renderErrorNotice() {
    if (!error) return null;
    return (
      <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 text-xs text-destructive">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 break-words">{error}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-my-2 -mr-2 shrink-0 text-destructive"
          onClick={() => setError(null)}
          aria-label="关闭错误提示"
        >
          <X aria-hidden="true" />
        </Button>
      </div>
    );
  }

  function renderSessionDirectory({ embedded = false, className = '' } = {}) {
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
            onClick={enterGroupSetup}
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
              onChange={event => setSearchQuery(event.target.value)}
              placeholder={activeTab === 'chat' ? '搜索对话' : '搜索联系人'}
              className="pl-9"
            />
          </div>
          <Tabs
            value={activeTab}
            onValueChange={value => {
              setActiveTab(value);
              setSearchQuery('');
            }}
          >
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="chat">对话</TabsTrigger>
              <TabsTrigger value="contacts">联系人</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {renderErrorNotice()}
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
                      ? requestSingleChat(char)
                      : setError('角色已离线，不能新建聊天')}
                    className="flex min-h-14 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}
                  >
                    {renderAvatar(char, 'h-10 w-10', active ? '' : 'grayscale opacity-55')}
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

  function renderDirectoryItem(item, index) {
    const timeLabel = formatChatTime(item.last_message_at);
    if (item.type === 'group') {
      const groupParts = (item.participants || []).map(participant => normalizeParticipant(participant));
      const unreadCount = Math.max(0, Number(item.unread_count || 0));
      return (
        <button
          type="button"
          key={`group-${item.group_thread_id || item.session_id || index}`}
          onClick={() => enterGroupChat(item, groupParts)}
          className="flex min-h-16 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex shrink-0 -space-x-2">
            {groupParts.slice(0, 3).map((participant, participantIndex) => (
              <Fragment key={participant.character_id || participantIndex}>
                {renderAvatar(participant, 'h-9 w-9', 'border-card')}
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
        onClick={() => requestSingleChat(item)}
        className="flex min-h-16 w-full items-center gap-3 rounded-md border border-transparent px-2 py-2 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {renderAvatar(item, 'h-10 w-10', active ? '' : 'grayscale opacity-55')}
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

  function renderListView() {
    const activeContacts = allChars.filter(char => isCharacterActive(char)).length;
    const groupCount = chatItems.filter(item => item.type === 'group').length;
    return (
      <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
        <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
          {renderSessionDirectory({ className: 'lg:col-span-2' })}
          <aside className="hidden min-h-0 flex-col bg-background lg:flex">
            <div className="min-h-16 border-b border-border px-4 py-3">
              <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Archive Status</p>
              <h2 className="font-archive-serif text-base font-semibold text-foreground">叙事索引</h2>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <dl className="divide-y divide-border border-y border-border">
                <SummaryRow label="全部会话" value={chatItems.length} />
                <SummaryRow label="群聊会话" value={groupCount} />
                <SummaryRow label="在线角色" value={activeContacts} />
                <SummaryRow label="角色总数" value={allChars.length} />
              </dl>
              <div className="mt-5">
                <h3 className="font-archive-serif text-sm font-semibold text-foreground">在线联系人</h3>
                <div className="mt-2 space-y-1">
                  {allChars.filter(char => isCharacterActive(char)).slice(0, 8).map(char => (
                    <button
                      type="button"
                      key={char.character_id}
                      onClick={() => requestSingleChat(char)}
                      className="flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {renderAvatar(char, 'h-8 w-8')}
                      <span className="min-w-0 flex-1 truncate font-archive-serif text-sm text-foreground">{char.name}</span>
                      <span className="h-2 w-2 rounded-sm bg-primary" aria-hidden="true" />
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    );
  }

  function SummaryRow({ label, value }) {
    return (
      <div className="flex items-center justify-between gap-3 py-3">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="font-archive-mono text-sm text-foreground tabular-nums">{value}</dd>
      </div>
    );
  }

  function renderGroupSetup() {
    const activeCharacters = allChars.filter(char => isCharacterActive(char));
    return (
      <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
        <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
          <section className="flex min-h-0 min-w-0 flex-col border-r border-border bg-background lg:col-span-2">
            <div className="flex min-h-16 items-center gap-2 border-b border-border px-3 sm:px-4">
              <Button type="button" variant="ghost" size="icon" onClick={goToList} aria-label="返回会话目录">
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
                {renderErrorNotice()}
                <section className="rounded-lg border border-border bg-card p-4">
                  <label htmlFor="group-name" className="mb-2 block font-archive-serif text-sm font-semibold text-foreground">
                    群聊名称
                  </label>
                  <Input
                    id="group-name"
                    type="text"
                    value={groupName}
                    onChange={event => {
                      setGroupName(event.target.value);
                      if (error) setError(null);
                    }}
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
                          onClick={() => toggleParticipant(char)}
                          aria-pressed={selected}
                          className={`flex min-h-14 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                            selected
                              ? 'border-primary/60 bg-primary/10'
                              : 'border-border bg-background hover:bg-accent'
                          }`}
                        >
                          {renderAvatar(char, 'h-9 w-9')}
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
                          onClick={() => toggleParticipant(participant)}
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
                  onClick={startGroupChat}
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
                      {renderAvatar(participant, 'h-9 w-9')}
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

  function renderChatWorkbench(mode) {
    const isSingle = mode === 'single';
    return (
      <div data-archive-chat-workbench className="h-[calc(100dvh-4rem)] min-w-0 overflow-hidden bg-background font-archive-sans text-foreground">
        <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_minmax(240px,320px)]">
          {renderSessionDirectory({ embedded: true })}
          {renderChatArea(mode)}
          <aside className="hidden min-h-0 flex-col border-l border-border bg-card lg:flex">
            {renderProfilePanel(mode)}
          </aside>
        </div>
        {showClockSettings && <UserSettingsModal onClose={() => setShowClockSettings(false)} />}
      </div>
    );
  }

  function renderChatArea(mode) {
    const isSingle = mode === 'single';
    const singleReadOnly = isSingle && !isCharacterActive(character);
    const resolvedParticipants = participants.map(participant => normalizeParticipant(participant));
    const activeParticipantCount = resolvedParticipants.filter(participant => isCharacterActive(participant)).length;
    const title = isSingle ? character?.name : groupName || '群聊';
    const status = isSingle
      ? (singleReadOnly ? '离线 · 只读' : sending ? '正在回应' : MOOD_LABELS[mood])
      : (sendingMulti ? '角色思考中' : `${activeParticipantCount}/${resolvedParticipants.length} 在线`);

    return (
      <section className="flex min-h-0 min-w-0 flex-col bg-background">
        <div className="flex min-h-16 items-center gap-2 border-b border-border px-2 sm:px-3">
          <Button type="button" variant="ghost" size="icon" onClick={goToList} className="lg:hidden" aria-label="返回会话目录">
            <ArrowLeft aria-hidden="true" />
          </Button>
          <button
            type="button"
            onClick={() => setShowDetail(current => !current)}
            className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:pointer-events-none"
          >
            {isSingle
              ? renderAvatar(character, 'h-9 w-9')
              : (
                <span className="flex shrink-0 -space-x-2">
                  {resolvedParticipants.slice(0, 2).map(participant => (
                    <Fragment key={participant.character_id}>
                      {renderAvatar(participant, 'h-9 w-9', 'border-background')}
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
              onClick={() => setShowClockSettings(true)}
            />
          </div>
          {isSingle && events.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="relative text-destructive"
              onClick={() => setEvents([])}
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
            {renderProfilePanel(mode, true)}
          </div>
        )}

        <div
          ref={messageScrollRef}
          style={{ overflowAnchor: 'none' }}
          className="relative min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5"
          onScroll={event => {
            if (event.target.scrollTop < 60 && !loadingHistory && hasMoreHistory) loadMoreHistory();
          }}
        >
          <div className="mx-auto max-w-3xl space-y-4">
            {renderErrorNotice()}
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
                              messageId={message.message_id}
                              pending={message._pending}
                            />
                          )}
                        </div>
                      ) : (
                        <div className="flex min-w-0 gap-3">
                          {renderAvatar(charInfo || character, 'h-9 w-9', 'mt-0.5')}
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
                                messageId={message.message_id}
                              />
                            )}
                            {isLastParagraph && message.message_id != null && (
                              <MessageAudioControl
                                messageId={message.message_id}
                                messageSessionId={message.session_id}
                                getAudioState={getAudioState}
                                onToggle={toggleAudio}
                                onRetry={retryAudio}
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

        <div className="shrink-0 border-t border-border bg-card px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-4">
          <SpeechErrorNotice error={speechError} onDismiss={clearSpeechError} onRetry={startRecording} />
          <div className="flex items-end gap-2">
            <SpeechRecorderButton
              status={speechStatus}
              supported={isRecordingSupported}
              disabled={singleReadOnly || sending || sendingMulti}
              onStart={startRecording}
              onStop={stopRecording}
            />
            <Textarea
              ref={inputRef}
              value={input}
              onChange={event => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder={singleReadOnly ? '角色已离线，只能查看历史' : '输入消息'}
              disabled={singleReadOnly || sending || sendingMulti}
              className="max-h-28 min-h-11 flex-1 resize-none"
            />
            <Button
              type="button"
              size="icon"
              onClick={sendMessage}
              disabled={singleReadOnly || !input.trim() || sending || sendingMulti}
              aria-label="发送消息"
            >
              <Send aria-hidden="true" />
            </Button>
          </div>
        </div>
      </section>
    );
  }

  function renderProfilePanel(mode, mobile = false) {
    if (mode === 'group') return renderGroupProfile(mobile);

    const affinityPercent = Math.min(100, Math.max(0, Math.round((affinity + 100) / 2)));
    const trustValue = Math.min(100, Math.max(0, Math.round(Number(trust) || 0)));
    const identitySummary = character?.identity?.core_identity_summary || character?.core_identity;
    return (
      <div className={`${mobile ? '' : 'min-h-0 flex-1 overflow-y-auto'} p-4`}>
        <div className="flex items-center gap-3 border-b border-border pb-4">
          {renderAvatar(character, 'h-14 w-14')}
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
          <SummaryRow label="当前心情" value={`${MOOD_EMOJI[mood] || MOOD_EMOJI.neutral} ${MOOD_LABELS[mood] || MOOD_LABELS.neutral}`} />
          <SummaryRow label="会话状态" value={isCharacterActive(character) ? '进行中' : '离线只读'} />
          <SummaryRow label="历史恢复" value={isRecovered ? '已恢复' : '新会话'} />
          <SummaryRow label="消息数" value={messages.length} />
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

  function renderGroupProfile(mobile = false) {
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
          <SummaryRow label="会话状态" value={multiSessionStatus === 'active' ? '进行中' : '已结束'} />
          <SummaryRow label="同步状态" value={groupHistoryReady ? '已同步' : '同步中'} />
          <SummaryRow label="在线成员" value={`${activeParticipantCount}/${resolvedParticipants.length}`} />
          <SummaryRow label="消息数" value={messages.length} />
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
                <div key={participant.character_id} className="flex min-h-12 items-center gap-3 border-b border-border py-2">
                  <span className="w-5 shrink-0 font-archive-mono text-[10px] text-muted-foreground tabular-nums">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  {renderAvatar(participant, 'h-9 w-9', active ? '' : 'grayscale opacity-55')}
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
}
