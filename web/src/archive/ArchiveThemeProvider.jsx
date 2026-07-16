import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import {
  persistArchiveTheme,
  readArchiveTheme,
  resolveArchiveTheme,
  safeGetArchiveStorage,
} from './theme';

const ArchiveThemeContext = createContext(null);

export function ArchiveThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => (
    readArchiveTheme(safeGetArchiveStorage(
      typeof window === 'undefined' ? null : window,
    ))
  ));

  const setTheme = useCallback((nextTheme) => {
    setThemeState((currentTheme) => {
      const resolved = resolveArchiveTheme(
        typeof nextTheme === 'function' ? nextTheme(currentTheme) : nextTheme,
      );
      return persistArchiveTheme(
        safeGetArchiveStorage(typeof window === 'undefined' ? null : window),
        resolved,
      );
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(currentTheme => (currentTheme === 'dark' ? 'light' : 'dark'));
  }, [setTheme]);

  useEffect(() => {
    document.body.dataset.archiveTheme = theme;
    return () => {
      if (document.body.dataset.archiveTheme === theme) {
        delete document.body.dataset.archiveTheme;
      }
    };
  }, [theme]);

  useEffect(() => {
    const handleStorage = (event) => {
      if (event.key !== 'memoria-theme') return;
      setThemeState(resolveArchiveTheme(event.newValue));
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const value = useMemo(() => ({
    theme,
    setTheme,
    toggleTheme,
  }), [setTheme, theme, toggleTheme]);

  return (
    <ArchiveThemeContext.Provider value={value}>
      {children}
    </ArchiveThemeContext.Provider>
  );
}

export function useArchiveTheme() {
  const context = useContext(ArchiveThemeContext);
  if (!context) {
    throw new Error('useArchiveTheme must be used within ArchiveThemeProvider');
  }
  return context;
}
