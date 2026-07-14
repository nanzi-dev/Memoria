import TagInput from './TagInput';
import { BookOpen, Plus, Target, Trash2 } from 'lucide-react';

export default function StepBackground({ formData, updateField, showRelationships = true }) {
  const bg = formData.background || {};
  const gm = formData.goals_and_motivations || {};

  // Key Events helpers
  function addKeyEvent() {
    const events = [...(bg.key_events || []), { event: '', description: '', emotional_weight: 0 }];
    updateField('background.key_events', events);
  }
  function updateKeyEvent(idx, field, value) {
    const events = [...(bg.key_events || [])];
    events[idx] = { ...events[idx], [field]: value };
    updateField('background.key_events', events);
  }
  function removeKeyEvent(idx) {
    updateField('background.key_events', (bg.key_events || []).filter((_, i) => i !== idx));
  }

  // Relationships helpers
  function addRelationship() {
    const rels = [...(bg.relationships || []), { target: '', relationship_type: '', description: '', emotional_weight: 0 }];
    updateField('background.relationships', rels);
  }
  function updateRelationship(idx, field, value) {
    const rels = [...(bg.relationships || [])];
    rels[idx] = { ...rels[idx], [field]: value };
    updateField('background.relationships', rels);
  }
  function removeRelationship(idx) {
    updateField('background.relationships', (bg.relationships || []).filter((_, i) => i !== idx));
  }

  // Secrets helpers
  function addSecret() {
    const secrets = [...(bg.secrets || []), { secret: '', description: '', reveal_conditions: '' }];
    updateField('background.secrets', secrets);
  }
  function updateSecret(idx, field, value) {
    const secrets = [...(bg.secrets || [])];
    secrets[idx] = { ...secrets[idx], [field]: value };
    updateField('background.secrets', secrets);
  }
  function removeSecret(idx) {
    updateField('background.secrets', (bg.secrets || []).filter((_, i) => i !== idx));
  }

  const fieldStyle = 'memoria-form-control';
  const labelStyle = 'memoria-form-label';

  return (
    <div className="space-y-6">
      <div className="memoria-section-heading">
        <BookOpen size={18} />
        <h3 className="font-mono text-base font-bold text-zinc-100 sm:text-lg">背景故事 Background</h3>
      </div>

      {/* Story Bio */}
      <div>
        <label className={labelStyle}>背景简介 Story Bio</label>
        <textarea
          value={bg.story_bio || ''}
          onChange={(e) => updateField('background.story_bio', e.target.value)}
          rows={5}
          className={fieldStyle}
          placeholder="Describe the character's backstory..."
        />
      </div>

      {/* Key Events */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className={labelStyle}>关键事件 Key Events</label>
          <button type="button" onClick={addKeyEvent} className="memoria-button px-3">
            <Plus size={12} /> Add
          </button>
        </div>
        <div className="space-y-3">
          {(bg.key_events || []).map((event, idx) => (
            <div key={idx} className="memoria-editor-item flex items-start gap-2">
              <div className="flex-1 space-y-2">
                <input
                  type="text" value={event.event || ''}
                  onChange={(e) => updateKeyEvent(idx, 'event', e.target.value)}
                  className={fieldStyle} placeholder="Event name"
                />
                <input
                  type="text" value={event.description || ''}
                  onChange={(e) => updateKeyEvent(idx, 'description', e.target.value)}
                  className={fieldStyle} placeholder="Description"
                />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-cyber-green/40 font-mono">Weight:</span>
                  <input
                    type="number" value={event.emotional_weight || 0}
                    onChange={(e) => updateKeyEvent(idx, 'emotional_weight', parseInt(e.target.value) || 0)}
                    className="memoria-form-control w-20"
                  />
                </div>
              </div>
              <button type="button" onClick={() => removeKeyEvent(idx)} className="memoria-icon-button mt-1 text-zinc-600 hover:bg-red-400/10 hover:text-red-300" aria-label="删除关键事件">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Relationships */}
      {showRelationships && <div>
        <div className="flex items-center justify-between mb-2">
          <label className={labelStyle}>人物关系 Relationships</label>
          <button type="button" onClick={addRelationship} className="memoria-button px-3">
            <Plus size={12} /> Add
          </button>
        </div>
        <div className="space-y-3">
          {(bg.relationships || []).map((rel, idx) => (
            <div key={idx} className="memoria-editor-item flex items-start gap-2">
              <div className="flex-1 space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <input type="text" value={rel.target || ''} onChange={(e) => updateRelationship(idx, 'target', e.target.value)} className={fieldStyle} placeholder="Target" />
                  <input type="text" value={rel.relationship_type || ''} onChange={(e) => updateRelationship(idx, 'relationship_type', e.target.value)} className={fieldStyle} placeholder="Type" />
                </div>
                <input type="text" value={rel.description || ''} onChange={(e) => updateRelationship(idx, 'description', e.target.value)} className={fieldStyle} placeholder="Description" />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-cyber-green/40 font-mono">Weight:</span>
                  <input type="number" value={rel.emotional_weight || 0} onChange={(e) => updateRelationship(idx, 'emotional_weight', parseInt(e.target.value) || 0)} className="memoria-form-control w-20" />
                </div>
              </div>
              <button type="button" onClick={() => removeRelationship(idx)} className="memoria-icon-button mt-1 text-zinc-600 hover:bg-red-400/10 hover:text-red-300" aria-label="删除人物关系">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>}

      {/* Secrets */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className={labelStyle}>秘密 Secrets</label>
          <button type="button" onClick={addSecret} className="memoria-button px-3">
            <Plus size={12} /> Add
          </button>
        </div>
        <div className="space-y-3">
          {(bg.secrets || []).map((sec, idx) => (
            <div key={idx} className="memoria-editor-item flex items-start gap-2">
              <div className="flex-1 space-y-2">
                <input type="text" value={sec.secret || ''} onChange={(e) => updateSecret(idx, 'secret', e.target.value)} className={fieldStyle} placeholder="Secret" />
                <input type="text" value={sec.reveal_conditions || ''} onChange={(e) => updateSecret(idx, 'reveal_conditions', e.target.value)} className={fieldStyle} placeholder="Reveal conditions" />
              </div>
              <button type="button" onClick={() => removeSecret(idx)} className="memoria-icon-button mt-1 text-zinc-600 hover:bg-red-400/10 hover:text-red-300" aria-label="删除秘密">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Goals & Motivations */}
      <div className="border-t border-cyber-green/10 pt-5">
        <div className="memoria-section-heading mb-4">
          <Target size={18} />
          <h3 className="font-mono text-base font-bold text-zinc-100 sm:text-lg">目标与动机 Goals & Motivations</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={labelStyle}>当前目标 Current Goals</label>
            <TagInput tags={gm.current_goals || []} onChange={(tags) => updateField('goals_and_motivations.current_goals', tags)} placeholder="Add goal..." />
          </div>
          <div>
            <label className={labelStyle}>长期目标 Long-term Goals</label>
            <TagInput tags={gm.long_term_goals || []} onChange={(tags) => updateField('goals_and_motivations.long_term_goals', tags)} placeholder="Add goal..." />
          </div>
          <div>
            <label className={labelStyle}>激怒因素 Triggers Anger</label>
            <TagInput tags={gm.what_triggers_anger || []} onChange={(tags) => updateField('goals_and_motivations.what_triggers_anger', tags)} placeholder="Add trigger..." />
          </div>
          <div>
            <label className={labelStyle}>快乐来源 Brings Joy</label>
            <TagInput tags={gm.what_brings_joy || []} onChange={(tags) => updateField('goals_and_motivations.what_brings_joy', tags)} placeholder="Add source of joy..." />
          </div>
        </div>
      </div>
    </div>
  );
}
