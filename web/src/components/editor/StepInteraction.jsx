import TagInput from './TagInput';

export default function StepInteraction({ formData, updateField }) {
  const ir = formData.interaction_rules || {};
  const sc = formData.safety_constraints || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg text-cyber-ink/60">🤝</span>
        <h3 className="font-mono text-lg font-bold text-cyber-ink">交互规则 Interaction Rules</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Initial Attitude */}
        <div>
          <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
            初始态度 Initial Attitude
          </label>
          <select
            value={ir.initial_attitude_to_player || 'neutral'}
            onChange={(e) => updateField('interaction_rules.initial_attitude_to_player', e.target.value)}
            className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none"
          >
            <option value="friendly">友好 Friendly</option>
            <option value="neutral">中立 Neutral</option>
            <option value="hostile">敌对 Hostile</option>
            <option value="cautious">谨慎 Cautious</option>
            <option value="curious">好奇 Curious</option>
          </select>
        </div>
      </div>

      {/* Topics to Avoid Unless Trusted */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          需要信任才能讨论的话题 Topics to Avoid Unless Trusted
        </label>
        <TagInput
          tags={ir.topics_to_avoid_unless_trusted || []}
          onChange={(tags) => updateField('interaction_rules.topics_to_avoid_unless_trusted', tags)}
          placeholder="e.g. 个人过去..."
        />
      </div>

      {/* Topics Loves to Discuss */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          喜欢讨论的话题 Topics Loves to Discuss
        </label>
        <TagInput
          tags={ir.topics_he_or_she_loves_to_discuss || []}
          onChange={(tags) => updateField('interaction_rules.topics_he_or_she_loves_to_discuss', tags)}
          placeholder="e.g. 战术策略..."
        />
      </div>

      {/* Response to Rudeness */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          对粗鲁行为的反应 Response to Rudeness
        </label>
        <TagInput
          tags={ir.response_to_rudeness || []}
          onChange={(tags) => updateField('interaction_rules.response_to_rudeness', tags)}
          placeholder="e.g. 忽略, 反击..."
        />
      </div>

      {/* Gift Reactions */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          礼物反应 Gift Reactions (格式: 礼物类型, 反应)
        </label>
        <TagInput
          tags={(ir.gift_reactions || []).map(g => Array.isArray(g) ? g.join(', ') : g)}
          onChange={(tags) => updateField('interaction_rules.gift_reactions', tags.map(t => {
            const parts = t.split(',').map(s => s.trim());
            return parts.length >= 2 ? [parts[0], parts.slice(1).join(', ')] : [t, 'neutral'];
          }))}
          placeholder="e.g. 书籍, 喜欢..."
        />
      </div>

      {/* Safety Constraints */}
      <div className="border-t pt-4" style={{ borderColor: '#C4B594' }}>
        <div className="flex items-center gap-2 mb-4">
          <span className="text-lg text-cyber-ink/60">🛡️</span>
          <h3 className="font-mono text-lg font-bold text-cyber-ink">安全约束 Safety Constraints</h3>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              需要避免的话题 Topics to Avoid
            </label>
            <TagInput
              tags={sc.topics_to_avoid || []}
              onChange={(tags) => updateField('safety_constraints.topics_to_avoid', tags)}
              placeholder="e.g. 现实政治..."
            />
          </div>
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              OOC处理方式 Out-of-Character Handling
            </label>
            <input
              type="text"
              value={sc.out_of_character_handling || ''}
              onChange={(e) => updateField('safety_constraints.out_of_character_handling', e.target.value)}
              className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
              placeholder="How to handle out-of-character situations..."
            />
          </div>
        </div>
      </div>

      {/* Action Vocabulary (simplified) */}
      <div className="border-t pt-4" style={{ borderColor: '#C4B594' }}>
        <div className="flex items-center gap-2 mb-4">
          <span className="text-lg text-cyber-ink/60">🎬</span>
          <h3 className="font-mono text-lg font-bold text-cyber-ink">行为动作词库 Action Vocabulary</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              打招呼 Greeting
            </label>
            <TagInput
              tags={formData.action_vocabulary?.greeting_actions || []}
              onChange={(tags) => updateField('action_vocabulary.greeting_actions', tags)}
              placeholder="e.g. 点头致意..."
            />
          </div>
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              告别 Farewell
            </label>
            <TagInput
              tags={formData.action_vocabulary?.farewell_actions || []}
              onChange={(tags) => updateField('action_vocabulary.farewell_actions', tags)}
              placeholder="e.g. 转身离开..."
            />
          </div>
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              同意 Agreement
            </label>
            <TagInput
              tags={formData.action_vocabulary?.agreement_actions || []}
              onChange={(tags) => updateField('action_vocabulary.agreement_actions', tags)}
              placeholder="e.g. 微微点头..."
            />
          </div>
          <div>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              反对 Disagreement
            </label>
            <TagInput
              tags={formData.action_vocabulary?.disagreement_actions || []}
              onChange={(tags) => updateField('action_vocabulary.disagreement_actions', tags)}
              placeholder="e.g. 皱眉摇头..."
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              情绪反应 Emotional Reactions
            </label>
            <TagInput
              tags={formData.action_vocabulary?.emotional_reactions || []}
              onChange={(tags) => updateField('action_vocabulary.emotional_reactions', tags)}
              placeholder="e.g. 目光柔和..."
            />
          </div>
        </div>
      </div>
    </div>
  );
}
