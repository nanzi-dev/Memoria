import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';

const Home = lazy(() => import('./pages/Home'));
const ChatRoom = lazy(() => import('./pages/ChatRoom'));
const EventList = lazy(() => import('./pages/EventList'));
const EventEditor = lazy(() => import('./pages/EventEditor'));
const CharacterEditor = lazy(() => import('./pages/CharacterEditor'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));

export default function App() {
  return (
    <Suspense fallback={null}>
      <Routes>
        <Route path="/chat" element={<ChatRoom />} />

        <Route path="/" element={<Home />} />
        <Route path="/editor" element={<CharacterEditor />} />
        <Route path="/editor/:characterId" element={<CharacterEditor />} />
        <Route path="/events" element={<EventList />} />
        <Route path="/graph" element={<RelationshipGraph />} />
        <Route path="/events/:eventId" element={<EventEditor />} />
      </Routes>
    </Suspense>
  );
}
