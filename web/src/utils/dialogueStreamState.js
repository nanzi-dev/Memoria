function eventData(event) {
  return event?.data && typeof event.data === 'object' ? event.data : (event || {});
}

function responseData(event) {
  const data = eventData(event);
  return data?.response && typeof data.response === 'object' ? data.response : data;
}

function copyResponseFields(message, response) {
  const next = { ...message };
  [
    'action',
    'affinity_delta',
    'trust_delta',
    'current_affinity',
    'current_trust',
    'current_mood',
    'triggered_events',
    'event_executions',
    'event_notifications',
    'event_notification',
    'created_at',
    'world_created_at',
    'knowledge_sources',
    'session_id',
    'reply_to_message_id',
    'reply_to_character_id',
    'intent',
    'topic',
    'trigger_source',
  ].forEach(key => {
    if (response[key] !== undefined) next[key] = response[key];
  });
  return next;
}

function responseMessage(response, existing = {}, preserveVisibleContent = false) {
  let message = copyResponseFields(existing, response);
  const finalContent = response.content ?? response.dialogue ?? response.message;
  const charId = response.charId ?? response.character_id;
  const charName = response.charName ?? response.character_name;
  const messageId = response.message_id ?? response.assistant_message_id;

  message.role = 'assistant';
  if (!preserveVisibleContent || !message.content) {
    message.content = finalContent ?? message.content ?? '';
  }
  if (charId !== undefined) message.charId = charId;
  if (charName !== undefined) message.charName = charName;
  if (messageId !== undefined) message.message_id = messageId;
  return message;
}

export function startCharacter(state, event) {
  const data = eventData(event);
  if (!data.stream_id) return state;

  const existingIndex = state.findIndex(message => message.stream_id === data.stream_id);
  if (existingIndex >= 0) {
    return state.map((message, index) => {
      if (index !== existingIndex) return message;
      return {
        ...message,
        ...(data.character_id !== undefined ? { charId: data.character_id } : {}),
        ...(data.character_name !== undefined ? { charName: data.character_name } : {}),
        _streaming: true,
      };
    });
  }

  return [
    ...state,
    {
      role: 'assistant',
      content: '',
      stream_id: data.stream_id,
      ...(data.character_id !== undefined ? { charId: data.character_id } : {}),
      ...(data.character_name !== undefined ? { charName: data.character_name } : {}),
      _streaming: true,
    },
  ];
}

export function appendDialogueDelta(state, event) {
  const data = eventData(event);
  if (!data.stream_id || data.delta == null) return state;

  return state.map(message => (
    message.stream_id === data.stream_id
      ? { ...message, content: `${message.content || ''}${data.delta}` }
      : message
  ));
}

export function completeCharacter(state, event) {
  const data = eventData(event);
  const response = responseData(data);
  if (!data.stream_id) return state;

  return state.map(message => {
    if (message.stream_id !== data.stream_id) return message;
    return {
      ...responseMessage(response, message, true),
      _streaming: false,
    };
  });
}

function finalResponses(finalResponse) {
  const response = responseData(finalResponse);
  if (Array.isArray(response)) return response;
  if (Array.isArray(response?.responses)) return response.responses;
  return response && typeof response === 'object' ? [response] : [];
}

function responseId(response) {
  return response.message_id ?? response.assistant_message_id;
}

function responseCharacterId(response) {
  return response.charId ?? response.character_id;
}

export function reconcileTurn(state, finalResponse) {
  const responses = finalResponses(finalResponse);
  if (!responses.length) return state;

  const finalIds = new Set(
    responses
      .map(responseId)
      .filter(id => id != null)
      .map(String),
  );
  const workingState = state.filter(message => (
    message.stream_id != null
    || message.message_id == null
    || !finalIds.has(String(message.message_id))
  ));
  const placeholderIndexes = workingState
    .map((message, index) => (message.stream_id != null ? index : -1))
    .filter(index => index >= 0);
  const matchedPlaceholders = new Set();
  const responseByIndex = new Map();
  const unmatchedResponses = [];

  responses.forEach(response => {
    const streamId = response.stream_id;
    const charId = responseCharacterId(response);
    let match = placeholderIndexes.find(index => (
      !matchedPlaceholders.has(index)
      && streamId != null
      && workingState[index].stream_id === streamId
    ));
    if (match == null) {
      match = placeholderIndexes.find(index => (
        !matchedPlaceholders.has(index)
        && charId != null
        && workingState[index].charId === charId
      ));
    }
    if (match == null) {
      match = placeholderIndexes.find(index => !matchedPlaceholders.has(index));
    }

    if (match == null) {
      unmatchedResponses.push(response);
      return;
    }
    matchedPlaceholders.add(match);
    responseByIndex.set(match, response);
  });

  const reconciled = [];
  workingState.forEach((message, index) => {
    if (message.stream_id == null) {
      reconciled.push(message);
      return;
    }
    const response = responseByIndex.get(index);
    if (!response) return;
    const finalMessage = responseMessage(response, message);
    delete finalMessage.stream_id;
    delete finalMessage._streaming;
    reconciled.push(finalMessage);
  });
  unmatchedResponses.forEach(response => {
    reconciled.push(responseMessage(response));
  });

  const seenIds = new Set();
  return reconciled.filter(message => {
    if (message.message_id == null) return true;
    const id = String(message.message_id);
    if (seenIds.has(id)) return false;
    seenIds.add(id);
    return true;
  });
}
