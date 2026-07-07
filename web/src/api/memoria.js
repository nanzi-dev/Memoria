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
