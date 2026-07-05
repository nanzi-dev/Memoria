import TagInput from './TagInput';

export default function StepSpeechStyle({ formData, updateField }) {
  const s = formData.speech_style || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg text-cyber-ink/60">💬</span>
        <h3 className="font-mono text-lg font-bold text-cyber-ink">语言风格 Speech Style</h3>
      </div>

      {/* Tone */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          语气 Tone Register
        </label>
        <input
          type="text"
          value={s.tone_register || ''}
          onChange={(e) => updateField('speech_style.tone_register', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
          placeholder="e.g. 简短、直接..."
        />
      </div>

      {/* Vocabulary Notes */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          用词习惯 Vocabulary Notes
        </label>
        <textarea
          value={s.vocabulary_notes || ''}
          onChange={(e) => updateField('speech_style.vocabulary_notes', e.target.value)}
          rows={3}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-amber-50/50 border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50 rounded-t resize-none transition-colors"
          placeholder="Describe vocabulary habits..."
        />
      </div>

      {/* Formality */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          默认正式程度 Formality Default
        </label>
        <input
          type="text"
          value={s.formality_default || ''}
          onChange={(e) => updateField('speech_style.formality_default', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
          placeholder="e.g. 疏离克制..."
        />
      </div>

      {/* Language */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          语言 Language
        </label>
        <select
          value={s.language || 'zh-CN'}
          onChange={(e) => updateField('speech_style.language', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none"
        >
          <option value="zh-CN">中文 (zh-CN)</option>
          <option value="en-US">English (en-US)</option>
          <option value="ja-JP">日本語 (ja-JP)</option>
        </select>
      </div>

      {/* Sentence Patterns */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          常用句式 Sentence Patterns
        </label>
        <TagInput
          tags={s.sentence_patterns || []}
          onChange={(tags) => updateField('speech_style.sentence_patterns', tags)}
          placeholder="e.g. 短句为主..."
        />
      </div>

      {/* Catchphrases */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          口头禅 Catchphrases
        </label>
        <TagInput
          tags={s.catchphrases || []}
          onChange={(tags) => updateField('speech_style.catchphrases', tags)}
          placeholder="e.g. 没必要解释..."
        />
      </div>

      {/* Things Never to Say */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          禁忌用语 Things Never to Say
        </label>
        <TagInput
          tags={s.things_never_to_say || []}
          onChange={(tags) => updateField('speech_style.things_never_to_say', tags)}
          placeholder="e.g. 不会主动诉苦..."
        />
      </div>
    </div>
  );
}
