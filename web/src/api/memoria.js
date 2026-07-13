/**
 * Memoria backend API service layer.
 */
const API_BASE = '/api/v1';

async function request(url, options = {}) {
  const headers = { ...options.headers };
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const token = localStorage.getItem('memoria-token');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_BASE}${url}`, { ...options, credentials: 'include', headers });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ═══════════════════════════════════════════════
// User API
// ═══════════════════════════════════════════════
export const userApi = {
  register(username, password, gender = 'unknown') {
    return request('/user/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, gender }),
    });
  },
  login(username, password) {
    return request('/user/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },
  getMe() {
    return request('/user/me');
  },
  logout() {
    return request('/user/logout', { method: 'POST' });
  },
  updateProfile(username, gender) {
    return request('/user/profile', {
      method: 'PUT',
      body: JSON.stringify({ username, gender }),
    });
  },
  async uploadAvatar(file) {
    const formData = new FormData();
    formData.append('file', file);
    const headers = {};
    const token = localStorage.getItem('memoria-token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`${API_BASE}/user/avatar/upload`, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
  },
  setAvatarUrl(url) {
    return request('/user/avatar/url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  },
  getWorldClock() {
    return request('/user/world-clock');
  },
  updateWorldClock({ timezone, timeScale } = {}) {
    return request('/user/world-clock', {
      method: 'PUT',
      body: JSON.stringify({
        ...(timezone != null ? { timezone } : {}),
        ...(timeScale != null ? { time_scale: timeScale } : {}),
      }),
    });
  },
  syncWorldClock() {
    return request('/user/world-clock/sync', { method: 'POST' });
  },
  getEventInbox(unreadOnly = true, limit = 50) {
    return request(`/user/event-inbox?unread_only=${unreadOnly}&limit=${limit}`);
  },
  markEventRead(inboxId) {
    return request(`/user/event-inbox/${inboxId}/read`, { method: 'POST' });
  },
};

export const characterAdmin = {
  list(onlyActive = false) {
    return request(`/admin/characters?only_active=${onlyActive}`);
  },
  get(characterId) {
    return request(`/admin/characters/${characterId}`);
  },
  create(characterData) {
    return request('/admin/characters', {
      method: 'POST',
      body: JSON.stringify({ character_data: characterData }),
    });
  },
  update(characterId, characterData) {
    return request(`/admin/characters/${characterId}`, {
      method: 'PUT',
      body: JSON.stringify({ character_data: characterData }),
    });
  },
  delete(characterId, permanent = false) {
    return request(`/admin/characters/${characterId}?permanent=${permanent}`, {
      method: 'DELETE',
    });
  },
  activate(characterId) {
    return request(`/admin/characters/${characterId}/activate`, { method: 'POST' });
  },
  async uploadAvatar(characterId, file) {
    const formData = new FormData();
    formData.append('file', file);
    return request(`/admin/characters/${characterId}/avatar/upload`, {
      method: 'POST',
      body: formData,
    });
  },
  setAvatarUrl(characterId, url) {
    return request(`/admin/characters/${characterId}/avatar/url`, {
      method: 'POST', body: JSON.stringify({ url }) });
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
    return request(`/admin/events/${eventId}`);
  },
  create(eventData) {
    return request('/admin/events', {
      method: 'POST',
      body: JSON.stringify(eventData),
    });
  },
  update(eventId, eventData) {
    return request(`/admin/events/${eventId}`, {
      method: 'PUT',
      body: JSON.stringify(eventData),
    });
  },
  delete(eventId) {
    return request(`/admin/events/${eventId}`, { method: 'DELETE' });
  },
  toggle(eventId, active) {
    return request(`/admin/events/${eventId}/toggle?active=${active}`, { method: 'POST' });
  },
  history(eventId, characterId = null, playerId = null, limit = 50) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (playerId) params.set('player_id', playerId);
    params.set('limit', String(limit));
    return request(`/admin/events/${eventId}/history?${params.toString()}`);
  },
  allHistory(characterId = null, playerId = null, limit = 100) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (playerId) params.set('player_id', playerId);
    params.set('limit', String(limit));
    return request(`/admin/events/history/all?${params.toString()}`);
  },
  resetHistory(eventId, characterId, playerId) {
    return request(`/admin/events/${eventId}/history?character_id=${characterId}&player_id=${playerId}`, { method: 'DELETE' });
  },
  simulate(eventId, data) {
    return request(`/admin/events/${encodeURIComponent(eventId)}/simulate`, {
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
      `/admin/event-schedules/${encodeURIComponent(eventId)}/${encodeURIComponent(characterId)}/pause`,
      { method: 'POST' }
    );
  },
  resumeSchedule(eventId, characterId) {
    return request(
      `/admin/event-schedules/${encodeURIComponent(eventId)}/${encodeURIComponent(characterId)}/resume`,
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
      `/admin/events/${encodeURIComponent(eventId)}/executions?limit=${encodeURIComponent(limit)}`
    );
  },
};

export const relationshipAdmin = {
  /** 获取关系网络（力导引图数据） */
  network(characterIds = null) {
    const params = characterIds ? `?character_ids=${characterIds}` : '';
    return request(`/relationships/network${params}`);
  },
  /** 获取指定角色的所有关系 */
  listForCharacter(characterId) {
    return request(`/relationships/character/${characterId}`);
  },
  /** 获取两个角色之间的关系 */
  get(charIdA, charIdB) {
    return request(`/relationships/pair/${charIdA}/${charIdB}`);
  },
  /** 创建/更新关系 */
  save(data) {
    return request('/relationships', { method: 'POST', body: JSON.stringify(data) });
  },
  /** 更新关系 */
  update(charIdA, charIdB, data) {
    return request(`/relationships/pair/${charIdA}/${charIdB}`, {
      method: 'PUT', body: JSON.stringify(data) });
  },
  /** 删除关系 */
  remove(charIdA, charIdB) {
    return request(`/relationships/${charIdA}/${charIdB}`, { method: 'DELETE' });
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
    return request(`/knowledge/bases/${knowledgeBaseId}`);
  },
  updateBase(knowledgeBaseId, data) {
    return request(`/knowledge/bases/${knowledgeBaseId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },
  setEnabled(knowledgeBaseId, isEnabled) {
    return request(`/knowledge/bases/${knowledgeBaseId}/enabled`, {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    });
  },
  deleteBase(knowledgeBaseId) {
    return request(`/knowledge/bases/${knowledgeBaseId}`, { method: 'DELETE' });
  },
  setBindings(knowledgeBaseId, bindings) {
    return request(`/knowledge/bases/${knowledgeBaseId}/bindings`, {
      method: 'PUT',
      body: JSON.stringify({ bindings }),
    });
  },
  getBindingTargets() {
    return request('/knowledge/binding-targets');
  },
  listDocuments(knowledgeBaseId) {
    return request(`/knowledge/bases/${knowledgeBaseId}/documents`);
  },
  uploadDocument(knowledgeBaseId, file) {
    const formData = new FormData();
    formData.append('file', file);
    return request(`/knowledge/bases/${knowledgeBaseId}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
  },
  pasteDocument(knowledgeBaseId, data) {
    return request(`/knowledge/bases/${knowledgeBaseId}/documents/paste`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteDocument(documentId) {
    return request(`/knowledge/documents/${documentId}`, { method: 'DELETE' });
  },
  retryDocument(documentId) {
    return request(`/knowledge/documents/${documentId}/retry`, { method: 'POST' });
  },
  preview(data) {
    return request('/knowledge/preview', {
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
      body: JSON.stringify({ character_id: characterId, player_id: playerId, player_name: playerName }),
    });
  },
  /** 发送消息并获取回复 */
  sendMessage(sessionId, playerMessage) {
    return request('/dialogue/turn', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, player_message: playerMessage }),
    });
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
    let url = `/dialogue/history?character_id=${characterId}&player_id=${playerId}&offset=${offset}&limit=${limit}`;
    if (excludeSessionId) url += `&exclude_session_id=${encodeURIComponent(excludeSessionId)}`;
    return request(url);
  },
  /** 获取玩家所有会话（单聊 + 群聊） */
  listPlayerSessions(playerId) {
    return request(`/dialogue/sessions/player?player_id=${playerId}`);
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
      }),
    });
  },
  /** 发送群聊消息，后端按语境决定实际回复人数 */
  discussMessage(sessionId, playerMessage, maxResponses = null) {
    const body = {
      session_id: sessionId,
      player_message: playerMessage,
      discussion_mode: true,
    };
    if (maxResponses) body.max_responses = maxResponses;
    return request('/multi-dialogue/turn', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  /** 结束会话 */
  endSession(sessionId) {
    return request('/multi-dialogue/session/end', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },
  continueSession(sessionId) {
    return request(`/multi-dialogue/session/${sessionId}/continue`, { method: 'POST' });
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
    return request(`/multi-dialogue/session/${sessionId}`);
  },
  /** 获取多角色对话历史 */
  getHistory(sessionId, offset = 0, limit = 20) {
    return request(`/multi-dialogue/history/${sessionId}?offset=${offset}&limit=${limit}`);
  },
};
