import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FaultyTerminal from '../components/FaultyTerminal';
import PillNav from '../components/PillNav';
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
        console.error('后端不可用:', apiErr.message);
        setError('无法连接到后端服务');
        setCharacters([]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
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
      <div className="relative z-10 flex flex-col items-center min-h-screen px-4 py-10 pointer-events-none">
        <div className="mt-6 mb-2 pointer-events-auto">
          <GlitchText speed={1} enableShadows enableOnHover={false} className="home-title">
            Memoria
          </GlitchText>
        </div>
        <p className="text-cyber-green/40 font-mono text-[11px] mb-8 tracking-[0.4em] uppercase pointer-events-none select-none">
          Character Archive
        </p>
        <div className="pointer-events-auto pill-nav-inline mb-10 px-6 py-2.5 rounded-full border border-cyber-green/20 bg-[#0d0d14]/60 backdrop-blur-md shadow-[0_0_20px_rgba(167,239,158,0.06),0_0_40px_rgba(167,239,158,0.03)]">
          <PillNav
            items={[
              { label: "对话", href: "/chat" },
              { label: "事件", href: "/events" },
              { label: "图谱", href: "/graph" },
            ]}
            hoveredPillTextColor="#A7EF9E"
            pillTextColor="#A7EF9E"
          />
        </div>


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
          <div className="flex flex-wrap justify-center gap-8 max-w-5xl pointer-events-auto">
            {characters.map((char) => (
              <CharacterBadge
                key={char.character_id}
                character={char}
    
                isActive={!!char.is_active}
              />
            ))}
            <AddCharacterBadge />
          </div>
        )}

        {!loading && characters.length === 0 && (
          <div className="text-[#A7EF9E] font-mono text-sm mt-8 drop-shadow-[0_0_8px_#A7EF9E]">
            还没有角色，点击 + 卡片开始创建
          </div>
        )}
      </div>
    </div>
  );
}
