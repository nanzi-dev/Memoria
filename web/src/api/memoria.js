/**
 * Memoria backend API service layer.
 */
const API_BASE = '/api/v1';

async function request(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  const token = localStorage.getItem('memoria-token');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_BASE}${url}`, { ...options, headers });
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
  // 头像
  getAvatar(characterId) {
    return request(`/admin/characters/${characterId}/avatar`);
  },
  async uploadAvatar(characterId, file) {
    const formData = new FormData();
    formData.append('file', file);
    const resp = await fetch(`${API_BASE}/admin/characters/${characterId}/avatar/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
  },
  setAvatarUrl(characterId, url) {
    return request(`/admin/characters/${characterId}/avatar/url`, {
      method: 'POST', body: JSON.stringify({ url }) });
  },
};

export const system = {
  health() { return fetch('/health').then(r => r.json()); },
  ready() { return fetch('/ready').then(r => r.json()); },
};

export const eventAdmin = {
  list(characterId = null, onlyActive = false) {
    const params = new URLSearchParams();
    if (characterId) params.set('character_id', characterId);
    if (onlyActive) params.set('only_active', 'true');
    const qs = params.toString();
    return request(`/admin/events${qs ? '?' + qs : ''}`);
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
// Dialogue API
// ═══════════════════════════════════════════════
export const dialogue = {
  /** 获取可用角色列表 */
  listCharacters() {
    return request('/characters');
  },
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
  latestSession(playerId, characterId = null) {
    const params = `player_id=${playerId}` + (characterId ? `&character_id=${characterId}` : '');
    return request(`/dialogue/session/latest?${params}`);
  },
  /** 获取会话历史 */
  getHistory(characterId, playerId, offset = 0, limit = 20, excludeSessionId = null) {
    let url = `/dialogue/history?character_id=${characterId}&player_id=${playerId}&offset=${offset}&limit=${limit}`;
    if (excludeSessionId) url += `&exclude_session_id=${encodeURIComponent(excludeSessionId)}`;
    return request(url);
  },
  /** 获取会话列表 */
  listSessions(characterId, playerId) {
    return request(`/dialogue/sessions?character_id=${characterId}&player_id=${playerId}`);
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
  startSession(playerId, playerName, characterIds, strategyType = 'hybrid', speakFrequencies = null) {
    return request('/multi-dialogue/session/start', {
      method: 'POST',
      body: JSON.stringify({
        player_id: playerId,
        player_name: playerName,
        character_ids: characterIds,
        strategy_type: strategyType,
        speak_frequencies: speakFrequencies,
      }),
    });
  },
  /** 发送消息（单角色回复模式） */
  sendMessage(sessionId, playerMessage, strategyType = 'hybrid') {
    return request('/multi-dialogue/turn', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        player_message: playerMessage,
        strategy_type: strategyType,
        discussion_mode: false,
      }),
    });
  },
  /** 讨论模式发送消息 */
  discussMessage(sessionId, playerMessage, maxResponses = 3, strategyType = 'hybrid') {
    return request('/multi-dialogue/turn', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        player_message: playerMessage,
        strategy_type: strategyType,
        discussion_mode: true,
        max_responses: maxResponses,
      }),
    });
  },
  /** 结束会话 */
  endSession(sessionId) {
    return request('/dialogue/session/end', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },
  latestSession(playerId, characterId = null) {
    const params = `player_id=${playerId}` + (characterId ? `&character_id=${characterId}` : '');
    return request(`/dialogue/session/latest?${params}`);
  },
  /** 获取多角色会话信息 */
  getSessionInfo(sessionId) {
    return request(`/multi-dialogue/session/${sessionId}`);
  },
  /** 触发角色互动 */
  triggerInteraction(sessionId, triggerCharacterId = null) {
    return request('/multi-dialogue/interaction/trigger', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, trigger_character_id: triggerCharacterId }),
    });
  },
  /** 获取多角色对话历史 */
  getHistory(sessionId, limit = 50) {
    return request(`/multi-dialogue/history/${sessionId}?limit=${limit}`);
  },
  /** 添加参与者 */
  addParticipant(sessionId, characterId, speakFrequency = 1.0) {
    return request('/multi-dialogue/participant/add', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, character_id: characterId, speak_frequency: speakFrequency }),
    });
  },
  /** 移除参与者 */
  removeParticipant(sessionId, characterId) {
    return request('/multi-dialogue/participant/remove', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, character_id: characterId }),
    });
  },
  /** 更新参与者配置 */
  updateParticipant(sessionId, characterId, data) {
    return request('/multi-dialogue/participant/update', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, character_id: characterId, ...data }),
    });
  },
};
