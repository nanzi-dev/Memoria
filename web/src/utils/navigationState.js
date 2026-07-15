function encodedPathSegment(value) {
  return encodeURIComponent(String(value));
}

export function characterEditorPath(characterId) {
  return `/editor/${encodedPathSegment(characterId)}`;
}

export function eventEditorPath(eventId) {
  return `/events/${encodedPathSegment(eventId)}`;
}

export function isActivationKey(key) {
  return key === 'Enter' || key === ' ';
}
