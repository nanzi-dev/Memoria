import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  BookOpen,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Fingerprint,
  Handshake,
  Loader2,
  MessageSquare,
  Power,
  PowerOff,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from 'lucide-react';
import { characterAdmin } from '../api/memoria';
import StepIdentity from '../components/editor/StepIdentity';
import StepPersonality from '../components/editor/StepPersonality';
import StepSpeechStyle from '../components/editor/StepSpeechStyle';
import StepBackground from '../components/editor/StepBackground';
import StepInteraction from '../components/editor/StepInteraction';
import { useDialog } from '../context/DialogContext';
import { characterEditorPath } from '../utils/navigationState';
import { createTimeoutController } from '../utils/timeoutController';
import { useArchiveShell } from '@/archive/ArchiveShell';
import ArchiveEditorWorkspace from '@/archive/ArchiveEditorWorkspace';
import { Button } from '@/components/ui/button';

const STEPS = [
  { id: 'identity', label: '身份 Identity', description: '姓名、外貌与账户标识', Icon: Fingerprint },
  { id: 'personality', label: '性格 Personality', description: '特质、价值观与禁忌', Icon: Brain },
  { id: 'speech', label: '语言风格 Speech', description: '措辞、句式与角色语音', Icon: MessageSquare },
  { id: 'background', label: '背景 Background', description: '往事、关系、秘密与目标', Icon: BookOpen },
  { id: 'interaction', label: '交互规则 Rules', description: '互动边界与动作词库', Icon: Handshake },
];

const SUPPORTED_I18N_LOCALES = ['zh-CN', 'en-US'];

const LOCALIZABLE_FIELDS = {
  meta: new Set(['name', 'display_name', 'aliases', 'game_module', 'created_by']),
  identity: new Set(['age', 'gender', 'occupation', 'race_or_species', 'appearance', 'social_status', 'core_identity_summary']),
  personality: new Set(['mbti_or_archetype', 'core_traits', 'values_and_beliefs', 'fears_and_tabooes', 'quirks_and_habits', 'moral_alignment']),
  speech_style: new Set(['tone_register', 'vocabulary_notes', 'sentence_patterns', 'catchphrases', 'things_never_to_say', 'language', 'formality_default']),
  background: new Set(['story_bio', 'key_events', 'secrets']),
  goals_and_motivations: new Set(['current_goals', 'long_term_goals', 'what_triggers_anger', 'what_brings_joy']),
  interaction_rules: new Set(['initial_attitude_to_player', 'topics_to_avoid_unless_trusted', 'topics_he_or_she_loves_to_discuss', 'response_to_rudeness', 'gift_reactions']),
  action_vocabulary: new Set(['greeting_actions', 'farewell_actions', 'agreement_actions', 'disagreement_actions', 'emotional_reactions', 'default_action', 'fallback_priority']),
  safety_constraints: new Set(['topics_to_avoid', 'out_of_character_handling']),
};

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
  voice: { builtinVoice: 'alloy', customVoiceId: null, customVoiceStatus: 'unconfigured', ttsInstructions: '' },
  i18n: {},
};

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function cloneData(value) {
  if (Array.isArray(value)) return value.map(cloneData);
  if (!isPlainObject(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, cloneData(entry)]));
}

function deepMerge(base, override) {
  const merged = isPlainObject(base) ? cloneData(base) : {};
  if (!isPlainObject(override)) return merged;
  for (const [key, value] of Object.entries(override)) {
    merged[key] = isPlainObject(value) && isPlainObject(merged[key])
      ? deepMerge(merged[key], value)
      : cloneData(value);
  }
  return merged;
}

function sanitizeLocaleOverride(override) {
  if (!isPlainObject(override)) return {};
  const sanitized = {};
  for (const [root, allowedFields] of Object.entries(LOCALIZABLE_FIELDS)) {
    const source = override[root];
    if (!isPlainObject(source)) continue;
    const fields = {};
    for (const [field, value] of Object.entries(source)) {
      if (allowedFields.has(field)) fields[field] = cloneData(value);
    }
    if (Object.keys(fields).length) sanitized[root] = fields;
  }
  return sanitized;
}

