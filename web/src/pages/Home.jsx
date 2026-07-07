import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FaultyTerminal from '../components/FaultyTerminal';
import GlitchText from '../components/GlitchText';
import CharacterBadge, { AddCharacterBadge } from '../components/CharacterBadge';
import { characterAdmin } from '../api/memoria';
import { Loader2 } from 'lucide-react';

export default function Home() {
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => { loadCharacters(); }, []);

  async function loadCharacters() {
    try {
      setLoading(true);
      try {
        const list = await characterAdmin.list(false);
        // 串行获取详情，避免并发触发 429
        const enriched = [];
        for (const c of list) {
          try {
            const detail = await characterAdmin.get(c.character_id);
            const d = detail.card_data || {};
            enriched.push({
              character_id: c.character_id,
              name: c.name || c.display_name || c.character_id,
              display_name: c.display_name || c.name,
              avatar_url: detail.avatar_url || d.avatar_url || null,
              gender: d.identity?.gender || null,
              age: d.identity?.age || null,
              is_active: c.is_active,
            });
          } catch {
            enriched.push({
              character_id: c.character_id,
              name: c.name || c.display_name || c.character_id,
              display_name: c.display_name || c.name,
              avatar_url: null,
              gender: null,
              age: null,
              is_active: c.is_active,
            });
          }
        }
                // 排序：启用的在前，禁用的在后
        enriched.sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0)); // is_active: 1/0 or true/false
        setCharacters(enriched);
      } catch (apiErr) {
        console.warn('后端不可用，使用 localStorage 回退:', apiErr.message);
        const stored = localStorage.getItem('memoria-characters');
        if (stored) {
          const raw = JSON.parse(stored);
          setCharacters(raw.map(c => ({
            character_id: c.character_id,
            name: c.meta?.name || c.name || c.character_id,
            display_name: c.meta?.display_name || c.display_name || c.name,
            avatar_url: c.avatar_url || null,
            gender: c.identity?.gender || null,
            age: c.identity?.age || null,
          })));
        } else {
          setCharacters([]);
        }
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleBadgeClick(character) {
    navigate(`/editor/${character.character_id}`);
  }

  return (
    <div className="relative min-h-screen bg-cyber-bg overflow-hidden">
      {/* FaultyTerminal 全屏背景 */}
      <div className="fixed inset-0 z-0">
        <FaultyTerminal
          scale={1.5}
          gridMul={[2, 1]}
          digitSize={1.2}
          timeScale={0.5}
          pause={false}
          scanlineIntensity={0.5}
          glitchAmount={1}
          flickerAmount={1}
          noiseAmp={1}
          chromaticAberration={0}
          dither={0}
          curvature={0.1}
          tint="#A7EF9E"
          mouseReact
          mouseStrength={0.5}
          pageLoadAnimation
          brightness={0.6}
        />
      </div>

      {/* 内容 */}
      <div className="relative z-10 flex flex-col items-center min-h-screen px-4 py-10" style={{ pointerEvents: 'none' }}>
        <div className="mt-6 mb-3">
          <GlitchText speed={1} enableShadows enableOnHover={false} className="home-title">
            Memoria
          </GlitchText>
        </div>

        <p className="text-cyber-green/50 font-mono text-xs mb-10 tracking-[0.3em] uppercase">
          Character Archive
        </p>

        {loading && (
          <div className="flex items-center gap-3 text-cyber-green/50">
            <Loader2 className="animate-spin" size={18} />
            <span className="font-mono text-sm">加载中...</span>
          </div>
        )}

        {error && (
          <div className="text-red-400 font-mono text-xs mb-8">错误: {error}</div>
        )}

        {!loading && (
          <div className="flex flex-wrap justify-center gap-8 max-w-5xl">
            {characters.map((char) => (
              <CharacterBadge
                key={char.character_id}
                character={char}
                onClick={handleBadgeClick}
                isActive={!!char.is_active}
              />
            ))}
            <AddCharacterBadge />
          </div>
        )}

        {!loading && characters.length === 0 && (
          <div className="text-cyber-green/30 font-mono text-sm mt-8">
            还没有角色，点击 + 卡片开始创建
          </div>
        )}
      </div>
    </div>
  );
}
