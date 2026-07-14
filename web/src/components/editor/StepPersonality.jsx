import TagInput from './TagInput';

export default function StepPersonality({ formData, updateField }) {
  const p = formData.personality || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg text-cyber-ink/60">🎭</span>
        <h3 className="font-mono text-lg font-bold text-cyber-ink">性格特征 Personality</h3>
      </div>

      {/* MBTI / Archetype */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          MBTI / 性格原型 MBTI or Archetype
        </label>
        <input
          type="text"
          value={p.mbti_or_archetype || ''}
          onChange={(e) => updateField('personality.mbti_or_archetype', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
          placeholder="e.g. ISTJ, The Caregiver..."
        />
      </div>

      {/* Core Traits */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          核心性格特征 Core Traits
        </label>
        <TagInput
          tags={p.core_traits || []}
          onChange={(tags) => updateField('personality.core_traits', tags)}
          placeholder="e.g. 冷静, 果断..."
        />
      </div>

      {/* Moral Alignment */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          道德取向 Moral Alignment
        </label>
        <input
          type="text"
          value={p.moral_alignment || ''}
          onChange={(e) => updateField('personality.moral_alignment', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
          placeholder="e.g. 中立善良..."
        />
      </div>

      {/* Values & Beliefs */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          价值观与信念 Values & Beliefs
        </label>
        <TagInput
          tags={p.values_and_beliefs || []}
          onChange={(tags) => updateField('personality.values_and_beliefs', tags)}
          placeholder="e.g. 行动胜于言语..."
        />
      </div>

      {/* Fears & Taboos */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          恐惧与禁忌 Fears & Taboos
        </label>
        <TagInput
          tags={p.fears_and_tabooes || []}
          onChange={(tags) => updateField('personality.fears_and_tabooes', tags)}
          placeholder="e.g. 害怕被同情..."
        />
      </div>

      {/* Quirks & Habits */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          怪癖与习惯 Quirks & Habits
        </label>
        <TagInput
          tags={p.quirks_and_habits || []}
          onChange={(tags) => updateField('personality.quirks_and_habits', tags)}
          placeholder="e.g. 双手插兜走路..."
        />
      </div>
    </div>
  );
}
