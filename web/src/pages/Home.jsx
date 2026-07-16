import { lazy, Suspense, useState, useEffect } from 'react';
import { useUser } from '../context/UserContext';
import LoginModal from '../components/LoginModal';
import UserSettingsModal from '../components/UserSettingsModal';
import PillNav from '../components/PillNav';
import GlitchText from '../components/GlitchText';
import { characterAdmin } from '../api/memoria';
import { Loader2, User } from 'lucide-react';

const FaultyTerminal = lazy(() => import('../components/FaultyTerminal'));
const CharacterBadge = lazy(() => import('../components/CharacterBadge'));
const AddCharacterBadge = lazy(() =>
  import('../components/CharacterBadge').then((module) => ({ default: module.AddCharacterBadge }))
);

function CharacterArchiveLoading({ label = '正在载入角色档案...' }) {
  return (
    <div
      className="flex min-h-[260px] w-full items-center justify-center gap-3 px-4 text-cyber-green/60"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="animate-spin" size={18} />
      <span className="font-mono text-sm">{label}</span>
    </div>
  );
}

export default function Home() {
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { user, loading: userLoading } = useUser();
  const [showLogin, setShowLogin] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    let cancelled = false;

    if (userLoading) {
      setLoading(true);
      return () => { cancelled = true; };
    }

    if (!user) {
      setCharacters([]);
      setError(null);
      setLoading(false);
      return () => { cancelled = true; };
    }

    async function loadCharacters() {
      setLoading(true);
      setError(null);
      try {
        const list = await characterAdmin.list(false);
        if (cancelled) return;
        const enriched = list.map((c) => ({
          character_id: c.character_id,
          name: c.name || c.display_name || c.character_id,
          display_name: c.display_name || c.name,
          avatar_url: c.avatar_url || null,
          gender: null,
          age: null,
          is_active: c.is_active,
        }));
        // 排序：启用的在前，禁用的在后
        enriched.sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0)); // is_active: 1/0 or true/false
        setCharacters(enriched);
      } catch (apiErr) {
        if (cancelled) return;
        console.error('角色列表加载失败:', apiErr.message);
        setError(apiErr.message);
        setCharacters([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadCharacters();
    return () => { cancelled = true; };
  }, [userLoading, user?.user_id]);


  return (
    <div className="relative min-h-dvh bg-cyber-bg overflow-hidden">
      {/* FaultyTerminal 全屏背景 */}
      <div className="fixed inset-0 z-0">
        <Suspense fallback={null}>
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
        </Suspense>
      </div>

      {/* 内容 */}
      <div className="relative z-10 flex flex-col items-center min-h-dvh px-3 sm:px-4 py-8 sm:py-10 pointer-events-none">
        <div className="mt-4 sm:mt-6 mb-2 pointer-events-auto">
          <GlitchText speed={1} enableShadows enableOnHover={false} className="home-title">
            Memoria
          </GlitchText>
        </div>
        <p className="text-cyber-green/40 font-mono text-[11px] mb-8 tracking-[0.24em] sm:tracking-[0.4em] uppercase pointer-events-none select-none text-center">
          Character Archive
        </p>
        <div className="pointer-events-auto pill-nav-inline mb-10 max-w-[calc(100vw-1rem)] overflow-visible px-3 sm:px-6 py-2.5 rounded-full border border-cyber-green/20 bg-[#0d0d14]/60 backdrop-blur-md shadow-[0_0_20px_rgba(167,239,158,0.06),0_0_40px_rgba(167,239,158,0.03)]">
          <div className="flex items-center gap-1">
            {/* User entry button — replaces the M logo's role as auth entry */}
            <button
              onClick={() => user ? setShowSettings(true) : setShowLogin(true)}
              className="w-[40px] h-[40px] sm:w-[36px] sm:h-[36px] rounded-full bg-[#0b0b0c] flex items-center justify-center flex-shrink-0 border border-cyber-green/15 hover:border-cyber-green/40 transition-colors overflow-hidden"
              title={user ? `${user.username}的设置` : '登录 / 注册'}
            >
              {user?.avatar_url ? (
                <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : user ? (
                <span className="text-cyber-green/60 text-[10px] font-bold">{user.username?.charAt(0)?.toUpperCase() || 'U'}</span>
              ) : (
                <User size={14} className="text-cyber-green/40" />
              )}
            </button>
            <PillNav
              items={[
              { label: "对话", href: "/chat" },
              { label: "事件", href: "/events" },
              { label: "图谱", href: "/graph" },
              { label: "知识", href: "/knowledge" },
            ]}
            hoveredPillTextColor="#A7EF9E"
              pillTextColor="#A7EF9E"
            />
          </div>
        </div>


        {loading && <CharacterArchiveLoading />}

        {error && (
          <div className="text-red-400 font-mono text-xs mb-8">错误: {error}</div>
        )}

        {!loading && (
          <Suspense fallback={<CharacterArchiveLoading label="正在准备角色卡片..." />}>
            <div className="flex flex-wrap justify-center gap-5 sm:gap-8 max-w-5xl pointer-events-auto px-1">
              {characters.map((char) => (
                <CharacterBadge
                  key={char.character_id}
                  character={char}
                  isActive={!!char.is_active}
                />
              ))}
              {user && <AddCharacterBadge />}
            </div>
          </Suspense>
        )}

        {!loading && user && characters.length === 0 && (
          <div className="text-[#A7EF9E] font-mono text-sm mt-8 px-4 text-center drop-shadow-[0_0_8px_#A7EF9E]">
            还没有角色，点击 + 卡片开始创建
          </div>
        )}
      </div>

      {/* Modals */}
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
      {showSettings && <UserSettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  );
}
