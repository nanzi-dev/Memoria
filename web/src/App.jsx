import { lazy, Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import { Navigate, Routes, Route } from 'react-router-dom';

const Home = lazy(() => import('./pages/Home'));
const ChatRoom = lazy(() => import('./pages/ChatRoom'));
const EventList = lazy(() => import('./pages/EventList'));
const EventEditor = lazy(() => import('./pages/EventEditor'));
const CharacterEditor = lazy(() => import('./pages/CharacterEditor'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));
const KnowledgeManager = lazy(() => import('./pages/KnowledgeManager'));

function RouteLoading() {
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

export default function App() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/chat" element={<ChatRoom />} />

        <Route path="/" element={<Home />} />
        <Route path="/editor" element={<CharacterEditor />} />
        <Route path="/editor/:characterId" element={<CharacterEditor />} />
        <Route path="/events" element={<EventList />} />
        <Route path="/graph" element={<RelationshipGraph />} />
        <Route path="/knowledge" element={<KnowledgeManager />} />
        <Route path="/events/:eventId" element={<EventEditor />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
