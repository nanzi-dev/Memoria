import {
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

import { useArchiveShell } from '../archive/ArchiveShell';
import { Button } from '../components/ui/button';
import ChatAvatar from '../components/chat/ChatAvatar';
import ChatGroupSetup from '../components/chat/ChatGroupSetup';
import ChatListView from '../components/chat/ChatListView';
import ChatWorkbench from '../components/chat/ChatWorkbench';

import { beginOwnedRequest, createRequestEpoch } from '../utils/asyncRequestState';
import {
  canApplySingleHistory,
  createPendingUserMessage,
  removePendingMessage,
  restoreFailedDraft,
  settlePendingMessage,
} from './chatOptimisticState';
import { reconcileTurn } from '../utils/dialogueStreamState';
import { retryDialogueTurnConflict } from '../utils/dialogueFallback';
import useBrowserSpeech from '../hooks/useBrowserSpeech';
import {
  applyDialogueStreamEvent,
  createClientMessageId,
  createRequestId,
  currentDelta,
  GROUP_POLL_INTERVAL_MS,
  HISTORY_PAGE_SIZE,
  IDLE_SESSION_END_MS,
  maxGroupMessageId,
  mergeGroupMessages,
  normalizeDialogueMessage,
  normalizeGroupMessage,
  removeDialogueStreamPlaceholders,
  shouldFallbackFromDialogueStream,
  sortMessagesChronologically,
  stableGroupMessageKey,
} from '../utils/chatRoom';
import { ArrowLeft, Loader2, Plus, User } from 'lucide-react';

export {
  applyDialogueStreamEvent,
  removeDialogueStreamPlaceholders,
  shouldFallbackFromDialogueStream,
} from '../utils/chatRoom';

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
      queueMicrotask(() => {
        if (activeSendRequestRef.current) {
          setInput(current => restoreFailedDraft(current, cleanText));
          return;
        }
        sendMessageRef.current?.(cleanText);
      });
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

    } catch (e) {
      if (isCurrentRequest()) setError(`会话列表加载失败：${e.message}`);
    }

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

    const text = String(typeof textOverride === 'string' ? textOverride : input).trim();

    if (activeSendRequestRef.current) return;

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



  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); sendMessage(); } };



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
          <ChatAvatar entity={character} sizeClass="h-10 w-10" />
          <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
          <span className="text-sm">正在连接 {character?.name || '角色'}</span>
        </div>
      </div>
    );
  }

  if (view === 'list') {
    return (
      <ChatListView
        activeTab={activeTab}
        onTabChange={value => {
          setActiveTab(value);
          setSearchQuery('');
        }}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        chatItems={chatItems}
        allChars={allChars}
        error={error}
        onDismissError={() => setError(null)}
        isCharacterActive={isCharacterActive}
        normalizeParticipant={normalizeParticipant}
        onEnterGroupSetup={enterGroupSetup}
        onRequestSingleChat={requestSingleChat}
        onEnterGroupChat={enterGroupChat}
        onOfflineContact={() => setError('角色已离线，不能新建聊天')}
      />
    );
  }
  if (view === 'group-setup') {
    return (
      <ChatGroupSetup
        groupName={groupName}
        onGroupNameChange={value => {
          setGroupName(value);
          if (error) setError(null);
        }}
        groupNameExists={groupNameExists}
        error={error}
        onDismissError={() => setError(null)}
        allChars={allChars}
        participants={participants}
        isCharacterActive={isCharacterActive}
        onToggleParticipant={toggleParticipant}
        onStartGroupChat={startGroupChat}
        onGoToList={goToList}
      />
    );
  }
  if (view === 'single' || view === 'group') {
    return (
      <ChatWorkbench
        mode={view}
        activeTab={activeTab}
        onTabChange={value => {
          setActiveTab(value);
          setSearchQuery('');
        }}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        chatItems={chatItems}
        allChars={allChars}
        error={error}
        onDismissError={() => setError(null)}
        onEnterGroupSetup={enterGroupSetup}
        onRequestSingleChat={requestSingleChat}
        onEnterGroupChat={enterGroupChat}
        onOfflineContact={() => setError('角色已离线，不能新建聊天')}
        character={character}
        participants={participants}
        groupName={groupName}
        singleSessionId={singleSessionId}
        multiSessionId={multiSessionId}
        multiSessionStatus={multiSessionStatus}
        groupHistoryReady={groupHistoryReady}
        messages={messages}
        input={input}
        affinity={affinity}
        trust={trust}
        mood={mood}
        events={events}
        isRecovered={isRecovered}
        sending={sending}
        sendingMulti={sendingMulti}
        showDetail={showDetail}
        onToggleDetail={() => setShowDetail(current => !current)}
        showClockSettings={showClockSettings}
        onShowClockSettings={() => setShowClockSettings(true)}
        onCloseClockSettings={() => setShowClockSettings(false)}
        onGoToList={goToList}
        onInputChange={setInput}
        onInputKeyDown={handleKeyDown}
        onSend={sendMessage}
        loadingHistory={loadingHistory}
        hasMoreHistory={hasMoreHistory}
        onLoadMore={loadMoreHistory}
        inputRef={inputRef}
        messageScrollRef={messageScrollRef}
        bottomRef={bottomRef}
        speechStatus={speechStatus}
        speechError={speechError}
        isRecordingSupported={isRecordingSupported}
        onStartRecording={startRecording}
        onStopRecording={stopRecording}
        onDismissSpeechError={clearSpeechError}
        getAudioState={getAudioState}
        onToggleAudio={toggleAudio}
        onRetryAudio={retryAudio}
        isCharacterActive={isCharacterActive}
        normalizeParticipant={normalizeParticipant}
        getCharById={getCharById}
        onClearEvents={() => setEvents([])}
      />
    );
  }
  return null;

}
