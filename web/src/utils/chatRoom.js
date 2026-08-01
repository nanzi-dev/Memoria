import {
  appendDialogueDelta,
  completeCharacter,
  reconcileTurn,
  startCharacter,
} from './dialogueStreamState';

export const MOOD_LABELS = {
  happy: '开心',
  neutral: '平静',
  sad: '悲伤',
  angry: '愤怒',
  surprised: '惊讶',
  fearful: '恐惧',
  disgusted: '厌恶',
};

export const MOOD_EMOJI = {
  happy: '😊',
  neutral: '😐',
  sad: '😢',
  angry: '😠',
  surprised: '😲',
  fearful: '😨',
  disgusted: '😖',
};

export const IDLE_SESSION_END_MS = 5 * 60 * 1000;
export const HISTORY_PAGE_SIZE = 20;
export const GROUP_POLL_INTERVAL_MS = 3 * 1000;

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

export function shouldFallbackFromDialogueStream(receivedDialogueDelta) {
  return receivedDialogueDelta !== true;
}

const toDelta = (value) => {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
};

export const currentDelta = (currentValue, previousValue, fallbackDelta = 0) => {
  if (currentValue == null) return toDelta(fallbackDelta);
  const current = Number(currentValue);
  const previous = Number(previousValue ?? 0);
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return toDelta(fallbackDelta);
  const delta = current - previous;
  return Number.isFinite(delta) ? Number(delta.toFixed(6)) : toDelta(fallbackDelta);
};

export function normalizeDialogueMessage(message, options = {}) {
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

export function normalizeGroupMessage(message, knownParticipants = [], options = {}) {
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

export function stableGroupMessageKey(message) {
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

export function mergeGroupMessages(currentMessages, incomingMessages, options = {}) {
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

export function maxGroupMessageId(messages, fallback = 0) {
  return messages.reduce((latest, message) => {
    const messageId = Number(message?.message_id);
    return Number.isFinite(messageId) ? Math.max(latest, messageId) : latest;
  }, fallback);
}

export function createRequestId(prefix = 'request') {
  return globalThis.crypto?.randomUUID?.()
    ?? `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createClientMessageId() {
  return createRequestId('group-message');
}

export function formatChatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function worldDateKey(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

export function formatWorldDate(value) {
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

export function formatWorldTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

export function sortMessagesChronologically(messages) {
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
