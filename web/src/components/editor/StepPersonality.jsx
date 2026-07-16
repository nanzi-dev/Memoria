import TagInput from './TagInput';
import { Brain } from 'lucide-react';

export default function StepPersonality({ formData, updateField }) {
  const p = formData.personality || {};
  const labelStyle = 'mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground';
  const inputStyle = 'min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-serif text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring';

  return (
    <div className="space-y-6">
      <div className="mb-4 flex items-center gap-2">
        <Brain className="h-5 w-5 text-primary" aria-hidden="true" />
        <h3 className="font-archive-serif text-lg font-semibold text-foreground">性格特征 Personality</h3>
      </div>

      {/* MBTI / Archetype */}
      <div>
        <label className={labelStyle}>
          MBTI / 性格原型 MBTI or Archetype
        </label>
        <input
          type="text"
          value={p.mbti_or_archetype || ''}
          onChange={(e) => updateField('personality.mbti_or_archetype', e.target.value)}
          className={inputStyle}
          placeholder="e.g. ISTJ, The Caregiver..."
        />
      </div>

      {/* Core Traits */}
      <div>
        <label className={labelStyle}>
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
        <label className={labelStyle}>
          道德取向 Moral Alignment
        </label>
        <input
          type="text"
          value={p.moral_alignment || ''}
          onChange={(e) => updateField('personality.moral_alignment', e.target.value)}
          className={inputStyle}
          placeholder="e.g. 中立善良..."
        />
      </div>

      {/* Values & Beliefs */}
      <div>
        <label className={labelStyle}>
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
        <label className={labelStyle}>
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
        <label className={labelStyle}>
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