function sanitizeI18n(i18n) {
  if (!isPlainObject(i18n)) return {};
  return Object.fromEntries(
    SUPPORTED_I18N_LOCALES
      .filter(locale => isPlainObject(i18n[locale]))
      .map(locale => [locale, sanitizeLocaleOverride(i18n[locale])]),
  );
}

function mergeCharacterData(importedData) {
  const merged = deepMerge(DEFAULT_DATA, isPlainObject(importedData) ? importedData : {});
  merged.i18n = sanitizeI18n(merged.i18n);
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
  const dialog = useDialog();
  const { setPrimaryAction } = useArchiveShell();
  const fileInputRef = useRef(null);
  const navigationTimeoutRef = useRef(null);
  if (!navigationTimeoutRef.current) {
    navigationTimeoutRef.current = createTimeoutController();
  }
  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState(() => mergeCharacterData({}));
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!!characterId);
  const [loadedCharacterId, setLoadedCharacterId] = useState(characterId ? null : '');
  const [loadError, setLoadError] = useState('');
  const [reloadVersion, setReloadVersion] = useState(0);
  const [actionPending, setActionPending] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [isActive, setIsActive] = useState(true);

  useEffect(() => {
    const previousRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    window.scrollTo(0, 0);
    return () => {
      navigationTimeoutRef.current.cancel();
      window.history.scrollRestoration = previousRestoration;
    };
  }, []);

  // Load existing character data
  useEffect(() => {
    let cancelled = false;
    if (!characterId) {
      setFormData(mergeCharacterData({}));
      setLoading(false);
      setLoadedCharacterId('');
      setLoadError('');
      setIsActive(true);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setLoadedCharacterId(null);
    setLoadError('');
    setSaveMessage('');
    setCurrentStep(0);

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
        if (cancelled) return;
        setFormData(mergeCharacterData(detail.card_data));
        // is_active: 1=active, 0=disabled (int)
        const active = detail.is_active === undefined ? true : (detail.is_active === 1 || detail.is_active === true);
        setIsActive(active);
        setLoadedCharacterId(characterId);
      } catch (e) {
        if (!cancelled) {
          setLoadError(`Failed to load character: ${e.message}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [characterId, reloadVersion]);

  const updateField = useCallback((path, value) => {
    setFormData(prev => {
      const keys = path.split('.');
      const updated = cloneData(prev);
      let obj = updated;
      for (let i = 0; i < keys.length - 1; i++) {
        if (!isPlainObject(obj[keys[i]])) obj[keys[i]] = {};
        obj = obj[keys[i]];
      }
      obj[keys[keys.length - 1]] = cloneData(value);
      return updated;
    });
  }, []);

  async function handleSave() {
    if (characterId && loadedCharacterId !== characterId) return;
    setSaving(true);
    setSaveMessage('');
    try {
      const data = cloneData(formData);
      // Auto-generate character_id from name if empty
      if (!data.character_id || data.character_id === '') {
        const name = data.meta?.name || 'new_character';
        data.character_id = `npc_${name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')}`;
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
      navigationTimeoutRef.current.schedule(() => {
        navigate(characterId ? '/' : characterEditorPath(data.character_id));
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
    if (!characterId || actionPending) return;
    const action = isActive ? '禁用' : '启用';
    const ok = await dialog.confirm({
      title: `${action}角色卡`,
      message: `确定要${action}这个角色卡吗？`,
      variant: isActive ? 'warning' : 'info',
      confirmText: action,
    });
    if (!ok) return;
    setActionPending(true);
    setSaveMessage('');
    try {
      if (isActive) {
        await characterAdmin.delete(characterId, false); // soft delete = disable
      } else {
        await characterAdmin.activate(characterId);
      }
      setIsActive(prev => !prev);
      setSaveMessage(`${action}成功`);
    } catch (e) {
      setSaveMessage(`Error: ${action}失败: ${e.message}`);
    } finally {
      setActionPending(false);
    }
  }

  async function handleDelete() {
    if (!characterId || actionPending) return;
    const ok = await dialog.confirm({
      title: '永久删除角色卡',
      message: '确定要永久删除这个角色卡吗？此操作不可撤销！',
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;
    setActionPending(true);
    setSaveMessage('');
    try {
      await characterAdmin.delete(characterId, true); // permanent delete
      navigate('/');
    } catch (e) {
      setSaveMessage(`Error: Delete failed: ${e.message}`);
      setActionPending(false);
    }
  }

  const saveDisabled = saving || actionPending || loading
    || Boolean(characterId && loadedCharacterId !== characterId);
  const primaryAction = useMemo(() => (
    <Button type="button" size="lg" onClick={handleSave} disabled={saveDisabled}>
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存角色'}
    </Button>
  ), [actionPending, characterId, formData, loadedCharacterId, loading, saving]);

  useEffect(() => {
    setPrimaryAction(primaryAction);
    return () => setPrimaryAction(null);
  }, [primaryAction, setPrimaryAction]);

  if (characterId && (loading || loadedCharacterId !== characterId) && !loadError) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center text-muted-foreground" role="status">
        <Loader2 className="h-7 w-7 animate-spin" aria-hidden="true" />
        <span className="sr-only">正在加载角色档案</span>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center px-4">
        <div className="w-full max-w-md border border-destructive/30 bg-card p-6 text-center" role="alert">
          <p className="break-words text-sm text-destructive">{loadError}</p>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Button type="button" variant="outline" onClick={() => navigate('/')}>返回</Button>
            <Button type="button" onClick={() => setReloadVersion(version => version + 1)}>
              <RefreshCw aria-hidden="true" /> 重试
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const StepComponent = [StepIdentity, StepPersonality, StepSpeechStyle, StepBackground, StepInteraction][currentStep];
  const currentStepMeta = STEPS[currentStep];
  const displayName = formData.meta?.display_name || formData.meta?.name || '未命名角色';
  const aliases = formData.meta?.aliases || [];

  const notice = saveMessage ? (
    <div
      className={`mb-4 flex items-start gap-2 border px-3 py-3 text-sm ${
        saveMessage.includes('Error')
          ? 'border-destructive/30 bg-destructive/5 text-destructive'
          : 'border-primary/30 bg-primary/5 text-foreground'
      }`}
      role={saveMessage.includes('Error') ? 'alert' : 'status'}
      aria-live={saveMessage.includes('Error') ? 'assertive' : 'polite'}
    >
      {saveMessage.includes('Error')
        ? <Trash2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        : <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />}
      <span>{saveMessage}</span>
    </div>
  ) : null;

  const directory = (
    <div className="p-3">
      <div className="border-b border-border px-2 pb-3">
        <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">章节目录</p>
        <p className="mt-1 truncate font-archive-serif text-base font-semibold text-foreground">{displayName}</p>
      </div>
      <nav aria-label="角色编辑章节" className="mt-2 space-y-1">
        {STEPS.map((step, index) => {
          const Icon = step.Icon;
          const active = index === currentStep;
          const complete = index < currentStep;
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setCurrentStep(index)}
              aria-current={active ? 'step' : undefined}
              className={`flex min-h-14 w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
                active
                  ? 'border-primary/40 bg-primary/10 text-foreground'
                  : 'border-transparent text-muted-foreground hover:border-border hover:bg-muted/35 hover:text-foreground'
              }`}
            >
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${
                active || complete ? 'border-primary/35 bg-background text-primary' : 'border-border bg-background'
              }`}>
                {complete ? <Check className="h-4 w-4" aria-hidden="true" /> : <Icon className="h-4 w-4" aria-hidden="true" />}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-medium">{step.label}</span>
                <span className="mt-0.5 hidden truncate text-[10px] text-muted-foreground lg:block">{step.description}</span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="mt-4 border-t border-border pt-4">
        <p className="px-2 text-[10px] uppercase text-muted-foreground">档案工具</p>
        <div className="mt-2 grid gap-2">
          {characterId ? (
            <Button type="button" variant="outline" onClick={handleExportFile} className="w-full justify-start">
              <Download aria-hidden="true" /> 导出 JSON
            </Button>
          ) : (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                onChange={handleImportFile}
                className="hidden"
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                className="w-full justify-start"
              >
                <Upload aria-hidden="true" /> 导入 JSON
              </Button>
            </>
          )}
          {characterId && (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleToggleActive}
                disabled={actionPending}
                className="w-full justify-start"
              >
                {isActive ? <PowerOff aria-hidden="true" /> : <Power aria-hidden="true" />}
                {isActive ? '停用角色' : '启用角色'}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={handleDelete}
                disabled={actionPending}
                className="w-full justify-start"
              >
                <Trash2 aria-hidden="true" /> 永久删除
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );

  const editor = (
    <div className="min-w-0">
      <div className="flex min-h-20 items-center gap-3 border-b border-border bg-muted/20 px-4 py-4 sm:px-6">
        <span className="font-archive-mono text-xs tabular-nums text-muted-foreground">
          {String(currentStep + 1).padStart(2, '0')}
        </span>
        <div className="min-w-0">
          <h2 className="font-archive-serif text-lg font-semibold text-foreground">{currentStepMeta.label}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{currentStepMeta.description}</p>
        </div>
      </div>
      <div className="min-h-[520px] min-w-0 p-4 font-archive-serif sm:p-6">
        <StepComponent
          formData={formData}
          updateField={updateField}
          characterId={characterId}
          showAvatar
          showRelationships
          showVoice
        />
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-4 sm:px-6">
        <Button
          type="button"
          variant="outline"
          onClick={() => setCurrentStep(prev => Math.max(0, prev - 1))}
          disabled={currentStep === 0}
        >
          <ChevronLeft aria-hidden="true" /> 上一章
        </Button>
        <span className="font-archive-mono text-xs tabular-nums text-muted-foreground">
          {currentStep + 1} / {STEPS.length}
        </span>
        {currentStep < STEPS.length - 1 ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => setCurrentStep(prev => Math.min(STEPS.length - 1, prev + 1))}
          >
            下一章 <ChevronRight aria-hidden="true" />
          </Button>
        ) : (
          <Button type="button" onClick={handleSave} disabled={saveDisabled}>
            {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
            保存
          </Button>
        )}
      </div>
    </div>
  );

  const summary = (
    <div className="p-4">
      <div className="flex items-start gap-3 border-b border-border pb-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted/35">
          {formData.avatar_url ? (
            <img src={formData.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            <Fingerprint className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          )}
        </div>
        <div className="min-w-0">
          <h2 className="truncate font-archive-serif text-base font-semibold text-foreground">{displayName}</h2>
          <p className="mt-1 break-all font-archive-mono text-[10px] text-muted-foreground">
            {formData.character_id || '保存时自动生成 ID'}
          </p>
        </div>
      </div>
      <dl className="text-xs">
        {[
          ['状态', isActive ? '启用' : '停用', false],
          ['版本', formData.version || '1.0.0', true],
          ['当前章节', `${currentStep + 1} / ${STEPS.length}`, true],
          ['姓名', formData.meta?.name || '未填写', false],
          ['职业', formData.identity?.occupation || '未填写', false],
          ['语言', formData.speech_style?.language || '未填写', true],
          ['别名', aliases.length, true],
          ['最后更新', formData.meta?.last_updated || '尚未保存', true],
        ].map(([label, value, mono]) => (
          <div key={label} className="grid grid-cols-[80px_minmax(0,1fr)] gap-3 border-b border-border py-3 last:border-b-0">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className={`min-w-0 break-words text-right text-foreground ${mono ? 'font-archive-mono tabular-nums' : ''}`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 border border-border bg-muted/25 p-3">
        <p className="text-xs font-medium text-foreground">角色卡摘要</p>
        <p className="mt-2 font-archive-serif text-sm leading-6 text-muted-foreground">
          {formData.identity?.core_identity_summary
            || formData.identity?.appearance
            || '在身份章节写下角色的核心侧写。'}
        </p>
      </div>
    </div>
  );

  const mobileAction = (
    <Button type="button" size="lg" onClick={handleSave} disabled={saveDisabled} className="w-full">
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存角色'}
    </Button>
  );

  return (
    <ArchiveEditorWorkspace
      indexLabel={characterId ? 'Character archive / edit' : 'Character archive / new'}
      title={characterId ? '编辑角色档案' : '新建角色档案'}
      description="按章节整理角色卡，并在右侧实时核对身份、版本与状态。"
      directory={directory}
      editor={editor}
      summary={summary}
      mobileAction={mobileAction}
      notice={notice}
    />
  );
}
