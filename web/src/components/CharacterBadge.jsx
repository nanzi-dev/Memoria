import { useNavigate } from 'react-router-dom';
import { useMemo } from 'react';
import Lanyard from './Lanyard';

export default function CharacterBadge({ character, onClick }) {
  const navigate = useNavigate();

  const characterInfo = useMemo(() => ({
    avatarUrl: character.avatar_url || null,
    name: character.name || character.display_name || character.character_id,
    gender: character.gender || null,
  }), [character]);

  const handleClick = () => {
    if (onClick) onClick(character);
    else navigate(`/editor/${character.character_id}`);
  };

  return (
    <div
      className="group relative cursor-pointer transition-all duration-300 hover:z-10"
      style={{ width: 260, height: 380, pointerEvents: 'auto' }}
      onDoubleClick={handleClick}
    >
      {/* 3D 卡片 */}
      <Lanyard characterInfo={characterInfo} />

      {/* hover 发光边框 */}
      <div className="absolute inset-0 rounded-xl ring-1 ring-cyber-green/0 group-hover:ring-cyber-green/30 transition-all duration-500 pointer-events-none" />
    </div>
  );
}

export function AddCharacterBadge({ onClick }) {
  const navigate = useNavigate();
  const handleClick = () => {
    if (onClick) onClick();
    else navigate('/editor');
  };

  return (
    <div
      className="group relative cursor-pointer transition-all duration-300 hover:scale-105 border-2 border-dashed border-cyber-green/20 hover:border-cyber-green/50 flex items-center justify-center bg-[#0d0d14]"
      style={{ width: 260, height: 380, pointerEvents: 'auto' }}
      onClick={handleClick}
    >
      {/* 网格背景 */}
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            'linear-gradient(#A7EF9E 1px, transparent 1px), linear-gradient(90deg, #A7EF9E 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }}
      />
      <div className="relative z-10 text-center">
        <div className="text-5xl text-cyber-green/30 group-hover:text-cyber-green/70 transition-colors mb-3">
          +
        </div>
        <p className="text-xs font-mono text-cyber-green/30 group-hover:text-cyber-green/70 transition-colors">
          添加角色
        </p>
      </div>
    </div>
  );
}
