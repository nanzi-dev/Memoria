import TagInput from './TagInput';
import { BookOpen, Plus, Target, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

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

  const fieldStyle = 'min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-serif text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring';
  const labelStyle = 'mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground';

  return (
    <div className="space-y-6">
      <div className="mb-4 flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" aria-hidden="true" />
        <h3 className="font-archive-serif text-lg font-semibold text-foreground">背景故事 Background</h3>
      </div>

      {/* Story Bio */}
      <div>
        <label className={labelStyle}>背景简介 Story Bio</label>
        <textarea
          value={bg.story_bio || ''}
          onChange={(e) => updateField('background.story_bio', e.target.value)}
          rows={5}
          className={`${fieldStyle} resize-y py-2 leading-7`}
          placeholder="Describe the character's backstory..."
        />
      </div>

      {/* Key Events */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className={labelStyle}>关键事件 Key Events</label>
          <Button type="button" variant="ghost" onClick={addKeyEvent}>
            <Plus aria-hidden="true" /> 添加
          </Button>
        </div>
        <div className="space-y-3">
          {(bg.key_events || []).map((event, idx) => (
            <div key={idx} className="flex items-start gap-2 rounded-md border border-border bg-muted/25 p-3">
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
                  <span className="font-archive-mono text-[10px] text-muted-foreground">Weight:</span>
                  <input
                    type="number" value={event.emotional_weight || 0}
                    onChange={(e) => updateKeyEvent(idx, 'emotional_weight', parseInt(e.target.value) || 0)}
                    className="min-h-11 w-20 rounded-md border border-input bg-background px-2 font-archive-mono text-xs tabular-nums text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeKeyEvent(idx)}
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label={`删除关键事件 ${idx + 1}`}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* Relationships */}
      {showRelationships && <div>
        <div className="mb-2 flex items-center justify-between">
          <label className={labelStyle}>人物关系 Relationships</label>
          <Button type="button" variant="ghost" onClick={addRelationship}>
            <Plus aria-hidden="true" /> 添加
          </Button>
        </div>
        <div className="space-y-3">
          {(bg.relationships || []).map((rel, idx) => (
            <div key={idx} className="flex items-start gap-2 rounded-md border border-border bg-muted/25 p-3">
              <div className="flex-1 space-y-2">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <input type="text" value={rel.target || ''} onChange={(e) => updateRelationship(idx, 'target', e.target.value)} className={fieldStyle} placeholder="Target" />
                  <input type="text" value={rel.relationship_type || ''} onChange={(e) => updateRelationship(idx, 'relationship_type', e.target.value)} className={fieldStyle} placeholder="Type" />
                </div>
                <input type="text" value={rel.description || ''} onChange={(e) => updateRelationship(idx, 'description', e.target.value)} className={fieldStyle} placeholder="Description" />
                <div className="flex items-center gap-2">
                  <span className="font-archive-mono text-[10px] text-muted-foreground">Weight:</span>
                  <input type="number" value={rel.emotional_weight || 0} onChange={(e) => updateRelationship(idx, 'emotional_weight', parseInt(e.target.value) || 0)} className="min-h-11 w-20 rounded-md border border-input bg-background px-2 font-archive-mono text-xs tabular-nums text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeRelationship(idx)}
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label={`删除人物关系 ${idx + 1}`}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
          ))}
        </div>
      </div>}

      {/* Secrets */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className={labelStyle}>秘密 Secrets</label>
          <Button type="button" variant="ghost" onClick={addSecret}>
            <Plus aria-hidden="true" /> 添加
          </Button>
        </div>
        <div className="space-y-3">
          {(bg.secrets || []).map((sec, idx) => (
            <div key={idx} className="flex items-start gap-2 rounded-md border border-border bg-muted/25 p-3">
              <div className="flex-1 space-y-2">
                <input type="text" value={sec.secret || ''} onChange={(e) => updateSecret(idx, 'secret', e.target.value)} className={fieldStyle} placeholder="Secret" />
                <input type="text" value={sec.reveal_conditions || ''} onChange={(e) => updateSecret(idx, 'reveal_conditions', e.target.value)} className={fieldStyle} placeholder="Reveal conditions" />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeSecret(idx)}
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label={`删除秘密 ${idx + 1}`}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* Goals & Motivations */}
      <div className="border-t border-border pt-4">
        <div className="mb-4 flex items-center gap-2">
          <Target className="h-5 w-5 text-primary" aria-hidden="true" />
          <h3 className="font-archive-serif text-lg font-semibold text-foreground">目标与动机 Goals & Motivations</h3>
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
