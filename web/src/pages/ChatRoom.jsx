import { Fragment, useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';

import { useSearchParams, useNavigate } from 'react-router-dom';

import { useUser } from '../context/UserContext';

import { dialogue, multiDialogue, characterAdmin } from '../api/memoria';

import SideRays from '../components/SideRays';
import { EventInboxBanner, WorldClockDisplay } from '../components/WorldClock';
import UserSettingsModal from '../components/UserSettingsModal';

import { splitAssistantReply } from '../utils/chatMessages';
import useBrowserSpeech from '../hooks/useBrowserSpeech';

import {

  Send, ArrowLeft, Heart, AlertTriangle, Loader2, User, X, Plus, Users,

  Search, Cpu, Activity, MessageSquare, Mic, Square, Volume2,
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



const MOOD_BORDER = { happy: 'border-emerald-400/60', neutral: 'border-slate-500/40', sad: 'border-blue-400/60', angry: 'border-red-400/60', surprised: 'border-yellow-400/60', fearful: 'border-purple-400/60', disgusted: 'border-orange-400/60' };

const MOOD_GLOW = { happy: 'shadow-[0_0_12px_rgba(52,211,153,0.3)]', neutral: '', sad: 'shadow-[0_0_12px_rgba(96,165,250,0.3)]', angry: 'shadow-[0_0_12px_rgba(248,113,113,0.3)]' };
const MOOD_BUBBLE = { happy: 'bg-emerald-950 border-emerald-400/20 text-zinc-200', neutral: 'bg-white/[0.03] border-white/[0.06] text-zinc-300', sad: 'bg-blue-950 border-blue-400/20 text-zinc-200', angry: 'bg-red-950 border-red-400/20 text-zinc-200', surprised: 'bg-yellow-950 border-yellow-400/20 text-zinc-200', fearful: 'bg-purple-950 border-purple-400/20 text-zinc-200', disgusted: 'bg-orange-950 border-orange-400/20 text-zinc-200' };



const IDLE_SESSION_END_MS = 5 * 60 * 1000;
const HISTORY_PAGE_SIZE = 20;
const GROUP_POLL_INTERVAL_MS = 3 * 1000;

const CHAT_RAYS_PROPS = {
  speed: 2.1,
  rayColor1: '#F8D36B',
  rayColor2: '#9DD8FF',
  intensity: 2.6,
  spread: 2.15,
  origin: 'top-right',
  tilt: -4,
  saturation: 1.35,
  blend: 0.68,
  falloff: 1.45,
  opacity: 0.82,
};

function ChatBackdrop({ origin = 'top-right', tilt = -4 }) {
  return (
    <SideRays
      {...CHAT_RAYS_PROPS}
      origin={origin}
      tilt={tilt}
      className="side-rays-chat"
    />
  );
}



// ═══════════════════════════════════════════════

// Scanning line animation (for AI thinking)

// ═══════════════════════════════════════════════

function ScanLine() {

  return (

    <div className="absolute inset-0 overflow-hidden pointer-events-none rounded-lg" aria-hidden="true">

      <div className="absolute inset-x-0 h-[2px] bg-gradient-to-r from-transparent via-cyber-green/40 to-transparent animate-scan" />

    </div>

  );

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
    <div className="flex items-center gap-3 py-1" role="separator" aria-label={`世界日期 ${label}`}>
      <span className="h-px flex-1 bg-amber-200/10" />
      <span className="shrink-0 text-[10px] text-amber-100/55">{label} · 世界时间</span>
      <span className="h-px flex-1 bg-amber-200/10" />
    </div>
  );
}

function MessageWorldTime({ value, align = 'left' }) {
  const label = formatWorldTime(value);
  if (!label) return null;
  return (
    <div className={`mt-1 flex items-center gap-1 px-1 text-[10px] text-zinc-600 ${align === 'right' ? 'justify-end' : 'justify-start'}`}>
      <span className="h-1 w-1 rounded-full bg-amber-300/45" />
      <time dateTime={value}>{label}</time>
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
    <span className="mx-0.5 inline-block max-w-full rounded-[4px] border border-emerald-200/45 bg-emerald-300/14 px-1.5 py-0 align-baseline font-character text-[0.94em] font-medium [line-height:inherit] text-emerald-50 shadow-[0_0_10px_rgba(110,231,183,0.12)] whitespace-normal break-words italic">
      {text}
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
    <span className={value > 0 ? 'text-emerald-400/70' : 'text-red-400/70'}>
      {label} {value > 0 ? '+' : ''}{formatDelta(value)}
    </span>
  );

  return (
    <div className="mt-0.5 ml-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] leading-normal">
      {affinity !== 0 && renderDelta('好感', affinity)}
      {trust !== 0 && renderDelta('信任', trust)}
    </div>
  );
}

function MessageAudioControl({ messageId, getAudioState, onToggle, onRetry }) {
  const audioState = getAudioState(messageId);
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
    <button
      type="button"
      onClick={() => isError ? onRetry(messageId) : onToggle(messageId)}
      disabled={isLoading}
      className={`mt-1 flex h-11 w-11 items-center justify-center rounded-lg border transition-colors disabled:cursor-wait ${
        isError
          ? 'border-red-400/20 text-red-300/70 hover:border-red-400/40 hover:bg-red-400/5'
          : 'border-cyber-green/10 text-cyber-green/35 hover:border-cyber-green/30 hover:bg-cyber-green/5 hover:text-cyber-green/70'
      }`}
      aria-label={label}
      title={audioState.error || label}
    >
      {isLoading ? <Loader2 size={15} className="animate-spin" />
        : isPlaying ? <Pause size={15} />
          : isError ? <RotateCw size={15} />
            : <Volume2 size={15} />}
    </button>
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
    <button
      type="button"
      onClick={isRecording ? onStop : onStart}
      disabled={disabled || isTranscribing || (!supported && !isRecording)}
      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition-all disabled:cursor-not-allowed disabled:opacity-25 ${
        isRecording
          ? 'border-red-400/35 bg-red-400/10 text-red-300 hover:bg-red-400/15'
          : 'border-cyan-200/15 bg-cyan-200/[0.035] text-cyan-100/55 hover:border-cyan-200/35 hover:bg-cyan-200/[0.07] hover:text-cyan-100'
      }`}
      aria-label={label}
      title={label}
    >
      {isTranscribing ? <Loader2 size={16} className="animate-spin" />
        : isRecording ? <Square size={15} fill="currentColor" />
          : <Mic size={17} />}
    </button>
  );
}

function SpeechErrorNotice({ error, onDismiss, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-2 flex items-center gap-2 rounded-lg border border-red-400/15 bg-red-400/[0.055] px-3 py-2 text-[11px] leading-5 text-red-200/75">
      <AlertTriangle size={13} className="shrink-0" />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      <button type="button" onClick={onRetry} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-red-200/55 hover:bg-red-400/10 hover:text-red-100" aria-label="重试语音输入" title="重试语音输入">
        <RotateCw size={14} />
      </button>
      <button type="button" onClick={onDismiss} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-red-200/35 hover:bg-red-400/10 hover:text-red-100" aria-label="关闭语音错误">
        <X size={15} />
      </button>
    </div>
  );
}

// ═══════════════════════════════════════════════

// ChatRoom — Main Container

// ═══════════════════════════════════════════════

export default function ChatRoom() {

  const [searchParams] = useSearchParams();

  const navigate = useNavigate();

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

  const pendingHistoryScrollRef = useRef(null);

  const latestGroupMessageIdRef = useRef(0);

  const loadedGroupMessageIdsRef = useRef(new Set());

  const groupPollInFlightRef = useRef(null);

  const activeGroupThreadIdRef = useRef(null);

  const activeGroupSessionIdRef = useRef(null);

  const groupRequestGenerationRef = useRef(0);

  const singleRequestGenerationRef = useRef(0);

  const activeSendRequestRef = useRef(null);

  const sendMessageRef = useRef(null);

  const directCharacterHandledRef = useRef(null);

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
    setGroupHistoryReady(false);
  }

  function invalidatePendingSend() {
    activeSendRequestRef.current = null;
    setSending(false);
    setSendingMulti(false);
  }

  function nextSingleRequestGeneration() {
    singleRequestGenerationRef.current += 1;
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

        if (!cancelled) setAllChars(enriched);

      } catch (e) { if (!cancelled) setError(e.message); }

      // Load sessions after characters are loaded (so we can resolve names/avatars from cache)

      if (!cancelled) await loadSessions(chars);

      if (!cancelled) setSessionsLoaded(true);

    })();

    return () => { cancelled = true; };

  }, [userLoading, PLAYER_ID]);



  // ── Load player sessions for chat list ──

  async function loadSessions(charsOverride) {

    if (!PLAYER_ID) {
      setChatItems([]);
      return;
    }

    const chars = charsOverride || allChars;
    const getActivityTime = (item) => item.last_message_at || item.ended_at || item.created_at || '';

    try {

      const sessions = await dialogue.listPlayerSessions(PLAYER_ID);
      const sortedSessions = [...sessions].sort((a, b) => new Date(getActivityTime(b) || 0) - new Date(getActivityTime(a) || 0));

      const items = [];
      const seenSingleChars = new Set();

      for (const s of sortedSessions) {

        if (s.is_multi_character) {

          // Fetch group chat participants for proper display
          let groupParticipants = [];
          let info = null;
          try {
            info = await multiDialogue.getSessionInfo(s.session_id);
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
      setChatItems(nextItems);

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

    if (skipAutoScrollRef.current) {

      skipAutoScrollRef.current = false;

      return;

    }

    const isInitialSingleScroll = view === 'single' && pendingInitialSingleScrollRef.current;
    const frame = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({
        behavior: isInitialSingleScroll ? 'auto' : 'smooth',
        block: 'end',
      });
      if (isInitialSingleScroll) pendingInitialSingleScrollRef.current = false;
    });

    return () => cancelAnimationFrame(frame);

  }, [messages, view]);

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

      setLoadingHistory(true);

      try {

        const hist = await dialogue.getHistory(character.character_id, PLAYER_ID, historyOffset, HISTORY_PAGE_SIZE);
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
        console.error('[loadMoreHistory] single failed:', err);
      } finally { setLoadingHistory(false); }

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
    setError(null); setView('single-loading');

    try {

      const res = await multiDialogue.startSession(
        PLAYER_ID,
        PLAYER_NAME,
        selectedParticipants.map(p => p.character_id),
        cleanGroupName,
      );

      const generation = groupRequestGenerationRef.current + 1;
      const groupThreadId = res.group_thread_id || res.session_id;
      groupRequestGenerationRef.current = generation;
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

      setView('group');

    } catch (e) { setError(e.message); setView('group-setup'); }

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
    const singleGeneration = singleRequestGenerationRef.current;
    const singleSessionAtSend = singleSessionId;
    activeSendRequestRef.current = requestToken;

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
    setMessages(prev => view === 'group'
      ? mergeGroupMessages(prev, [pendingGroupMessage])
      : [...prev, {
          role: 'user',
          content: text,
          world_created_at: optimisticWorldCreatedAt,
        }]);

    try {

      if (view === 'single') {

        const res = await dialogue.sendMessage(singleSessionAtSend, text, requestId);
        if (
          singleGeneration !== singleRequestGenerationRef.current
          || activeSessionRef.current !== singleSessionAtSend
        ) return;

        const affinityDelta = currentDelta(res.current_affinity, affinity, res.affinity_delta);
        const trustDelta = currentDelta(res.current_trust, trust, res.trust_delta);
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.dialogue,
          action: res.action || '',
          affinity_delta: affinityDelta,
          trust_delta: trustDelta,
          showRelationshipDelta: true,
          world_created_at: res.world_created_at,
          message_id: res.assistant_message_id,
        }]);

        if (user?.tts_auto_play && res.assistant_message_id != null) {
          enqueueAutoplay(res.assistant_message_id, singleSessionId, 'single');
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

        const sendGroupTurn = (sessionId) => (
          multiDialogue.discussMessage(sessionId, text, null, requestId)
        );

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

        if (groupGeneration !== groupRequestGenerationRef.current) return;
        const groupResponses = Array.isArray(res.responses) ? res.responses : [res];
        const normalizedResponses = groupResponses.map(response => (
          normalizeGroupMessage(response, [...participants, ...allChars], { showRelationshipDelta: true })
        ));
        const addedResponses = registerLoadedGroupMessages(normalizedResponses);
        setMessages(prev => mergeGroupMessages(prev, normalizedResponses));
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
      const isCurrentGroupRequest = view === 'group'
        && groupGeneration === groupRequestGenerationRef.current;
      if (isCurrentGroupRequest && pendingGroupMessage?.client_id) {
        setMessages(prev => mergeGroupMessages(
          prev.filter(message => message.client_id !== pendingGroupMessage.client_id),
          [],
          { replacePending: false },
        ));
        setInput(current => current || text);
      }
      const isCurrentSingleRequest = view === 'single'
        && singleGeneration === singleRequestGenerationRef.current
        && activeSessionRef.current === singleSessionAtSend;
      if (isCurrentSingleRequest || isCurrentGroupRequest) {
        setError(e.message);
      }
    }

    finally {
      if (activeSendRequestRef.current === requestToken) {
        activeSendRequestRef.current = null;
        setSending(false);
        setSendingMulti(false);
      }
    }

  }, [input, sending, sendingMulti, view, singleSessionId, multiSessionId, multiSessionStatus, groupName, affinity, trust, character, participants, allChars, PLAYER_ID, PLAYER_NAME, getWorldNow, syncGroupHistory, user?.tts_auto_play, enqueueAutoplay]);

  sendMessageRef.current = sendMessage;



  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };



  // ── Helpers ──

  const getCharById = (id) => participants.find(p => p.character_id === id) || allChars.find(c => c.character_id === id);

  // ═══════════════════════════════════════════════

  // View: Loading

  // ═══════════════════════════════════════════════

  if (userLoading) {

    return (

      <div className="min-h-screen bg-[#0b0b0c] flex items-center justify-center font-mono">

        <div className="flex flex-col items-center gap-3">

          <Loader2 className="animate-spin text-cyber-green/40" size={22} />

          <span className="text-xs text-cyber-green/35">正在确认登录状态...</span>

        </div>

      </div>

    );

  }

  if (!user) {

    return (

      <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">

        <header className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-[#0d0d14]/80 backdrop-blur-md shrink-0">

          <button onClick={() => navigate('/')} className="text-cyber-green/30 hover:text-cyber-green/50 p-1" aria-label="返回首页"><ArrowLeft size={18} /></button>

          <div className="flex items-center gap-2">

            <Activity size={14} className="text-cyber-green/40" />

            <span className="text-xs font-bold text-cyber-green/60 uppercase tracking-[0.15em]">Memoria</span>

          </div>

        </header>

        <main className="flex-1 flex items-center justify-center px-6">

          <div className="w-full max-w-sm text-center space-y-5">

            <div className="mx-auto w-14 h-14 rounded-full border border-cyber-green/15 bg-cyber-green/[0.03] flex items-center justify-center">

              <User size={22} className="text-cyber-green/35" />

            </div>

            <div className="space-y-2">

              <h1 className="text-base font-semibold text-zinc-200">请先登录后使用对话功能</h1>

              <p className="text-xs leading-6 text-cyber-green/25">登录后可以查看历史对话、开始单聊或创建群聊。</p>

            </div>

            <button onClick={() => navigate('/')} className="w-full min-h-11 rounded-lg border border-cyber-green/20 bg-cyber-green/10 text-sm font-medium text-cyber-green hover:bg-cyber-green/15 transition-colors">

              返回登录

            </button>

          </div>

        </main>

      </div>

    );

  }

  if (view === 'single-loading') {

    return (

      <div className="min-h-screen bg-[#0b0b0c] flex items-center justify-center font-mono">

        <div className="flex flex-col items-center gap-4">

          <div className="relative w-16 h-16 rounded-full border-2 border-cyber-green/20 flex items-center justify-center overflow-hidden">

            {character?.avatar_url ? (

              <img src={character.avatar_url} alt="" className="w-full h-full object-cover opacity-50" />

            ) : (

              <User size={24} className="text-cyber-green/20" />

            )}

            <ScanLine />

          </div>

          <Loader2 className="animate-spin text-cyber-green/40" size={20} />

          <span className="text-xs text-cyber-green/40">正在连接 {character?.name || '角色'}...</span>

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // View: List (Chat tab / Contacts)
  // ═══════════════════════════════════════════════
  if (view === 'list') {
    return (
      <div className="min-h-screen memoria-page flex flex-col font-mono">
        <ChatBackdrop />
        <header className="memoria-glass flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2.5 border-x-0 border-t-0 shrink-0">
          <button
            onClick={() => navigate('/')}
            aria-label="返回首页"
            title="返回首页"
            className="text-cyber-green/30 hover:text-cyber-green/70 hover:bg-cyber-green/5 rounded-lg p-2 min-w-[44px] min-h-[44px] flex items-center justify-center transition-all"
          >
            <ArrowLeft size={18} />
          </button>
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-cyber-green/40" />
            <span className="text-xs font-bold text-cyber-green/60 uppercase tracking-[0.15em]">Memoria</span>
            <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse ml-1" />
          </div>
          <div className="flex-1 hidden sm:flex items-center justify-center max-w-md mx-auto">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyber-green/20" />
              <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="搜索对话..." className="w-full bg-[#0b0b0c]/80 border border-cyber-green/10 rounded-full pl-9 pr-4 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/15 focus:outline-none focus:border-cyber-green/35 focus:ring-2 focus:ring-cyber-green/10 transition-all" />
            </div>
          </div>
          <button onClick={enterGroupSetup} className="text-xs px-3 py-1.5 min-h-[44px] rounded-full border border-cyber-green/15 text-cyber-green/45 hover:text-cyber-green/80 hover:border-cyber-green/35 hover:bg-cyber-green/10 active:scale-95 transition-all flex items-center gap-1.5 shrink-0"><Plus size={14} />群聊</button>
        </header>

        <div className="flex items-center gap-1 px-4 py-2 border-b border-cyber-green/[0.06] bg-[#0d0d14]/50 backdrop-blur-md">
          <button onClick={() => { setActiveTab('chat'); setSearchQuery(''); }} className={`text-xs px-4 py-1.5 min-h-[44px] rounded-full border transition-all ${activeTab === 'chat' ? 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green' : 'border-transparent text-cyber-green/30 hover:text-cyber-green/50'}`}>对话</button>
          <button onClick={() => { setActiveTab('contacts'); setSearchQuery(''); }} className={`text-xs px-4 py-1.5 min-h-[44px] rounded-full border transition-all ${activeTab === 'contacts' ? 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green' : 'border-transparent text-cyber-green/30 hover:text-cyber-green/50'}`}>联系人</button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {activeTab === 'chat' && ((() => {
            if (chatItems.length === 0) {
              return (
                <div className="flex flex-col items-center justify-center h-full text-center p-8 space-y-4">
                  <div className="w-16 h-16 rounded-full border-2 border-dashed border-cyber-green/10 flex items-center justify-center">
                    <MessageSquare size={24} className="text-cyber-green/15" />
                  </div>
                  <p className="text-sm text-cyber-green/20 font-mono">暂无对话记录</p>
                  <p className="text-[11px] text-cyber-green/10">切换至联系人标签开始新对话</p>
                </div>
              );
            }
            return (
              <div className="p-3 space-y-2">
                {chatItems.filter(item => {
                  if (!searchQuery) return true;
                  const name = item.type === 'single' ? item.name : item.group_name || '';
                  const msg = item.last_message || '';
                  return name.toLowerCase().includes(searchQuery.toLowerCase()) || msg.toLowerCase().includes(searchQuery.toLowerCase());
                }).map((item, i) => {
                  const displayTime = item.last_message_at;
                  const timeStr = formatChatTime(displayTime);
                  if (item.type === 'group') {
                    const groupParts = (item.participants || []).map(p => normalizeParticipant(p));
                    const unreadCount = Math.max(0, Number(item.unread_count || 0));
                    return (
                      <div key={`group-${item.group_thread_id || item.session_id || i}`} onClick={() => enterGroupChat(item, groupParts)} className="memoria-glass memoria-card-hover animate-fade-up flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer group relative overflow-hidden" style={{ animationDelay: `${Math.min(i, 12) * 24}ms` }}>
                        <div className="flex -space-x-2 shrink-0">
                          {groupParts.slice(0, 3).map((p, j) => (
                            <div key={p.character_id || j} className="memoria-avatar-ring w-10 h-10 rounded-full overflow-hidden border-2 border-[#0d0d14] bg-[#0b0b0c] ring-1 ring-cyber-green/10 transition-transform duration-200 group-hover:-translate-y-0.5">
                              {p.avatar_url ? (
                                <img src={p.avatar_url} alt="" className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[11px] font-bold">{p.name?.charAt(0) || '?'}</div>
                              )}
                            </div>
                          ))}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5"><span className="font-character text-lg leading-none text-zinc-200 truncate">{item.group_name || '群聊'}</span></div>
                          <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{item.last_message || '暂无消息'}</div>
                        </div>
                        <div className="flex min-w-[44px] flex-col items-end gap-1 shrink-0">
                          <span className="text-[11px] text-cyber-green/15 whitespace-nowrap">{timeStr}</span>
                          {unreadCount > 0 && (
                            <span className="min-w-5 h-5 px-1.5 rounded-full bg-cyber-green/15 border border-cyber-green/25 text-[10px] leading-none text-cyber-green/80 tabular-nums flex items-center justify-center" aria-label={`${unreadCount} 条未读消息`}>
                              {unreadCount > 99 ? '99+' : unreadCount}
                            </span>
                          )}
                        </div>
                        <div className="absolute left-0 top-3 bottom-3 w-px bg-cyber-green/0 group-hover:bg-cyber-green/35 transition-colors pointer-events-none" />
                      </div>
                    );
                  }
                  const itemActive = isCharacterActive(item);
                  return (
                    <div key={item.session_id || i} onClick={() => requestSingleChat(item)} className="memoria-glass memoria-card-hover animate-fade-up flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer group relative overflow-hidden" style={{ animationDelay: `${Math.min(i, 12) * 24}ms` }}>
                      <div className={`memoria-avatar-ring w-10 h-10 rounded-full overflow-hidden border-2 bg-[#0b0b0c] shrink-0 group-hover:border-cyber-green/45 transition-all group-hover:scale-105 ${itemActive ? 'border-slate-700/30' : 'border-zinc-700/30 opacity-60 grayscale'}`}>
                        {item.avatar_url ? <img src={item.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-sm font-bold">{item.name?.charAt(0)}</div>}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={`font-character text-lg leading-none truncate ${itemActive ? 'text-zinc-200' : 'text-zinc-500'}`}>{item.name}</span>
                          {!itemActive && <span className="text-[10px] text-zinc-500 border border-zinc-700/60 rounded-full px-1.5 py-0.5 shrink-0">离线</span>}
                        </div>
                        <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{item.last_message || '暂无消息'}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className="text-[11px] text-cyber-green/15">{timeStr}</span>
                      </div>
                      <div className="absolute left-0 top-3 bottom-3 w-px bg-cyber-green/0 group-hover:bg-cyber-green/35 transition-colors pointer-events-none" />
                    </div>
                  );
                })}
              </div>
            );
          })())}
          {activeTab === 'contacts' && (
            <div className="p-3 space-y-0.5">
              {allChars.filter(c => isCharacterActive(c)).map((char, i) => (
                <div key={char.character_id} onClick={() => requestSingleChat(char)} className="memoria-glass memoria-card-hover animate-fade-up flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer group" style={{ animationDelay: `${Math.min(i, 12) * 22}ms` }}>
                  <div className="memoria-avatar-ring w-10 h-10 rounded-full overflow-hidden border-2 border-slate-700/30 bg-[#0b0b0c] shrink-0 group-hover:border-cyber-green/40 transition-all group-hover:scale-105">
                    {char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-sm font-bold">{char.name?.charAt(0)}</div>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-character text-lg leading-none text-zinc-200 truncate">{char.name}</div>
                    {char.core_identity && <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{char.core_identity}</div>}
                  </div>
                  <div className="flex items-center gap-1.5 text-[11px] text-cyber-green/35 shrink-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/45" />
                    在线
                  </div>
                </div>
              ))}
              {allChars.filter(c => !isCharacterActive(c)).length > 0 && (
                <div className="pt-3 mt-2 border-t border-white/[0.03]">
                  <div className="text-[10px] text-cyber-green/12 uppercase px-2 mb-1">离线</div>
                  {allChars.filter(c => !isCharacterActive(c)).map((char, i) => (
                    <div key={char.character_id} onClick={() => setError('角色已离线，不能新建聊天')} className="animate-fade-up flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all cursor-not-allowed group opacity-50" style={{ animationDelay: `${Math.min(i, 8) * 22}ms` }}>
                      <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-slate-700/30 bg-[#0b0b0c] shrink-0">{char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/10 text-sm font-bold">{char.name?.charAt(0)}</div>}</div>
                      <div className="flex-1 min-w-0"><div className="font-character text-lg leading-none text-zinc-500 truncate">{char.name}</div></div>
                      <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-600" />
                        离线
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

      </div>
    );
  }

  // View: Group Setup

  // ═══════════════════════════════════════════════

  if (view === 'group-setup') {

    return (

      <div className="h-dvh max-h-dvh memoria-page flex flex-col overflow-hidden font-mono">
        <ChatBackdrop origin="bottom-left" tilt={8} />

        <header className="memoria-glass flex items-center gap-3 sm:gap-4 px-3 sm:px-6 py-3 border-x-0 border-t-0 shrink-0">

          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg"><ArrowLeft size={18} /></button>

          <h1 className="text-xs font-bold text-cyber-green/70 uppercase tracking-wider flex items-center gap-2"><Users size={14} />创建群聊</h1>

        </header>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6">
          <div className="max-w-2xl mx-auto w-full space-y-5">

          {error && (

            <div className="flex items-start gap-2 text-[13px] text-red-400/80 bg-red-500/5 border border-red-500/10 rounded-lg px-3 py-2.5">

              <AlertTriangle size={14} className="shrink-0 mt-0.5" /><span>{error}<button onClick={()=>setError(null)} className="ml-2 underline">关闭</button></span>

            </div>

          )}

          {/* Group name */}

          <div className="memoria-glass rounded-xl p-4">

            <label htmlFor="group-name" className="text-[12px] text-cyber-green/40 uppercase tracking-wider mb-2 block">群聊名称</label>

            <input
              id="group-name"
              type="text"
              value={groupName}
              onChange={e => { setGroupName(e.target.value); if (error) setError(null); }}
              maxLength={40}
              placeholder="输入唯一群名"
              aria-invalid={groupNameExists}
              className={`w-full bg-[#0b0b0c]/70 border rounded-lg px-3 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/12 focus:outline-none focus:ring-2 transition-all ${groupNameExists ? 'border-red-400/35 focus:border-red-400/55 focus:ring-red-400/10' : 'border-cyber-green/10 focus:border-cyber-green/35 focus:ring-cyber-green/10'}`}
            />
            {groupNameExists && (
              <p className="mt-2 text-[12px] text-red-400/75">群聊名称已存在，请换一个名称</p>
            )}

          </div>

          {/* Character selection */}

          <div className="memoria-glass rounded-xl p-4">

            <label className="text-[12px] text-cyber-green/40 uppercase tracking-wider mb-2 block">选择角色 ({participants.length})</label>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">

              {allChars.filter(c => isCharacterActive(c)).map((char, i)=>{

                const sel = participants.find(p=>p.character_id===char.character_id);

                return (

                  <div key={char.character_id} onClick={()=>toggleParticipant(char)} className={`memoria-card-hover animate-fade-up flex items-center gap-2 p-2 min-h-[48px] rounded-lg border cursor-pointer transition-all ${sel ? 'border-cyber-green/40 bg-cyber-green/5 shadow-[0_0_22px_rgba(167,239,158,0.08)]' : 'border-white/5 bg-[#0d0d14]/80 hover:border-cyber-green/20'}`} style={{ animationDelay: `${Math.min(i, 12) * 20}ms` }}>

                    <div className="w-8 h-8 rounded-full overflow-hidden border border-white/10 bg-[#0d0d14] shrink-0">

                      {char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-xs font-bold">{char.name?.charAt(0)}</div>}

                    </div>

                    <span className="font-character text-base leading-none text-cyber-green/70 truncate flex-1">{char.name}</span>

                    {sel && <div className="text-cyber-green/40"><X size={13} /></div>}

                  </div>

                );

              })}

            </div>

          </div>

          {participants.length>0 && <div className="flex flex-wrap gap-1.5">{participants.map(p=><div key={p.character_id} className="flex items-center gap-1 text-[12px] bg-cyber-green/5 border border-cyber-green/15 rounded-full px-2 py-1 text-cyber-green/50"><span className="font-character text-sm leading-none">{p.name}</span><button onClick={()=>toggleParticipant(p)} aria-label={`移除 ${p.name}`} title={`移除 ${p.name}`} className="-my-2 -mr-2 ml-0.5 flex h-11 w-11 items-center justify-center text-cyber-green/20 transition-colors hover:text-red-400"><X size={10}/></button></div>)}</div>}

          <button onClick={startGroupChat} disabled={participants.length<2 || !groupName.trim() || groupNameExists} className="w-full min-h-[44px] py-2.5 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-sm font-bold text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"><Users size={16} />开始群聊 ({participants.length}人)</button>
          </div>

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // View: Single Chat

  // ═══════════════════════════════════════════════

  if (view === 'single') {

    return renderSingleChat();

  }



  // ═══════════════════════════════════════════════

  // View: Group Chat

  // ═══════════════════════════════════════════════

  if (view === 'group') {

    return renderGroupChat();

  }



  return null;



  // ═══════════════════════════════════════════════

  // Single Chat Render

  // ═══════════════════════════════════════════════

  function renderSingleChat() {

    const singleReadOnly = !isCharacterActive(character);
    const moodEmoji = MOOD_EMOJI[mood] || '😐';
    const moodBorder = MOOD_BORDER[mood] || 'border-slate-500/40';
    const moodGlow = MOOD_GLOW[mood] || '';
    const moodBubble = MOOD_BUBBLE[mood] || MOOD_BUBBLE.neutral;
    const affinityPct = Math.round((affinity + 100) / 2);
    const affinityColor = affinity > 30 ? 'text-red-400' : affinity < -30 ? 'text-blue-400' : 'text-cyber-green/40';
    const trustValue = Math.min(100, Math.max(0, Math.round(Number(trust) || 0)));
    const trustStars = Math.min(5, Math.max(0, Math.round(trustValue / 20)));

    return (
      <div className="h-dvh max-h-dvh memoria-page font-mono flex flex-col overflow-hidden">
        <ChatBackdrop />

        {/* ═══ Top bar: 融合型 — 返回+名字+状态徽章 ═══ */}
        <header className="memoria-glass flex items-center gap-2 px-2.5 sm:px-3 py-2 border-x-0 border-t-0 shrink-0">
          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg shrink-0">
            <ArrowLeft size={18} />
          </button>

          {/* 角色头像小圆圈 — 点击展开详情 */}
          <div
            onClick={() => setShowDetail(!showDetail)}
            className={`memoria-avatar-ring w-8 h-8 rounded-full overflow-hidden border-2 shrink-0 cursor-pointer ${moodBorder} ${moodGlow} transition-all duration-500 hover:scale-105`}
          >
            {character?.avatar_url
              ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
              : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-xs font-bold">{character?.name?.charAt(0)}</div>}
          </div>

          {/* 角色名 + 状态徽章行 — 点击展开详情 */}
          <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setShowDetail(!showDetail)}>
            <div className="flex items-center gap-2">
              <h1 className="font-character text-lg leading-none text-zinc-200 truncate">{character?.name}</h1>
              {singleReadOnly
                ? <span className="text-[10px] text-zinc-500 border border-zinc-700/60 rounded-full px-1.5 py-0.5 shrink-0">离线</span>
                : sending && <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse shrink-0" />}
            </div>
            {/* 第二行：好感度 | 情绪 | 信任星级 */}
            <div className="flex items-center gap-1.5 sm:gap-2 text-[12px] mt-0.5 overflow-hidden">
              <span className={`flex items-center gap-0.5 ${affinityColor}`}>
                <Heart size={10} fill={affinity > 30 ? 'currentColor' : 'none'} />
                {affinity}
              </span>
              <span className="text-zinc-500">|</span>
              <span className="flex items-center gap-0.5 text-zinc-400">
                <span className="text-sm leading-none">{moodEmoji}</span>
                {MOOD_LABELS[mood]}
              </span>
              <span className="text-zinc-500">|</span>
              <span className="flex items-center gap-0.5 text-amber-400/60">
                {[...Array(5)].map((_, i) => (
                  <span key={i} className={i < trustStars ? 'text-amber-400' : 'text-zinc-600'}>★</span>
                ))}
              </span>
            </div>
          </div>

          <WorldClockDisplay
            className="max-w-[178px] sm:max-w-[260px]"
            onClick={() => setShowClockSettings(true)}
          />

          {/* 事件通知 */}
          {events.length > 0 && (
            <button onClick={() => setEvents([])} className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-amber-400/5" aria-label="清除事件通知" title="事件通知">
              <AlertTriangle size={14} className="text-amber-400/70" />
              <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-red-500 rounded-full text-[13px] flex items-center justify-center text-white font-bold">{events.length}</span>
            </button>
          )}
        </header>

        <EventInboxBanner
          characterId={character?.character_id}
          sessionId={singleSessionId}
        />

        {/* ═══ 状态详情下拉面板 ═══ */}
        {showDetail && (
          <div className="memoria-glass animate-fade-up border-x-0 border-t-0 px-4 py-3 space-y-3 shrink-0">
            {/* 头像+名字+简介 */}
            <div className="flex items-center gap-3">
              <div className={`w-14 h-14 rounded-full overflow-hidden border-2 ${moodBorder} ${moodGlow}`}>
                {character?.avatar_url
                  ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
                  : <div className="w-full h-full flex items-center justify-center text-cyber-green/20"><User size={24} /></div>}
              </div>
              <div className="flex-1">
                <h2 className="font-character text-xl leading-none text-zinc-100">{character?.name}</h2>
                {character?.identity?.core_identity_summary && (
                  <p className="text-[12px] text-zinc-500">{character.identity.core_identity_summary}</p>
                )}
              </div>
              <button onClick={() => setShowDetail(false)} className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/20 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/40" aria-label="关闭角色详情" title="关闭角色详情"><X size={16} /></button>
            </div>

            {/* 标签 */}
            {character?.status_labels?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {character.status_labels.slice(0, 4).map((t, i) => (
                  <span key={i} className="text-[13px] px-2 py-0.5 rounded-full bg-cyber-green/5 border border-cyber-green/10 text-cyber-green/40">{t}</span>
                ))}
              </div>
            )}

            {/* RPG 状态条 */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="flex justify-between text-[12px] mb-0.5"><span className="text-cyber-green/40">好感度</span><span className={affinityColor}>{affinity}</span></div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-red-400/30 to-red-400/60 rounded-full transition-all duration-700" style={{ width: `${affinityPct}%` }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-[12px] mb-0.5"><span className="text-cyber-green/40">信任度</span><span className="text-amber-400/60">{trustValue}</span></div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-amber-400/30 to-amber-400/60 rounded-full transition-all duration-700" style={{ width: `${trustValue}%` }} />
                </div>
              </div>
            </div>

            {/* 情绪 */}
            <div className="flex items-center gap-2 text-[12px] text-cyber-green/40">
              <span className="text-base">{moodEmoji}</span>
              <span>当前情绪: {MOOD_LABELS[mood]}</span>
            </div>
          </div>
        )}

        {/* ═══ 消息气泡区 ═══ */}
        <div ref={messageScrollRef} style={{ overflowAnchor: 'none' }} className="relative flex-1 min-h-0 overflow-y-auto px-2.5 sm:px-3 py-3 space-y-3"
          onScroll={(e) => { if (e.target.scrollTop < 60 && !loadingHistory && hasMoreHistory) loadMoreHistory(); }}>

          {error && (
            <div className="text-center text-red-400/50 text-xs p-2 bg-red-500/5 rounded-lg border border-red-500/10">
              {error}<button onClick={() => setError(null)} className="ml-2 underline">关闭</button>
            </div>
          )}

          {messages.flatMap((msg, i) => {
            const isUser = msg.role === 'user';
            const charInfo = msg.charId ? getCharById(msg.charId) : null;
            const replyBubbles = isUser ? [msg.content] : splitAssistantReply(msg.content);
            const currentWorldDate = worldDateKey(msg.world_created_at);
            const previousWorldDate = worldDateKey(messages[i - 1]?.world_created_at);
            const showWorldDate = !!currentWorldDate && currentWorldDate !== previousWorldDate;
            return replyBubbles.map((bubble, bubbleIndex) => {
              const isLastBubble = bubbleIndex === replyBubbles.length - 1;
              return (
              <Fragment key={`${msg.message_id ?? msg.client_id ?? i}-${bubbleIndex}`}>
              {bubbleIndex === 0 && showWorldDate && (
                <WorldDateSeparator value={msg.world_created_at} />
              )}
              <div className={`animate-fade-up flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
                {/* 头像 */}
                <div className={`w-8 h-8 rounded-full overflow-hidden border-2 shrink-0 mt-0.5 ${
                  isUser ? 'border-cyber-green/10 bg-cyber-green/[0.03]' : moodBorder
                }`}>
                  {isUser ? (
                    user?.avatar_url
                      ? <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
                      : <div className="w-full h-full flex items-center justify-center text-cyber-green/40 text-[13px] font-bold">{user?.username?.charAt(0)?.toUpperCase() || <User size={14} className="text-cyber-green/30" />}</div>
                  ) : charInfo?.avatar_url || character?.avatar_url ? (
                    <img src={charInfo?.avatar_url || character?.avatar_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-purple-800/10 text-purple-300/30 text-[13px] font-bold">
                      {charInfo?.name?.charAt(0) || character?.name?.charAt(0) || '?'}
                    </div>
                  )}
                </div>

                {/* 气泡内容 */}
                <div className={`max-w-[82%] sm:max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>
                  {/* 角色名 + action 标签 */}
                  {!isUser && (
                    <div className="flex items-center gap-1.5 mb-0.5 ml-1">
                      <span className="font-character text-sm leading-none text-zinc-400">{msg.charName || character?.name}</span>
                    </div>
                  )}

                  <div
                    className={`memoria-card-hover px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words border backdrop-blur-sm ${
                      isUser
                        ? 'bg-cyber-green/10 border-cyber-green/15 rounded-br-sm text-cyber-green/85'
                        : `${moodBubble} border rounded-bl-sm`
                    }`}
                  >
                    <MessageContent content={bubble} />
                  </div>

                  {msg.showRelationshipDelta && isLastBubble && (
                    <RelationshipDeltaLine affinityDelta={msg.affinity_delta} trustDelta={msg.trust_delta} />
                  )}
                  {isLastBubble && (
                    <MessageWorldTime
                      value={msg.world_created_at}
                      align={isUser ? 'right' : 'left'}
                    />
                  )}
                  {!isUser && isLastBubble && msg.message_id != null && (
                    <MessageAudioControl
                      messageId={msg.message_id}
                      getAudioState={getAudioState}
                      onToggle={toggleAudio}
                      onRetry={retryAudio}
                    />
                  )}
                </div>
              </div>
              </Fragment>
              );
            });
          })}

          {/* 思考中动画 */}
          {sending && (
            <div className="flex gap-2">
              <div className={`w-8 h-8 rounded-full overflow-hidden border-2 ${moodBorder} bg-purple-500/[0.02] flex items-center justify-center shrink-0 mt-0.5 relative`}>
                <Loader2 className="animate-spin text-cyber-green/25" size={14} />
                <ScanLine />
              </div>
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-2xl rounded-bl-sm px-4 py-2.5 relative">
                <div className="flex items-center gap-1.5">
                  <Cpu size={12} className="text-cyber-green/25 animate-pulse" />
                  <span className="text-[13px] text-cyber-green/25">思考中...</span>
                  <span className="flex gap-1 ml-1">
                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" />
                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{ animationDelay: '0.15s' }} />
                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{ animationDelay: '0.3s' }} />
                  </span>
                </div>
                <ScanLine />
              </div>
            </div>
          )}

          <div ref={bottomRef} />

          {loadingHistory && (
            <div className="absolute top-2 inset-x-0 z-10 flex justify-center pointer-events-none">
              <Loader2 className="animate-spin text-cyber-green/40" size={16} />
            </div>
          )}
        </div>

        {/* ═══ 底部输入栏 — 功能型 ═══ */}
        <div className="px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] border-t border-white/5 bg-[#0d0d14]/60 backdrop-blur-md shrink-0">
          <SpeechErrorNotice error={speechError} onDismiss={clearSpeechError} onRetry={startRecording} />
          <div className="flex items-end gap-1.5">
            <SpeechRecorderButton
              status={speechStatus}
              supported={isRecordingSupported}
              disabled={singleReadOnly || sending || sendingMulti}
              onStart={startRecording}
              onStop={stopRecording}
            />
            {/* 输入框 */}
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder={singleReadOnly ? '角色已离线，只能查看历史' : '输入消息...'}
              disabled={singleReadOnly || sending || sendingMulti}
              className="flex-1 bg-[#0b0b0c] border border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/10 resize-none focus:outline-none focus:border-cyber-green/30 transition-colors disabled:opacity-40 min-h-[44px] max-h-[100px]"
            />

            {/* 发送按钮 */}
            <button
              onClick={sendMessage}
              disabled={singleReadOnly || !input.trim() || sending || sendingMulti}
              aria-label="发送消息"
              className="px-3 py-2 min-w-[44px] min-h-[44px] bg-cyber-green/10 hover:bg-cyber-green/[0.18] active:scale-95 border border-cyber-green/20 rounded-xl text-cyber-green disabled:opacity-20 disabled:cursor-not-allowed disabled:active:scale-100 transition-all shrink-0 flex items-center justify-center"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
        {showClockSettings && <UserSettingsModal onClose={() => setShowClockSettings(false)} />}
      </div>
    );

  }
  function renderGroupChat() {

    const resolvedParticipants = participants.map(p => normalizeParticipant(p));
    const activeParticipantCount = resolvedParticipants.filter(p => isCharacterActive(p)).length;

    return (

      <div className="h-dvh max-h-dvh memoria-page font-mono flex flex-col overflow-hidden">
        <ChatBackdrop origin="bottom-right" tilt={6} />

        {/* Top bar */}

        <header className="memoria-glass flex items-center gap-2 sm:gap-3 px-2.5 sm:px-4 py-2.5 border-x-0 border-t-0 shrink-0">

          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg"><ArrowLeft size={18} /></button>

          <div className="hidden -space-x-2 sm:flex">

            {resolvedParticipants.slice(0,3).map(p => (

              <div key={p.character_id} className="memoria-avatar-ring w-9 h-9 rounded-full overflow-hidden border-2 border-[#0d0d14] bg-[#0b0b0c] transition-transform duration-200 hover:-translate-y-0.5">

                {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

              </div>

            ))}

          </div>

          <div className="flex-1 min-w-0">

            <h1 className="font-character text-lg leading-none text-zinc-200 truncate">{groupName || '群聊'} · {resolvedParticipants.length}人</h1>

            <div className="flex items-center gap-1.5 text-[13px] text-cyber-green/30">

              <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse" />

              {sendingMulti ? '角色思考中...' : `${activeParticipantCount} 在线`}

            </div>

          </div>

          <WorldClockDisplay
            className="max-w-[178px] sm:max-w-[260px]"
            onClick={() => setShowClockSettings(true)}
          />

        </header>



        {/* Two-panel body */}

        <div className="flex flex-1 min-h-0">

          {/* Left: Member Panel */}

          <aside className="hidden lg:flex w-[280px] min-h-0 flex-col border-r border-cyber-green/10 bg-[#0d0d14]/60 backdrop-blur-md overflow-y-auto shrink-0">

            <div className="p-4 space-y-3">

              <h3 className="text-[13px] text-cyber-green/30 uppercase tracking-[0.2em] flex items-center gap-1.5"><Users size={10} />群成员 ({resolvedParticipants.length})</h3>

              {resolvedParticipants.map((p, i) => (

                <div key={p.character_id} className="memoria-card-hover animate-fade-up flex items-center gap-2.5 p-2 rounded-lg hover:bg-white/[0.03] transition-colors" style={{ animationDelay: `${Math.min(i, 10) * 24}ms` }}>

                  <div className="w-9 h-9 rounded-full overflow-hidden border-2 border-white/10 shrink-0">

                    {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

                  </div>

                  <div className="flex-1 min-w-0">

                    <div className="font-character text-base leading-none text-zinc-200 truncate">{p.name}</div>

                    <div className="flex items-center gap-1 text-[13px] text-cyber-green/20">

                      <span className={`w-1 h-1 rounded-full ${isCharacterActive(p) ? 'bg-cyber-green/30 animate-pulse' : 'bg-zinc-600'}`} />

                      {isCharacterActive(p) ? '在线' : '离线'}

                    </div>

                  </div>

                </div>

              ))}

            </div>

          </aside>



          {/* Right: Chat area */}

          {renderChatArea('group')}

        </div>

        {showClockSettings && <UserSettingsModal onClose={() => setShowClockSettings(false)} />}

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // Shared Chat Area

  // ═══════════════════════════════════════════════

  function renderChatArea(mode) {

    const renderedParticipants = mode === 'group'
      ? participants.map(p => normalizeParticipant(p))
      : participants;

    return (

      <div className="flex-1 min-h-0 flex flex-col min-w-0">

        <EventInboxBanner
          characterId={mode === 'single' ? character?.character_id : null}
          sessionId={mode === 'group' ? multiSessionId : singleSessionId}
        />

        {/* Mobile: compact character info */}

        {mode === 'single' && (

          <div className="lg:hidden flex items-center gap-2 px-4 py-2 border-b border-white/5 bg-[#0d0d14]/40 shrink-0">

            <div className={`w-7 h-7 rounded-full overflow-hidden border-2 ${MOOD_BORDER[mood]} shrink-0`}>

              {character?.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{character?.name?.charAt(0)}</div>}

            </div>

            <div className="flex-1 flex items-center gap-3 text-[12px]">

              <span className="text-cyber-green/30 flex items-center gap-1"><Heart size={12} className={affinity>30?'text-red-400':''}/>{affinity}</span>

              <span className="text-cyber-green/30">{MOOD_EMOJI[mood]} {MOOD_LABELS[mood]}</span>

              {/* Affinity bar mobile */}

              <div className="flex-1 max-w-[80px]">

                <div className="h-1 bg-white/5 rounded-full overflow-hidden">

                  <div className="h-full bg-cyber-green/40 rounded-full transition-all" style={{width:`${Math.round((affinity+100)/2)}%`}} />

                </div>

              </div>

            </div>

          </div>

        )}



        {/* Messages */}

        <div ref={messageScrollRef} style={{ overflowAnchor: 'none' }} className="relative flex-1 min-h-0 overflow-y-auto px-2.5 sm:px-4 py-3 space-y-3" onScroll={(e) => {

          if (e.target.scrollTop < 60 && !loadingHistory && hasMoreHistory) loadMoreHistory();

        }}>

          {error && (

            <div className="text-center text-red-400/50 text-xs p-2 bg-red-500/5 rounded-lg border border-red-500/10">

              {error}<button onClick={()=>setError(null)} className="ml-2 underline">关闭</button>

            </div>

          )}

          {messages.flatMap((msg, i) => {

            const isUser = msg.role === 'user';

            const charInfo = msg.charId ? getCharById(msg.charId) : null;

            const replyBubbles = isUser ? [msg.content] : splitAssistantReply(msg.content);

            const currentWorldDate = worldDateKey(msg.world_created_at);

            const previousWorldDate = worldDateKey(messages[i - 1]?.world_created_at);

            const showWorldDate = !!currentWorldDate && currentWorldDate !== previousWorldDate;

            return replyBubbles.map((bubble, bubbleIndex) => {

              const isLastBubble = bubbleIndex === replyBubbles.length - 1;

              return (

              <Fragment key={`${msg.message_id ?? msg.client_id ?? i}-${bubbleIndex}`}>

              {bubbleIndex === 0 && showWorldDate && (

                <WorldDateSeparator value={msg.world_created_at} />

              )}

              <div className={`animate-fade-up flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>

                <div className={`w-8 h-8 sm:w-10 sm:h-10 rounded-full overflow-hidden border-2 shrink-0 mt-0.5 ${isUser ? 'border-cyber-green/10 bg-cyber-green/[0.03] flex items-center justify-center' : 'border-purple-500/15'}`}>

                  {isUser ? (

                    user?.avatar_url ? (

                      <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />

                    ) : user ? (

                      <div className="w-full h-full flex items-center justify-center text-cyber-green/40 text-[13px] font-bold">{user.username?.charAt(0)?.toUpperCase()}</div>

                    ) : (

                      <User size={18} className="text-cyber-green/30" />

                    )

                  ) : charInfo?.avatar_url || mode==='single' && character?.avatar_url ? (

                    <img src={charInfo?.avatar_url || character?.avatar_url} alt="" className="w-full h-full object-cover" />

                  ) : (

                    <div className="w-full h-full flex items-center justify-center bg-purple-800/10 text-purple-300/30 text-[13px] font-bold">

                      {charInfo?.name?.charAt(0) || character?.name?.charAt(0) || '?'}

                    </div>

                  )}

                </div>

                <div className={`max-w-[82%] sm:max-w-[72%] ${isUser ? 'items-end' : 'items-start'}`}>

                  {!isUser && (msg.charName || mode==='single') && (

                    <div className="font-character text-sm leading-none text-cyber-green/35 mb-1 ml-1">

                      {mode==='single' ? character?.name : msg.charName}

                    </div>

                  )}

                  <div className={`memoria-card-hover px-3 py-2 rounded-xl text-sm leading-relaxed whitespace-pre-wrap break-words backdrop-blur-sm ${

                    isUser

                      ? 'bg-cyber-green/10 border border-cyber-green/15 rounded-br-sm text-cyber-green/85'

                      : 'bg-white/[0.03] border border-white/[0.06] rounded-bl-sm text-zinc-300'

                  }`}>

                    <MessageContent content={bubble} />

                    {/* Scan line on AI messages when sending */}

                    {!isUser && sendingMulti && i === messages.length - 1 && isLastBubble && <ScanLine />}

                  </div>

                  {msg.showRelationshipDelta && isLastBubble && (
                    <RelationshipDeltaLine affinityDelta={msg.affinity_delta} trustDelta={msg.trust_delta} />
                  )}

                  {isLastBubble && (

                    <MessageWorldTime

                      value={msg.world_created_at}

                      align={isUser ? 'right' : 'left'}

                    />

                  )}

                  {!isUser && isLastBubble && msg.message_id != null && (
                    <MessageAudioControl
                      messageId={msg.message_id}
                      getAudioState={getAudioState}
                      onToggle={toggleAudio}
                      onRetry={retryAudio}
                    />
                  )}

                </div>

              </div>

              </Fragment>

              );

            });

          })}

          {sending && (

            <div className="flex gap-2.5">

              <div className="w-8 h-8 rounded-full overflow-hidden border-2 border-purple-500/10 bg-purple-500/[0.02] flex items-center justify-center shrink-0 mt-0.5 relative">

                <Loader2 className="animate-spin text-cyber-green/25" size={14} />

                <ScanLine />

              </div>

              <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl rounded-bl-sm px-4 py-2.5 relative">

                <div className="flex items-center gap-1.5">

                  <Cpu size={12} className="text-cyber-green/25 animate-pulse" />

                  <span className="text-[13px] text-cyber-green/25">角色思考中</span>

                  <span className="flex gap-1 ml-1">

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" />

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{animationDelay:'0.15s'}} />

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{animationDelay:'0.3s'}} />

                  </span>

                </div>

                <ScanLine />

              </div>

            </div>

          )}

          <div ref={bottomRef} />

          {loadingHistory && (

            <div className="absolute top-2 inset-x-0 z-10 flex justify-center pointer-events-none">

              <Loader2 className="animate-spin text-cyber-green/40" size={16} />

            </div>

          )}

        </div>



        {/* Participant strip (group) */}

        {mode === 'group' && (

          <div className="px-4 py-1.5 flex items-center gap-2 border-t border-white/[0.03] bg-[#0d0d14]/35 overflow-x-auto shrink-0">

            {renderedParticipants.map((p, i) => (

              <div key={p.character_id} className="animate-fade-up flex flex-col items-center gap-0.5 shrink-0" style={{ animationDelay: `${Math.min(i, 12) * 18}ms` }} title={p.name}>

                <div className={`w-7 h-7 rounded-full overflow-hidden border border-white/5 bg-[#0d0d14] ${isCharacterActive(p) ? '' : 'opacity-45 grayscale'}`}>

                  {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

                </div>

                <span className={`font-character text-sm leading-none truncate max-w-[52px] ${isCharacterActive(p) ? 'text-cyber-green/25' : 'text-zinc-600'}`}>{p.name}</span>

              </div>

            ))}

          </div>

        )}



        {/* Input */}

        <div className="px-3 sm:px-4 pt-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] border-t border-white/5 bg-[#0d0d14]/60 backdrop-blur-md shrink-0">

          <SpeechErrorNotice error={speechError} onDismiss={clearSpeechError} onRetry={startRecording} />

          <div className="flex gap-2">

            <SpeechRecorderButton
              status={speechStatus}
              supported={isRecordingSupported}
              disabled={sending || sendingMulti}
              onStart={startRecording}
              onStop={stopRecording}
            />

            <textarea

              ref={inputRef}

              value={input}

              onChange={e => setInput(e.target.value)}

              onKeyDown={handleKeyDown}

              rows={1}

              placeholder="输入消息..."

              disabled={sending || sendingMulti}

              className="flex-1 bg-[#0b0b0c] border border-white/10 rounded-xl px-3 sm:px-4 py-2.5 text-sm text-zinc-300 placeholder:text-cyber-green/10 resize-none focus:outline-none focus:border-cyber-green/30 transition-colors disabled:opacity-40 min-h-[44px] max-h-[96px]"

            />

            <button

              onClick={sendMessage}

              disabled={!input.trim() || sending || sendingMulti}

              aria-label="发送消息"

              className="px-3 sm:px-4 py-2.5 bg-cyber-green/10 hover:bg-cyber-green/[0.18] active:scale-95 border border-cyber-green/20 rounded-xl text-cyber-green disabled:opacity-20 disabled:cursor-not-allowed disabled:active:scale-100 transition-all shrink-0 min-w-[44px] min-h-[44px] flex items-center justify-center"

            >

              <Send size={16} />

            </button>

          </div>

          <div className="hidden sm:block text-[12px] text-cyber-green/10 mt-1.5 text-center">Enter 发送 · Shift+Enter 换行</div>

        </div>

      </div>

    );

  }

}
