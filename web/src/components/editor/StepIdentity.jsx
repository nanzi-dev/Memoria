import TagInput from './TagInput';

export default function StepIdentity({ formData, updateField }) {
  const meta = formData.meta || {};
  const identity = formData.identity || {};

  const infoFields = [
    { key: 'meta.name', label: '姓名 Name', value: meta.name || '' },
    { key: 'meta.display_name', label: '显示名 Display Name', value: meta.display_name || '' },
    { key: 'identity.gender', label: '性别 Gender', value: identity.gender || '' },
    { key: 'identity.age', label: '年龄 Age', value: identity.age || '' },
    { key: 'identity.occupation', label: '职业 Occupation', value: identity.occupation || '' },
    { key: 'identity.race_or_species', label: '种族 Race/Species', value: identity.race_or_species || '' },
    { key: 'identity.social_status', label: '社会地位 Social Status', value: identity.social_status || '' },
    { key: 'identity.appearance', label: '外貌 Appearance', value: identity.appearance || '', multiline: true },
    { key: 'identity.core_identity_summary', label: '身份总结 Identity Summary', value: identity.core_identity_summary || '', multiline: true },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg text-cyber-ink/60">👤</span>
        <h3 className="font-mono text-lg font-bold text-cyber-ink">身份信息 Identity</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {infoFields.map(({ key, label, value, multiline }) => (
          <div key={key} className={multiline ? 'md:col-span-2' : ''}>
            <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
              {label}
            </label>
            {multiline ? (
              <textarea
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                rows={3}
                className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-amber-50/50 border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50 rounded-t resize-none transition-colors"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            ) : (
              <input
                type="text"
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
                placeholder={`Enter ${label.toLowerCase()}...`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Aliases */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          别名 Aliases
        </label>
        <TagInput
          tags={meta.aliases || []}
          onChange={(tags) => updateField('meta.aliases', tags)}
          placeholder="Add alias..."
        />
      </div>

      {/* Avatar URL */}
      <div>
        <label className="block text-[11px] text-amber-700/60 font-mono mb-1 uppercase tracking-wider">
          头像 URL Avatar URL
        </label>
        <input
          type="text"
          value={formData.avatar_url || ''}
          onChange={(e) => updateField('avatar_url', e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono text-cyber-ink bg-transparent border-b border-amber-300/50 focus:border-amber-500 focus:outline-none focus:bg-amber-50/50 transition-colors"
          placeholder="https://..."
        />
      </div>
    </div>
  );
}
