import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Save, Loader2, Check, ChevronLeft, ChevronRight, Upload, Download } from 'lucide-react';
import { characterAdmin } from '../api/memoria';
import StepIdentity from '../components/editor/StepIdentity';
import StepPersonality from '../components/editor/StepPersonality';
import StepSpeechStyle from '../components/editor/StepSpeechStyle';
import StepBackground from '../components/editor/StepBackground';
import StepInteraction from '../components/editor/StepInteraction';

const STEPS = [
  { id: 'identity', label: '身份 Identity', Icon: null },
  { id: 'personality', label: '性格 Personality', Icon: null },
  { id: 'speech', label: '语言风格 Speech', Icon: null },
  { id: 'background', label: '背景 Background', Icon: null },
  { id: 'interaction', label: '交互规则 Rules', Icon: null },
];

const DEFAULT_DATA = {
  character_id: '',
  avatar_url: null,
  version: '1.0.0',
  meta: { name: '', display_name: '', aliases: [], game_module: '', created_by: '', last_updated: '' },
  identity: { age: '', gender: '', occupation: '', race_or_species: '', appearance: '', social_status: '', core_identity_summary: '' },
  personality: { mbti_or_archetype: '', core_traits: [], values_and_beliefs: [], fears_and_tabooes: [], quirks_and_habits: [], moral_alignment: '' },
  speech_style: { tone_register: '', vocabulary_notes: '', sentence_patterns: [], catchphrases: [], things_never_to_say: [], language: 'zh-CN', formality_default: '' },
  background: { story_bio: '', key_events: [], relationships: [], secrets: [] },
  goals_and_motivations: { current_goals: [], long_term_goals: [], what_triggers_anger: [], what_brings_joy: [] },
  interaction_rules: { initial_attitude_to_player: 'neutral', topics_to_avoid_unless_trusted: [], topics_he_or_she_loves_to_discuss: [], response_to_rudeness: [], gift_reactions: [] },
  action_vocabulary: { greeting_actions: [], farewell_actions: [], agreement_actions: [], disagreement_actions: [], emotional_reactions: [], default_action: 'neutral', fallback_priority: ['emotional_reactions', 'agreement_actions', 'disagreement_actions', 'greeting_actions', 'farewell_actions'] },
  runtime_state_schema: { relationships: [], current_mood: { type: 'enum', emotions: [], intensity: 0, default_mood: 'neutral' } },
  safety_constraints: { topics_to_avoid: [], out_of_character_handling: '' },
};

function mergeCharacterData(importedData) {
  const merged = JSON.parse(JSON.stringify(DEFAULT_DATA));
  for (const [key, value] of Object.entries(importedData)) {
    const baseValue = merged[key];
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      baseValue &&
      typeof baseValue === 'object' &&
      !Array.isArray(baseValue)
    ) {
      merged[key] = { ...baseValue, ...value };
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

function normalizeImportedCharacter(rawData) {
  const data = rawData?.character_data || rawData?.card_data || rawData;
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid character card JSON');
  }
  return data;
}

function characterIdFromFilename(filename) {
  const baseName = filename.replace(/\.[^.]+$/, '');
  const slug = baseName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return slug ? `npc_${slug}` : 'npc_imported_character';
}

function exportFilename(data) {
  const rawName = data.character_id || data.meta?.name || data.meta?.display_name || 'character_card';
  const slug = rawName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_\u4e00-\u9fff-]/g, '');
  return `${slug || 'character_card'}.json`;
}

