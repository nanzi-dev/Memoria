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
};

export const system = {
  health() { return fetch('/health').then(r => r.json()); },
  ready() { return fetch('/ready').then(r => r.json()); },
};
