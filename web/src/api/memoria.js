/**
 * Memoria backend API service layer.
 */
const API_BASE = '/api/v1';

function pathSegment(value) {
  return encodeURIComponent(String(value));
}

function formatApiError(errorBody, status) {
  const detail = errorBody?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail.message === 'string' && detail.message.trim()) {
    return detail.message;
  }
  if (Array.isArray(detail)) {
    const validationMessages = detail.map(item => {
      if (typeof item === 'string') return item;
      const location = Array.isArray(item?.loc)
        ? item.loc.filter(part => part !== 'body').join('.')
        : '';
      const message = item?.msg || item?.message;
      if (!message) return null;
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (validationMessages.length) return validationMessages.join('; ');
  }
  if (typeof errorBody?.message === 'string' && errorBody.message.trim()) {
    return errorBody.message;
  }
  return `HTTP ${status}`;
}

async function throwResponseError(resp) {
  const errorBody = await resp.json().catch(() => ({}));
  const error = new Error(formatApiError(errorBody, resp.status));
  error.status = resp.status;
  error.body = errorBody;
  throw error;
}

async function request(url, options = {}) {
  const headers = { ...options.headers };
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const resp = await fetch(`${API_BASE}${url}`, {
    ...options,
    credentials: 'include',
    headers,
  });
  if (!resp.ok) await throwResponseError(resp);
  return resp.json();
}

function parseSseFrame(frame) {
  let type = 'message';
  const dataLines = [];

  frame.split(/\r\n|\r|\n/).forEach(line => {
    if (!line || line.startsWith(':')) return;
    const separator = line.indexOf(':');
    const field = separator < 0 ? line : line.slice(0, separator);
    let value = separator < 0 ? '' : line.slice(separator + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') type = value || 'message';
    if (field === 'data') dataLines.push(value);
  });

  if (!dataLines.length) return null;
  return {
    type,
    data: JSON.parse(dataLines.join('\n')),
  };
}

function streamEventError(data) {
  const message = data?.message
    || data?.detail
    || data?.error
    || data?.error_type
    || 'Stream request failed';
  const error = new Error(message);
  error.body = data;
  return error;
}

async function requestStream(url, options = {}, onEvent = undefined) {
  const headers = { ...options.headers };
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const resp = await fetch(`${API_BASE}${url}`, {
    ...options,
    credentials: 'include',
    headers,
  });
  if (!resp.ok) await throwResponseError(resp);
  if (!resp.body?.getReader) throw new Error('Streaming response body is unavailable');

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let terminalResponse;
  let terminalReceived = false;

  const dispatchFrame = frame => {
    const event = parseSseFrame(frame);
    if (!event) return;
    onEvent?.(event);
    if (event.type === 'error') throw streamEventError(event.data);
    if (event.type === 'turn_completed') {
      terminalReceived = true;
      terminalResponse = event.data?.response ?? event.data;
    }
  };

  const drainFrames = () => {
    while (true) {
      const separator = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      if (!separator) return;
      const frame = buffer.slice(0, separator.index);
      buffer = buffer.slice(separator.index + separator[0].length);
      dispatchFrame(frame);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drainFrames();
    }
    buffer += decoder.decode();
    drainFrames();
    if (buffer.trim()) dispatchFrame(buffer);
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }

  if (!terminalReceived) throw new Error('Streaming response ended before turn completion');
  return terminalResponse;
}

async function requestBlob(url, options = {}) {
  const resp = await fetch(`${API_BASE}${url}`, {
    ...options,
    credentials: 'include',
    headers: { ...options.headers },
  });
  if (!resp.ok) await throwResponseError(resp);
  return resp.blob();
}

// ═══════════════════════════════════════════════
// User API
// ═══════════════════════════════════════════════
export const userApi = {
  register(username, password, gender = 'unknown', options = {}) {
    return request('/user/register', {
      ...options,
      method: 'POST',
      body: JSON.stringify({ username, password, gender }),
    });
  },
  login(username, password, options = {}) {
    return request('/user/login', {
      ...options,
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },
  getMe(options = {}) {
    return request('/user/me', options);
  },
  logout(options = {}) {
    return request('/user/logout', { ...options, method: 'POST' });
  },
  updateProfile(username, gender) {
    return request('/user/profile', {
      method: 'PUT',
      body: JSON.stringify({ username, gender }),
    });
  },
  updateSpeechSettings(ttsAutoPlay, sttAutoSend) {
    return request('/user/speech-settings', {
      method: 'PUT',
      body: JSON.stringify({
        tts_auto_play: ttsAutoPlay,
        stt_auto_send: sttAutoSend,
      }),
    });
  },
  async uploadAvatar(file) {
    const formData = new FormData();
    formData.append('file', file);
    return request('/user/avatar/upload', {
      method: 'POST',
      body: formData,
    });
  },
  setAvatarUrl(url) {
    return request('/user/avatar/url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  },
  getCharacterCard() {
    return request('/user/character-card');
  },
  updateCharacterCard(data) {
    return request('/user/character-card', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },
  async uploadCharacterCardAvatar(file) {
    const formData = new FormData();
    formData.append('file', file);
    return request('/user/character-card/avatar/upload', {
      method: 'POST',
      body: formData,
    });
  },
  setCharacterCardAvatarUrl(url) {
    return request('/user/character-card/avatar/url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  },
  getWorldClock() {
    return request('/user/world-clock');
  },
  updateWorldClock({ expectedRevision, timezone, timezoneMode, timeScale } = {}) {
    return request('/user/world-clock', {
      method: 'PUT',
      body: JSON.stringify({
        expected_revision: expectedRevision,
        ...(timezone != null ? { timezone } : {}),
        ...(timezoneMode != null ? { timezone_mode: timezoneMode } : {}),
        ...(timeScale != null ? { time_scale: timeScale } : {}),
      }),
    });
  },
  syncWorldClock(expectedRevision) {
    return request('/user/world-clock/sync', {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
  },
  setWorldClock(worldNow, expectedRevision) {
    return request('/user/world-clock/set', {
      method: 'POST',
      body: JSON.stringify({ world_now: worldNow, expected_revision: expectedRevision }),
    });
  },
  advanceWorldClock(seconds, expectedRevision) {
    return request('/user/world-clock/advance', {
      method: 'POST',
      body: JSON.stringify({ seconds, expected_revision: expectedRevision }),
    });
  },
  getEventInbox(unreadOnly = true, limit = 50) {
    return request(`/user/event-inbox?unread_only=${unreadOnly}&limit=${limit}`);
  },
  markEventRead(inboxId) {
    return request(`/user/event-inbox/${pathSegment(inboxId)}/read`, { method: 'POST' });
  },
};

export const characterAdmin = {
  list(onlyActive = false) {
    return request(`/admin/characters?only_active=${onlyActive}`);
  },
  get(characterId) {
    return request(`/admin/characters/${pathSegment(characterId)}`);
  },
  create(characterData) {
    return request('/admin/characters', {
      method: 'POST',
      body: JSON.stringify({ character_data: characterData }),
    });
  },
  update(characterId, characterData) {
    return request(`/admin/characters/${pathSegment(characterId)}`, {
      method: 'PUT',
      body: JSON.stringify({ character_data: characterData }),
    });
  },
  delete(characterId, permanent = false) {
    return request(`/admin/characters/${pathSegment(characterId)}?permanent=${permanent}`, {
      method: 'DELETE',
    });
  },
  activate(characterId) {
    return request(`/admin/characters/${pathSegment(characterId)}/activate`, { method: 'POST' });
  },
  async uploadAvatar(characterId, file) {
    const formData = new FormData();
    formData.append('file', file);
    return request(`/admin/characters/${pathSegment(characterId)}/avatar/upload`, {
      method: 'POST',
      body: formData,
    });
  },
  setAvatarUrl(characterId, url) {
    return request(`/admin/characters/${pathSegment(characterId)}/avatar/url`, {
      method: 'POST', body: JSON.stringify({ url }) });
  },
  getVoiceStatus(characterId) {
    return request(`/admin/characters/${pathSegment(characterId)}/voice`);
  },
  uploadVoiceConsent(characterId, locale, recording, name = null) {
    const formData = new FormData();
    formData.append('locale', locale);
    formData.append('recording', recording);
    if (name?.trim()) formData.append('name', name.trim());
    return request(`/admin/characters/${pathSegment(characterId)}/voice/consent`, {
      method: 'POST',
      body: formData,
    });
  },
  createCustomVoice(characterId, audioSample, referenceTranscript, name = null) {
    const formData = new FormData();
    formData.append('audio_sample', audioSample);
    formData.append('reference_transcript', referenceTranscript);
    if (name?.trim()) formData.append('name', name.trim());
    return request(`/admin/characters/${pathSegment(characterId)}/voice`, {
      method: 'POST',
      body: formData,
    });
  },
  unbindCustomVoice(characterId) {
    return request(`/admin/characters/${pathSegment(characterId)}/voice`, { method: 'DELETE' });
  },
};

export const eventAdmin = {
  list(characterId = null, onlyActive = false) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (onlyActive) params.set('only_active', 'true');
    const qs = params.toString();
    return request(`/admin/events${qs ? '?' + qs : ''}`);
  },
  templates(category = null) {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    const qs = params.toString();
    return request(`/admin/event-templates${qs ? '?' + qs : ''}`);
  },
  get(eventId) {
    return request(`/admin/events/${pathSegment(eventId)}`);
  },
  create(eventData) {
    return request('/admin/events', {
      method: 'POST',
      body: JSON.stringify(eventData),
    });
  },
  update(eventId, eventData) {
    return request(`/admin/events/${pathSegment(eventId)}`, {
      method: 'PUT',
      body: JSON.stringify(eventData),
    });
  },
  delete(eventId) {
    return request(`/admin/events/${pathSegment(eventId)}`, { method: 'DELETE' });
  },
  toggle(eventId, active) {
    return request(`/admin/events/${pathSegment(eventId)}/toggle?active=${active}`, { method: 'POST' });
  },
  history(eventId, characterId = null, playerId = null, limit = 50) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (playerId) params.set('player_id', playerId);
    params.set('limit', String(limit));
    return request(`/admin/events/${pathSegment(eventId)}/history?${params.toString()}`);
  },
  allHistory(characterId = null, playerId = null, limit = 100) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (playerId) params.set('player_id', playerId);
    params.set('limit', String(limit));
    return request(`/admin/events/history/all?${params.toString()}`);
  },
  resetHistory(eventId, characterId, playerId) {
    const params = new URLSearchParams({
      character_id: characterId,
      player_id: playerId,
    });
    return request(`/admin/events/${pathSegment(eventId)}/history?${params.toString()}`, {
      method: 'DELETE',
    });
  },
  simulate(eventId, data) {
    return request(`/admin/events/${pathSegment(eventId)}/simulate`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  schedules(eventId = null, status = null) {
    const params = new URLSearchParams();
    if (eventId) params.set('event_id', eventId);
    if (status) params.set('status', status);
    const qs = params.toString();
    return request(`/admin/event-schedules${qs ? '?' + qs : ''}`);
  },
  pauseSchedule(eventId, characterId) {
    return request(
      `/admin/event-schedules/${pathSegment(eventId)}/${pathSegment(characterId)}/pause`,
      { method: 'POST' }
    );
  },
  resumeSchedule(eventId, characterId) {
    return request(
      `/admin/event-schedules/${pathSegment(eventId)}/${pathSegment(characterId)}/resume`,
      { method: 'POST' }
    );
  },
  metrics(eventId = null) {
    const params = new URLSearchParams();
    if (eventId) params.set('event_id', eventId);
    const qs = params.toString();
    return request(`/admin/event-metrics${qs ? '?' + qs : ''}`);
  },
  executions(eventId, limit = 100) {
    return request(
      `/admin/events/${pathSegment(eventId)}/executions?limit=${encodeURIComponent(limit)}`
    );
  },
};

export const relationshipAdmin = {
  /** 获取关系网络（力导引图数据） */
  network(characterIds = null) {
    const params = new URLSearchParams();
    if (characterIds) params.set('character_ids', characterIds);
    const query = params.toString();
    return request(`/relationships/network${query ? `?${query}` : ''}`);
  },
  /** 获取指定角色的所有关系 */
  listForCharacter(characterId) {
    return request(`/relationships/character/${pathSegment(characterId)}`);
  },
  /** 获取两个角色之间的关系 */
  get(charIdA, charIdB) {
    return request(`/relationships/pair/${pathSegment(charIdA)}/${pathSegment(charIdB)}`);
  },
  /** 创建/更新关系 */
  save(data) {
    return request('/relationships', { method: 'POST', body: JSON.stringify(data) });
  },
  /** 更新关系 */
  update(charIdA, charIdB, data) {
    return request(`/relationships/pair/${pathSegment(charIdA)}/${pathSegment(charIdB)}`, {
      method: 'PUT', body: JSON.stringify(data) });
  },
  /** 删除关系 */
  remove(charIdA, charIdB) {
    return request(`/relationships/${pathSegment(charIdA)}/${pathSegment(charIdB)}`, {
      method: 'DELETE',
    });
  },
};

// ═══════════════════════════════════════════════
// Knowledge Base API
// ═══════════════════════════════════════════════
export const knowledgeApi = {
  listBases() {
    return request('/knowledge/bases');
  },
  createBase(data) {
    return request('/knowledge/bases', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  getBase(knowledgeBaseId) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}`);
  },
  updateBase(knowledgeBaseId, data) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },
  setEnabled(knowledgeBaseId, isEnabled) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}/enabled`, {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    });
  },
  deleteBase(knowledgeBaseId) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}`, { method: 'DELETE' });
  },
  setBindings(knowledgeBaseId, bindings) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}/bindings`, {
      method: 'PUT',
      body: JSON.stringify({ bindings }),
    });
  },
  getBindingTargets() {
    return request('/knowledge/binding-targets');
  },
  listDocuments(knowledgeBaseId) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}/documents`);
  },
  uploadDocument(knowledgeBaseId, file) {
    const formData = new FormData();
    formData.append('file', file);
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
  },
  pasteDocument(knowledgeBaseId, data) {
    return request(`/knowledge/bases/${pathSegment(knowledgeBaseId)}/documents/paste`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteDocument(documentId) {
    return request(`/knowledge/documents/${pathSegment(documentId)}`, { method: 'DELETE' });
  },
  retryDocument(documentId) {
    return request(`/knowledge/documents/${pathSegment(documentId)}/retry`, { method: 'POST' });
  },
  preview(data, options = {}) {
    return request('/knowledge/preview', {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

// ═══════════════════════════════════════════════
// Dialogue API
// ═══════════════════════════════════════════════
export const dialogue = {
  /** 开始单角色对话会话 */
  startSession(characterId, playerId, playerName = '旅行者') {
    return request('/dialogue/session/start', {
      method: 'POST',
      body: JSON.stringify({
        character_id: characterId,
        player_id: playerId,
        player_name: playerName,
        locale: 'zh-CN',
      }),
    });
  },
  /** 发送消息并获取回复 */
  sendMessage(sessionId, playerMessage, requestId) {
    return request('/dialogue/turn', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        player_message: playerMessage,
        request_id: requestId,
      }),
    });
  },
  /** 流式发送消息，并逐帧接收回复 */
  streamMessage(sessionId, playerMessage, requestId, onEvent, options = {}) {
    return requestStream('/dialogue/turn/stream', {
      ...options,
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        player_message: playerMessage,
        request_id: requestId,
      }),
    }, onEvent);
  },
  /** 结束会话 */
  endSession(sessionId) {
    return request('/dialogue/session/end', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },
  endSessionOnUnload(sessionId) {
    if (!sessionId) return;
    const body = JSON.stringify({ session_id: sessionId });
    const url = `${API_BASE}/dialogue/session/end`;
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' });
      navigator.sendBeacon(url, blob);
      return;
    }
    fetch(url, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      keepalive: true,
    }).catch(() => {});
  },
  /** 获取会话历史 */
  getHistory(characterId, playerId, offset = 0, limit = 20, excludeSessionId = null) {
    const params = new URLSearchParams({
      character_id: characterId,
      player_id: playerId,
      offset: String(offset),
      limit: String(limit),
    });
    if (excludeSessionId) params.set('exclude_session_id', excludeSessionId);
    return request(`/dialogue/history?${params.toString()}`);
  },
  /** 获取玩家所有会话（单聊 + 群聊） */
  listPlayerSessions(playerId) {
    const params = new URLSearchParams({ player_id: playerId });
    return request(`/dialogue/sessions/player?${params.toString()}`);
  },
};

// ═══════════════════════════════════════════════
// Multi-Dialogue API
// ═══════════════════════════════════════════════
export const multiDialogue = {
  /** 开始多角色群聊 */
  startSession(playerId, playerName, characterIds, groupName = null) {
    return request('/multi-dialogue/session/start', {
      method: 'POST',
      body: JSON.stringify({
        player_id: playerId,
        player_name: playerName,
        group_name: groupName,
        character_ids: characterIds,
        locale: 'zh-CN',
      }),
    });
  },
  /** 发送群聊消息，后端按语境决定实际回复人数 */
  discussMessage(sessionId, playerMessage, maxResponses = null, requestId = null) {
    const body = {
      session_id: sessionId,
      player_message: playerMessage,
      discussion_mode: true,
      request_id: requestId,
    };
    if (maxResponses) body.max_responses = maxResponses;
    return request('/multi-dialogue/turn', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  /** 流式发送群聊消息，后端按语境决定实际回复人数 */
  streamDiscussMessage(
    sessionId,
    playerMessage,
    maxResponses = null,
    requestId = null,
    onEvent,
    options = {},
  ) {
    const body = {
      session_id: sessionId,
      player_message: playerMessage,
      discussion_mode: true,
      request_id: requestId,
    };
    if (maxResponses) body.max_responses = maxResponses;
    return requestStream('/multi-dialogue/turn/stream', {
      ...options,
      method: 'POST',
      body: JSON.stringify(body),
    }, onEvent);
  },
  /** 结束会话 */
  endSession(sessionId) {
    return request('/multi-dialogue/session/end', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },
  continueSession(sessionId) {
    return request(`/multi-dialogue/session/${pathSegment(sessionId)}/continue`, { method: 'POST' });
  },
  endSessionOnUnload(sessionId) {
    if (!sessionId) return;
    const body = JSON.stringify({ session_id: sessionId });
    const url = `${API_BASE}/multi-dialogue/session/end`;
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' });
      navigator.sendBeacon(url, blob);
      return;
    }
    fetch(url, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      keepalive: true,
    }).catch(() => {});
  },
  /** 获取多角色会话信息 */
  getSessionInfo(sessionId) {
    return request(`/multi-dialogue/session/${pathSegment(sessionId)}`);
  },
  /** 获取多角色对话历史 */
  getHistory(sessionId, offset = 0, limit = 20, afterMessageId = null) {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (afterMessageId != null) params.set('after_message_id', String(afterMessageId));
    return request(`/multi-dialogue/history/${pathSegment(sessionId)}?${params.toString()}`);
  },
  /** 清除逻辑群聊线程的聚合未读通知 */
  markThreadRead(groupThreadId) {
    return request(`/multi-dialogue/thread/${pathSegment(groupThreadId)}/read`, {
      method: 'POST',
    });
  },
};

// ═══════════════════════════════════════════════
// Speech API
// ═══════════════════════════════════════════════
export const speechApi = {
  getConfiguration() {
    return request('/speech/configuration');
  },
  transcribe(sessionId, mode, file, signal = undefined) {
    const formData = new FormData();
    formData.append('session_id', sessionId);
    formData.append('mode', mode);
    formData.append('file', file);
    return request('/speech/transcriptions', {
      method: 'POST',
      body: formData,
      signal,
    });
  },
  getMessageAudio(mode, sessionId, messageId, signal = undefined) {
    const routeMode = mode === 'group' ? 'group' : 'single';
    return requestBlob(
      `/speech/${routeMode}/sessions/${pathSegment(sessionId)}/messages/${pathSegment(messageId)}/audio`,
      { signal },
    );
  },
};
