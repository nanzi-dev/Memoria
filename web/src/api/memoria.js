/**
 * Memoria backend API service layer.
 */
const API_BASE = '/api/v1';

async function request(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  const resp = await fetch(`${API_BASE}${url}`, { ...options, headers });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

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
