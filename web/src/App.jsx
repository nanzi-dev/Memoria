import { Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import ChatRoom from './pages/ChatRoom';
import EventList from './pages/EventList';
import EventEditor from './pages/EventEditor';
import CharacterEditor from './pages/CharacterEditor';
import RelationshipGraph from './pages/RelationshipGraph';

export default function App() {
  return (
    <Routes>
      <Route path="/chat" element={<ChatRoom />} />
      
      <Route path="/" element={<Home />} />
      <Route path="/editor" element={<CharacterEditor />} />
      <Route path="/editor/:characterId" element={<CharacterEditor />} />
      <Route path="/events" element={<EventList />} />
      <Route path="/graph" element={<RelationshipGraph />} />
      <Route path="/events/:eventId" element={<EventEditor />} />
    </Routes>
  );
}
