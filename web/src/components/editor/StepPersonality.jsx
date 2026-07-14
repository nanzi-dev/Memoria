import TagInput from './TagInput';
import { Brain } from 'lucide-react';

export default function StepPersonality({ formData, updateField }) {
  const p = formData.personality || {};

  return (
    <div className="space-y-6">
      <div className="memoria-section-heading">
        <Brain size={18} />
        <h3 className="font-mono text-base font-bold text-zinc-100 sm:text-lg">性格特征 Personality</h3>
      </div>

      {/* MBTI / Archetype */}
      <div>
        <label className="memoria-form-label">
          MBTI / 性格原型 MBTI or Archetype
        </label>
        <input
          type="text"
          value={p.mbti_or_archetype || ''}
          onChange={(e) => updateField('personality.mbti_or_archetype', e.target.value)}
          className="memoria-form-control"
          placeholder="e.g. ISTJ, The Caregiver..."
        />
      </div>

      {/* Core Traits */}
      <div>
        <label className="memoria-form-label">
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
        <label className="memoria-form-label">
          道德取向 Moral Alignment
        </label>
        <input
          type="text"
          value={p.moral_alignment || ''}
          onChange={(e) => updateField('personality.moral_alignment', e.target.value)}
          className="memoria-form-control"
          placeholder="e.g. 中立善良..."
        />
      </div>

      {/* Values & Beliefs */}
      <div>
        <label className="memoria-form-label">
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
        <label className="memoria-form-label">
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
        <label className="memoria-form-label">
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