export default function CharacterEditor() {
  const { characterId } = useParams();
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState(DEFAULT_DATA);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!!characterId);
  const [saveMessage, setSaveMessage] = useState('');
  const [isActive, setIsActive] = useState(true);

  useEffect(() => {
    const previousRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    window.scrollTo(0, 0);
    return () => { window.history.scrollRestoration = previousRestoration; };
  }, []);

  // Load existing character data
  useEffect(() => {
    if (!characterId) return;
    (async () => {
      try {
        // 重试最多2次，应对 429
        let detail;
        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            detail = await characterAdmin.get(characterId);
            break;
          } catch (err) {
            if (attempt === 1) throw err;
            await new Promise(r => setTimeout(r, 800));
          }
        }
        setFormData(detail.card_data);
        // is_active: 1=active, 0=disabled (int)
        const active = detail.is_active === undefined ? true : (detail.is_active === 1 || detail.is_active === true);
        setIsActive(active);
      } catch (e) {
        console.error('Failed to load character:', e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [characterId]);

  const updateField = useCallback((path, value) => {
    setFormData(prev => {
      // deep path update
      const keys = path.split('.');
      const updated = JSON.parse(JSON.stringify(prev));
      let obj = updated;
      for (let i = 0; i < keys.length - 1; i++) {
        obj = obj[keys[i]];
      }
      obj[keys[keys.length - 1]] = value;
      return updated;
    });
  }, []);

  async function handleSave() {
    setSaving(true);
    setSaveMessage('');
    try {
      const data = { ...formData };
      // Auto-generate character_id from name if empty
      if (!data.character_id || data.character_id === '') {
        const name = data.meta?.name || 'new_character';
        data.character_id = `npc_${name.toLowerCase().replace(/\\s+/g, '_').replace(/[^a-z0-9_]/g, '')}`;
      }
      data.character_id = data.character_id || 'npc_new_character';
      if (!data.meta?.name) data.meta.name = data.character_id;
      if (!data.meta?.display_name) data.meta.display_name = data.meta.name;
      data.meta.last_updated = new Date().toISOString().split('T')[0];

      // Try backend API first
      try {
        if (characterId) {
          await characterAdmin.update(characterId, data);
        } else {
          await characterAdmin.create(data);
        }
      } catch (apiErr) {
        setSaveMessage(`Error: ${apiErr.message}`);
        setSaving(false);
        return;
      }

      setSaveMessage('Saved successfully!');
      setTimeout(() => {
        navigate('/');
      }, 800);
    } catch (e) {
      setSaveMessage(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleImportFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const importedData = normalizeImportedCharacter(parsed);
      const data = mergeCharacterData(importedData);
      if (characterId) {
        data.character_id = characterId;
      } else if (!data.character_id) {
        data.character_id = characterIdFromFilename(file.name);
      }
      setFormData(data);
      setIsActive(true);
      setCurrentStep(0);
      setSaveMessage('Imported character JSON. Review and save.');
    } catch (e) {
      setSaveMessage(`Error: ${e.message}`);
    } finally {
      event.target.value = '';
    }
  }

  function handleExportFile() {
    const json = JSON.stringify(formData, null, 2);
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = exportFilename(formData);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function handleToggleActive() {
    if (!characterId) return;
    const action = isActive ? '禁用' : '启用';
    if (!window.confirm(`确定要${action}这个角色卡吗？`)) return;
    try {
      if (isActive) {
        await characterAdmin.delete(characterId, false); // soft delete = disable
      } else {
        await characterAdmin.activate(characterId);
      }
      setIsActive(!isActive);
    } catch (e) {
      console.error(`${action}失败:`, e.message);
    }
  }

  function handleDelete() {
    if (!characterId) return;
    if (!window.confirm('确定要永久删除这个角色卡吗？此操作不可撤销！')) return;
    (async () => {
      try {
        await characterAdmin.delete(characterId, true); // permanent delete
      } catch (e) {
        console.error('Delete failed:', e.message);
      }
      navigate('/');
    })();
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-cyber-bg flex items-center justify-center">
        <Loader2 className="animate-spin text-cyber-green" size={32} />
      </div>
    );
  }

  const StepComponent = [StepIdentity, StepPersonality, StepSpeechStyle, StepBackground, StepInteraction][currentStep];

  return (
    <div className="min-h-screen bg-cyber-bg">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-cyber-surface/95 backdrop-blur border-b border-cyber-green/20">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1 text-cyber-green/60 hover:text-cyber-green transition-colors font-mono text-sm"
          >
            <ArrowLeft size={16} />
            Back
          </button>
          <h1 className="font-display text-lg text-cyber-green tracking-widest">
            {characterId ? 'EDIT CHARACTER' : 'NEW CHARACTER'}
          </h1>
          <div className="flex items-center gap-2">
            {characterId ? (
              <button
                onClick={handleExportFile}
                className="flex items-center gap-1 px-3 py-1 text-xs font-mono text-cyber-green/70 hover:text-cyber-green border border-cyber-green/20 hover:border-cyber-green/40 rounded transition-colors"
              >
                <Download size={14} />
                <span className="hidden sm:inline">Export JSON</span>
              </button>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json,application/json"
                  onChange={handleImportFile}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1 px-3 py-1 text-xs font-mono text-cyber-green/70 hover:text-cyber-green border border-cyber-green/20 hover:border-cyber-green/40 rounded transition-colors"
                >
                  <Upload size={14} />
                  <span className="hidden sm:inline">Import JSON</span>
                </button>
              </>
            )}
            {characterId && (
              <>
                <button
                  onClick={handleToggleActive}
                  className={`px-3 py-1 text-xs font-mono rounded transition-colors border ${
                    isActive
                      ? 'text-amber-400/70 hover:text-amber-400 border-amber-400/20 hover:border-amber-400/40'
                      : 'text-green-400/70 hover:text-green-400 border-green-400/20 hover:border-green-400/40'
                  }`}
                >
                  {isActive ? 'Disable' : 'Enable'}
                </button>
                <button
                  onClick={handleDelete}
                  className="px-3 py-1 text-xs font-mono text-red-400/60 hover:text-red-400 border border-red-400/20 hover:border-red-400/40 rounded transition-colors"
                >
                  Delete
                </button>
              </>
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1 px-4 py-1.5 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save
            </button>
          </div>
        </div>

        {/* Step indicator */}
        <div className="max-w-5xl mx-auto px-4 pb-3">
          <div className="flex items-center justify-between">
            {STEPS.map((step, idx) => (
              <button
                key={step.id}
                onClick={() => setCurrentStep(idx)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono transition-all ${
                  idx === currentStep
                    ? 'bg-cyber-violet/20 text-cyber-violet border border-cyber-violet/40'
                    : idx < currentStep
                    ? 'text-cyber-green/60 hover:text-cyber-green'
                    : 'text-cyber-green/30'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                  idx < currentStep ? 'bg-cyber-green/20 text-cyber-green' :
                  idx === currentStep ? 'bg-cyber-violet/30 text-cyber-violet' :
                  'bg-cyber-green/5 text-cyber-green/30'
                }`}>
                  {idx < currentStep ? <Check size={10} /> : idx + 1}
                </span>
                <span className="hidden sm:inline">{step.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Save message */}
      {saveMessage && (
        <div className={`fixed top-16 left-1/2 -translate-x-1/2 z-30 px-4 py-2 rounded font-mono text-sm ${
          saveMessage.includes('Error') ? 'bg-red-900/80 text-red-300' : 'bg-cyber-green/20 text-cyber-green'
        }`}>
          {saveMessage}
        </div>
      )}

      {/* Form content - Paper folder style */}
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="relative">
          {/* Paper folder background */}
          <div
            className="rounded-lg shadow-2xl overflow-hidden"
            style={{
              background: 'linear-gradient(135deg, #3D3226 0%, #4A3B2C 30%, #3D3226 60%, #362B20 100%)',
              border: '1px solid #5A4A38',
              boxShadow: '0 20px 60px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05)',
            }}
          >
            {/* Folder tab */}
            <div
              className="relative mx-8 -mt-0.5"
              style={{
                background: '#4A3B2C',
                borderTopLeftRadius: 8,
                borderTopRightRadius: 8,
                border: '1px solid #5A4A38',
                borderBottom: 'none',
                padding: '8px 24px',
                display: 'inline-block',
              }}
            >
              <p className="text-center font-mono text-xs text-amber-800/80 tracking-wider">
                ★ CHARACTER FILE ★
              </p>
            </div>

            {/* Paper card */}
            <div
              className="mx-6 mb-6 rounded-sm"
              style={{
                background: 'linear-gradient(to bottom, #F5EDE0 0%, #EDE4D4 100%)',
                border: '1px solid #C4B594',
                boxShadow: '0 2px 12px rgba(0,0,0,0.3), inset 0 0 30px rgba(139,119,90,0.1)',
              }}
            >
              {/* Card header */}
              <div className="p-6 pb-4 border-b" style={{ borderColor: '#C4B594' }}>
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-bold text-cyber-ink font-mono tracking-wide">
                      CHARACTER RESUME / PROFILE CARD
                    </h2>
                    <p className="text-xs text-amber-700/60 font-mono mt-1">
                      CHARACTER RESUME / PROFILE CARD
                    </p>
                  </div>
                  {/* Decorative compass/mark */}
                  <div className="text-cyber-ink/20">
                    <svg width="40" height="40" viewBox="0 0 40 40">
                      <circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" strokeWidth="1" />
                      <circle cx="20" cy="20" r="8" fill="none" stroke="currentColor" strokeWidth="0.5" />
                      <line x1="20" y1="2" x2="20" y2="8" stroke="currentColor" strokeWidth="1" />
                      <line x1="20" y1="32" x2="20" y2="38" stroke="currentColor" strokeWidth="1" />
                      <line x1="2" y1="20" x2="8" y2="20" stroke="currentColor" strokeWidth="1" />
                      <line x1="32" y1="20" x2="38" y2="20" stroke="currentColor" strokeWidth="1" />
                      <polygon points="20,4 23,18 20,22 17,18" fill="currentColor" />
                    </svg>
                  </div>
                </div>
              </div>

              {/* Form body */}
              <div className="p-6">
                <StepComponent formData={formData} updateField={updateField} />
              </div>

              {/* Card footer - status + stamp */}
              <div className="p-6 pt-4 border-t flex items-center justify-between" style={{ borderColor: '#C4B594' }}>
                <div className="flex items-center gap-4">
                  <div>
                    <span className="text-[10px] text-amber-700/60 font-mono uppercase">最后更新</span>
                    <p className="text-xs font-mono text-amber-700/80">
                      {formData.meta?.last_updated || new Date().toISOString().split('T')[0]}
                    </p>
                  </div>
                </div>

                {/* Red stamp */}
                <div
                  className="relative"
                  style={{
                    transform: 'rotate(-8deg)',
                    border: isActive ? '2px solid #0B6E0B' : '2px solid #8B0000',
                    borderRadius: 4,
                    padding: '4px 12px',
                    opacity: 0.6,
                  }}
                >
                  <span className={`text-xs font-bold font-mono whitespace-nowrap ${isActive ? 'text-green-800/70' : 'text-red-900/70'}`}>
                    {isActive ? '启用档案' : '禁用档案'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Step navigation */}
          <div className="flex items-center justify-between mt-6">
            <button
              onClick={() => setCurrentStep(prev => Math.max(0, prev - 1))}
              disabled={currentStep === 0}
              className="flex items-center gap-1 px-4 py-2 text-sm font-mono text-cyber-green/60 hover:text-cyber-green disabled:opacity-30 transition-colors"
            >
              <ChevronLeft size={16} />
              Previous
            </button>
            <span className="text-xs font-mono text-cyber-green/40">
              Step {currentStep + 1} of {STEPS.length}
            </span>
            {currentStep < STEPS.length - 1 ? (
              <button
                onClick={() => setCurrentStep(prev => Math.min(STEPS.length - 1, prev + 1))}
                className="flex items-center gap-1 px-4 py-2 text-sm font-mono text-cyber-green/60 hover:text-cyber-green transition-colors"
              >
                Next
                <ChevronRight size={16} />
              </button>
            ) : (
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1 px-6 py-2 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 transition-colors"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                Finish & Save
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
