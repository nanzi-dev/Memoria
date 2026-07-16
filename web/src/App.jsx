import { lazy, Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import { Navigate, Routes, Route } from 'react-router-dom';

import ArchiveRouteLoading from './archive/ArchiveRouteLoading';
import ArchiveShell from './archive/ArchiveShell';
import { ArchiveThemeProvider } from './archive/ArchiveThemeProvider';

const Home = lazy(() => import('./pages/Home'));
const ChatRoom = lazy(() => import('./pages/ChatRoom'));
const EventList = lazy(() => import('./pages/EventList'));
const EventEditor = lazy(() => import('./pages/EventEditor'));
const CharacterEditor = lazy(() => import('./pages/CharacterEditor'));
const PersonaEditor = lazy(() => import('./pages/PersonaEditor'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));
const KnowledgeManager = lazy(() => import('./pages/KnowledgeManager'));

function HomeRouteLoading() {
  return (
    <div
      className="min-h-dvh bg-cyber-bg flex items-center justify-center text-cyber-green"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="animate-spin" size={32} aria-hidden="true" />
      <span className="sr-only">正在加载页面</span>
    </div>
  );
}

function ArchiveLayout() {
  return (
    <ArchiveThemeProvider>
      <ArchiveShell />
    </ArchiveThemeProvider>
  );
}

function archiveRoute(Component) {
  return (
    <Suspense fallback={<ArchiveRouteLoading />}>
      <Component />
    </Suspense>
  );
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={(
          <Suspense fallback={<HomeRouteLoading />}>
            <Home />
          </Suspense>
        )}
      />
      <Route element={<ArchiveLayout />}>
        <Route path="/chat" element={archiveRoute(ChatRoom)} />
        <Route path="/editor" element={archiveRoute(CharacterEditor)} />
        <Route path="/editor/:characterId" element={archiveRoute(CharacterEditor)} />
        <Route path="/persona" element={archiveRoute(PersonaEditor)} />
        <Route path="/events" element={archiveRoute(EventList)} />
        <Route path="/graph" element={archiveRoute(RelationshipGraph)} />
        <Route path="/knowledge" element={archiveRoute(KnowledgeManager)} />
        <Route path="/events/:eventId" element={archiveRoute(EventEditor)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
