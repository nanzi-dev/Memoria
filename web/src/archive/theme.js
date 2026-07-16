export const THEME_STORAGE_KEY = 'memoria-theme';
export const DEFAULT_ARCHIVE_THEME = 'dark';
export const ARCHIVE_THEMES = Object.freeze(['dark', 'light']);

export function isArchiveTheme(value) {
  return ARCHIVE_THEMES.includes(value);
}

export function resolveArchiveTheme(value) {
  return isArchiveTheme(value) ? value : DEFAULT_ARCHIVE_THEME;
}

export function safeGetArchiveStorage(windowLike) {
  try {
    return windowLike?.localStorage || null;
  } catch {
    return null;
  }
}

export function readArchiveTheme(storage) {
  if (!storage) return DEFAULT_ARCHIVE_THEME;
  try {
    return resolveArchiveTheme(storage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_ARCHIVE_THEME;
  }
}

export function persistArchiveTheme(storage, value) {
  const theme = resolveArchiveTheme(value);
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage may be unavailable in privacy modes; the in-memory theme still applies.
  }
  return theme;
}
