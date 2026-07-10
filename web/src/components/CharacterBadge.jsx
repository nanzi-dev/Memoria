import { useNavigate } from 'react-router-dom';
import { memo, useMemo } from 'react';
import Lanyard from './Lanyard';

function CharacterBadge({ character, onClick, isActive = true }) {
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
      className="relative group animate-fade-up rounded-[28px]"
      style={{
        width: 320,
        height: 460,
        pointerEvents: 'auto',
        contentVisibility: 'auto',
        containIntrinsicSize: '320px 460px',
      }}
    >
      <div
        className={`relative cursor-pointer rounded-[28px] transition-all duration-300 hover:z-10 hover:-translate-y-1 ${!isActive ? 'card-disabled' : ''}`}
        style={{ width: 320, height: 460, pointerEvents: 'auto' }}
        onDoubleClick={handleClick}
      >
        <Lanyard
          characterInfo={characterInfo}
          className="transition-[filter,transform] duration-300 group-hover:scale-[1.01] group-hover:drop-shadow-[0_0_28px_rgba(167,239,158,0.18)]"
        />
      </div>
    </div>
  );
}

export default memo(CharacterBadge);

export function AddCharacterBadge({ onClick }) {
  const navigate = useNavigate();
  const handleClick = () => {
    if (onClick) onClick();
    else navigate('/editor');
  };

  return (
    <div
      className="group relative cursor-pointer transition-all duration-300 hover:scale-[1.03] hover:-translate-y-1 border-2 border-dashed border-cyber-green/20 hover:border-cyber-green/50 flex items-center justify-center bg-[#0d0d14] animate-fade-up"
      style={{ width: 320, height: 460, pointerEvents: 'auto' }}
      onDoubleClick={handleClick}
    >
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
        <p className="text-sm font-character text-cyber-green/30 group-hover:text-cyber-green/70 transition-colors">
          添加角色
        </p>
      </div>
    </div>
  );
}
