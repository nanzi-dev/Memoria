import { Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import CharacterEditor from './pages/CharacterEditor';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/editor" element={<CharacterEditor />} />
      <Route path="/editor/:characterId" element={<CharacterEditor />} />
    </Routes>
  );
}
