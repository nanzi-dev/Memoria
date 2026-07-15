export function createPendingUserMessage(content, worldCreatedAt, clientId) {
  return {
    role: 'user',
    content,
    world_created_at: worldCreatedAt,
    client_id: clientId,
    _pending: true,
  };
}

export function settlePendingMessage(messages, clientId) {
  return messages.map(message => (
    message.client_id === clientId
      ? { ...message, _pending: false }
      : message
  ));
}

export function removePendingMessage(messages, clientId) {
  return messages.filter(message => message.client_id !== clientId);
}

export function canApplySingleHistory(request, current) {
  return request.generation === current.generation
    && request.playerId === current.playerId
    && request.characterId === current.characterId;
}

export function restoreFailedDraft(currentDraft, failedText) {
  const current = String(currentDraft || '').trim();
  const failed = String(failedText || '').trim();
  if (!failed || current === failed) return current;
  if (!current) return failed;
  return `${failed}\n${current}`;
}
