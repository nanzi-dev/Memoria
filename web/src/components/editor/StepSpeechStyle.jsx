import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, MessageSquare, Mic, Upload, Volume2, X } from 'lucide-react';
import { characterAdmin, speechApi } from '../../api/memoria';
import TagInput from './TagInput';

const BUILTIN_VOICES = [
  'alloy', 'ash', 'ballad', 'cedar', 'coral', 'echo', 'fable',
  'marin', 'nova', 'onyx', 'sage', 'shimmer', 'verse',
];
const MAX_VOICE_FILE_BYTES = 10 * 1024 * 1024;
const VOICE_ACCEPT = 'audio/mpeg,audio/wav,audio/x-wav,audio/m4a,audio/x-m4a,.mp3,.wav,.m4a';
const ALLOWED_VOICE_TYPES = new Set([
  'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/m4a', 'audio/x-m4a',
]);

function validateVoiceFile(file) {
  if (!file) return '请选择音频文件';
  if (file.size > MAX_VOICE_FILE_BYTES) return '音频文件不能超过 10 MiB';
  if (file.type && !ALLOWED_VOICE_TYPES.has(file.type.toLowerCase())) {
    return '仅支持 MP3、M4A 或 WAV 音频';
  }
  return null;
}

function statusLabel(status) {
  return {
    unconfigured: '未配置',
    pending: '配置中',
    ready: '已就绪',
    unavailable: '服务不可用',
    failed: '配置失败',
  }[status] || status || '未配置';
}

export default function StepSpeechStyle({ formData, updateField, characterId = null, showVoice = true }) {
  const s = formData.speech_style || {};
  const voice = formData.voice || {};
  const [voiceStatus, setVoiceStatus] = useState(null);
  const [speechConfiguration, setSpeechConfiguration] = useState(null);
  const [voiceError, setVoiceError] = useState('');
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [consentLocale, setConsentLocale] = useState('zh-CN');
  const [consentName, setConsentName] = useState('');
  const [sampleName, setSampleName] = useState('');
  const [referenceTranscript, setReferenceTranscript] = useState('');
  const [consentFile, setConsentFile] = useState(null);
  const [sampleFile, setSampleFile] = useState(null);
  const consentInputRef = useRef(null);
  const sampleInputRef = useRef(null);

  const applyVoiceStatus = useCallback((status) => {
    setVoiceStatus(status);
    updateField('voice.customVoiceId', status?.custom_voice_id || null);
    updateField('voice.customVoiceStatus', status?.custom_voice_status || 'unconfigured');
    if (status?.consent_locale) setConsentLocale(status.consent_locale);
  }, [updateField]);

  useEffect(() => {
    if (!showVoice) {
      setSpeechConfiguration(null);
      return undefined;
    }
    let cancelled = false;
    speechApi.getConfiguration()
      .then((configuration) => { if (!cancelled) setSpeechConfiguration(configuration); })
      .catch(() => { if (!cancelled) setSpeechConfiguration(null); });
    return () => { cancelled = true; };
  }, [showVoice]);

  useEffect(() => {
    const builtinVoices = speechConfiguration?.builtin_voices;
    const defaultVoice = speechConfiguration?.default_builtin_voice;
    if (
      showVoice
      && Array.isArray(builtinVoices)
      && builtinVoices.length
      && defaultVoice
      && !builtinVoices.includes(voice.builtinVoice)
    ) {
      updateField('voice.builtinVoice', defaultVoice);
    }
  }, [showVoice, speechConfiguration, updateField, voice.builtinVoice]);

  useEffect(() => {
    if (!showVoice || !characterId) {
      setVoiceStatus(null);
      return undefined;
    }
    let cancelled = false;
    setVoiceLoading(true);
    setVoiceError('');
    characterAdmin.getVoiceStatus(characterId)
      .then(status => { if (!cancelled) applyVoiceStatus(status); })
      .catch(error => { if (!cancelled) setVoiceError(error.message); })
      .finally(() => { if (!cancelled) setVoiceLoading(false); });
    return () => { cancelled = true; };
  }, [applyVoiceStatus, characterId, showVoice]);

  async function uploadConsent() {
    const validationError = validateVoiceFile(consentFile);
    if (validationError) { setVoiceError(validationError); return; }
    setVoiceLoading(true);
    setVoiceError('');
    try {
      const status = await characterAdmin.uploadVoiceConsent(
        characterId,
        consentLocale,
        consentFile,
        consentName,
      );
      applyVoiceStatus(status);
      setConsentFile(null);
      if (consentInputRef.current) consentInputRef.current.value = '';
    } catch (error) {
      setVoiceError(error.message);
      try { applyVoiceStatus(await characterAdmin.getVoiceStatus(characterId)); } catch {}
    } finally {
      setVoiceLoading(false);
    }
  }

  async function createCustomVoice() {
    const validationError = validateVoiceFile(sampleFile);
    if (validationError) { setVoiceError(validationError); return; }
    if (!referenceTranscript.trim()) {
      setVoiceError('请填写声音样本对应的朗读文本');
      return;
    }
    setVoiceLoading(true);
    setVoiceError('');
    try {
      const status = await characterAdmin.createCustomVoice(
        characterId,
        sampleFile,
        referenceTranscript.trim(),
        sampleName,
      );
      applyVoiceStatus(status);
      setSampleFile(null);
      setReferenceTranscript('');
      if (sampleInputRef.current) sampleInputRef.current.value = '';
    } catch (error) {
      setVoiceError(error.message);
      try { applyVoiceStatus(await characterAdmin.getVoiceStatus(characterId)); } catch {}
    } finally {
      setVoiceLoading(false);
    }
  }

  async function unbindCustomVoice() {
    setVoiceLoading(true);
    setVoiceError('');
    try {
      applyVoiceStatus(await characterAdmin.unbindCustomVoice(characterId));
    } catch (error) {
      setVoiceError(error.message);
    } finally {
      setVoiceLoading(false);
    }
  }

  const customStatus = voiceStatus?.custom_voice_status || voice.customVoiceStatus || 'unconfigured';
  const speechConfigured = voiceStatus?.speech_configured !== false;
  const consentPhrase = voiceStatus?.consent_phrases?.[consentLocale] || '';
  const builtinVoices = Array.isArray(speechConfiguration?.builtin_voices)
    && speechConfiguration.builtin_voices.length
    ? speechConfiguration.builtin_voices
    : BUILTIN_VOICES;
  const defaultBuiltinVoice = speechConfiguration?.default_builtin_voice || builtinVoices[0];
  const selectedBuiltinVoice = builtinVoices.includes(voice.builtinVoice)
    ? voice.builtinVoice
    : defaultBuiltinVoice;
  const customVoiceSupported = speechConfiguration?.custom_voice_supported === true;
  const providerLabel = speechConfiguration?.provider_label || 'MiniMax';

  return (
    <div className="space-y-6">
      <div className="mb-4 flex items-center gap-2">
        <MessageSquare className="h-5 w-5 text-primary" aria-hidden="true" />
        <h3 className="font-archive-serif text-lg font-semibold text-foreground">语言风格 Speech Style</h3>
      </div>

      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">语气 Tone Register</label>
        <input type="text" value={s.tone_register || ''} onChange={(e) => updateField('speech_style.tone_register', e.target.value)} className="min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-serif text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" placeholder="e.g. 简短、直接..." />
      </div>

      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">用词习惯 Vocabulary Notes</label>
        <textarea value={s.vocabulary_notes || ''} onChange={(e) => updateField('speech_style.vocabulary_notes', e.target.value)} rows={3} className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-archive-serif text-base leading-7 text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" placeholder="Describe vocabulary habits..." />
      </div>

      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">默认正式程度 Formality Default</label>
        <input type="text" value={s.formality_default || ''} onChange={(e) => updateField('speech_style.formality_default', e.target.value)} className="min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-serif text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" placeholder="e.g. 疏离克制..." />
      </div>

      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">语言 Language</label>
        <select value={s.language || 'zh-CN'} onChange={(e) => updateField('speech_style.language', e.target.value)} className="min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-mono text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <option value="zh-CN">中文 (zh-CN)</option>
          <option value="en-US">English (en-US)</option>
        </select>
      </div>

      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">常用句式 Sentence Patterns</label>
        <TagInput tags={s.sentence_patterns || []} onChange={(tags) => updateField('speech_style.sentence_patterns', tags)} placeholder="e.g. 短句为主..." />
      </div>
      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">口头禅 Catchphrases</label>
        <TagInput tags={s.catchphrases || []} onChange={(tags) => updateField('speech_style.catchphrases', tags)} placeholder="e.g. 没必要解释..." />
      </div>
      <div>
        <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">禁忌用语 Things Never to Say</label>
        <TagInput tags={s.things_never_to_say || []} onChange={(tags) => updateField('speech_style.things_never_to_say', tags)} placeholder="e.g. 不会主动诉苦..." />
      </div>

      {showVoice && (
        <div className="space-y-5 border-t border-border pt-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Volume2 className="h-5 w-5 text-primary" aria-hidden="true" />
              <h3 className="font-archive-serif text-lg font-semibold text-foreground">角色语音 Voice</h3>
            </div>
            <span className="rounded-md border border-border bg-muted/40 px-2 py-1 font-archive-mono text-[10px] text-muted-foreground">AI-generated voice</span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">Built-in Voice · {providerLabel}</label>
              <select value={selectedBuiltinVoice} onChange={(e) => updateField('voice.builtinVoice', e.target.value)} className="min-h-11 w-full rounded-md border border-input bg-background px-3 font-archive-mono text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {builtinVoices.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </div>
            <div className="flex items-end">
              <div className="flex min-h-[44px] w-full items-center justify-between rounded border border-border bg-muted/25 px-3 font-archive-mono text-xs text-muted-foreground">
                <span>Custom Voice</span>
                <span className="font-bold">{customVoiceSupported ? (voiceLoading ? '同步中' : statusLabel(customStatus)) : '当前厂商不支持'}</span>
              </div>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block font-archive-mono text-[11px] uppercase text-muted-foreground">TTS Instructions</label>
            <textarea value={voice.ttsInstructions || ''} onChange={(e) => updateField('voice.ttsInstructions', e.target.value)} rows={3} className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-archive-serif text-base leading-7 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" placeholder="Describe pace, tone, emotion, and delivery..." />
          </div>

          {!characterId && (
            <div className="flex items-start gap-2 rounded border border-border bg-muted/40 px-3 py-2 text-xs leading-5 text-muted-foreground">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              保存角色后可录入同意声明并创建 Custom Voice。内置语音仍可直接设置。
            </div>
          )}

          {characterId && speechConfiguration && !customVoiceSupported && (
            <div className="flex items-start gap-2 rounded border border-border bg-muted/40 px-3 py-2 text-xs leading-5 text-muted-foreground">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              当前语音厂商不支持持久化 Custom Voice；将继续使用内置音色。
            </div>
          )}

          {characterId && customVoiceSupported && !speechConfigured && (
            <div className="flex items-start gap-2 rounded border border-border bg-muted/40 px-3 py-2 text-xs leading-5 text-muted-foreground">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              当前服务未配置 Custom Voice。内置语音与 TTS instructions 仍会作为回退方案保存。
            </div>
          )}

          {voiceError && (
            <div role="alert" className="flex items-start gap-2 rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs leading-5 text-destructive">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 break-words">{voiceError}</span>
              <button type="button" onClick={() => setVoiceError('')} className="flex h-11 w-11 shrink-0 items-center justify-center" aria-label="关闭语音错误"><X size={14} /></button>
            </div>
          )}

          {characterId && customVoiceSupported && speechConfigured && (
            <div className="space-y-5 rounded border border-border bg-muted/25 p-3 sm:p-4">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Mic size={15} className="text-muted-foreground" />
                  <h4 className="font-archive-mono text-sm font-bold text-muted-foreground">1. 同意声明 Consent</h4>
                </div>
                <div className="grid grid-cols-2 overflow-hidden rounded border border-border">
                  {['zh-CN', 'en-US'].map(locale => (
                    <button key={locale} type="button" onClick={() => setConsentLocale(locale)} className={`min-h-[44px] border-r border-border font-archive-mono text-xs last:border-r-0 ${consentLocale === locale ? 'bg-primary/10 text-muted-foreground' : 'text-muted-foreground hover:bg-muted/40'}`}>{locale}</button>
                  ))}
                </div>
                {consentPhrase && (
                  <div className="rounded border border-border bg-background/70 px-3 py-2.5 font-archive-mono text-xs leading-6 text-muted-foreground">{consentPhrase}</div>
                )}
                <input type="text" value={consentName} onChange={(e) => setConsentName(e.target.value)} placeholder="Consent name (optional)" className="w-full px-2 py-1.5 text-sm font-archive-mono text-foreground bg-transparent border-b border-border focus:border-border focus:outline-none" />
                <input ref={consentInputRef} type="file" accept={VOICE_ACCEPT} onChange={(e) => { setConsentFile(e.target.files?.[0] || null); setVoiceError(''); }} className="hidden" />
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button type="button" onClick={() => consentInputRef.current?.click()} disabled={voiceLoading} className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded border border-border bg-background/60 px-3 text-xs font-archive-mono text-muted-foreground disabled:opacity-40"><Upload size={14} />{consentFile?.name || '选择同意声明录音'}</button>
                  <button type="button" onClick={uploadConsent} disabled={voiceLoading || !consentFile} className="flex min-h-[44px] items-center justify-center gap-2 rounded border border-border bg-primary/10 px-4 text-xs font-bold font-archive-mono text-muted-foreground disabled:opacity-35">{voiceLoading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}上传声明</button>
                </div>
              </div>

              <div className="space-y-3 border-t border-border pt-4">
                <div className="flex items-center gap-2">
                  <Volume2 size={15} className="text-muted-foreground" />
                  <h4 className="font-archive-mono text-sm font-bold text-muted-foreground">2. 声音样本 Voice Sample</h4>
                </div>
                <p className="font-archive-mono text-[11px] leading-5 text-muted-foreground">使用 8 秒以内、环境安静、单人清晰朗读的 MP3、M4A 或 WAV 音频。单个文件上限 10 MiB。</p>
                <input type="text" value={sampleName} onChange={(e) => setSampleName(e.target.value)} placeholder="Voice name (optional)" className="w-full px-2 py-1.5 text-sm font-archive-mono text-foreground bg-transparent border-b border-border focus:border-border focus:outline-none" />
                <textarea value={referenceTranscript} onChange={(e) => setReferenceTranscript(e.target.value)} rows={3} placeholder="填写此声音样本中朗读的原文" className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-archive-serif text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" />
                <input ref={sampleInputRef} type="file" accept={VOICE_ACCEPT} onChange={(e) => { setSampleFile(e.target.files?.[0] || null); setVoiceError(''); }} className="hidden" />
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button type="button" onClick={() => sampleInputRef.current?.click()} disabled={voiceLoading} className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded border border-border bg-background/60 px-3 text-xs font-archive-mono text-muted-foreground disabled:opacity-40"><Upload size={14} />{sampleFile?.name || '选择声音样本'}</button>
                  <button type="button" onClick={createCustomVoice} disabled={voiceLoading || !sampleFile || !referenceTranscript.trim() || !voiceStatus?.consent_id} className="flex min-h-[44px] items-center justify-center gap-2 rounded border border-border bg-primary/10 px-4 text-xs font-bold font-archive-mono text-muted-foreground disabled:opacity-35">{voiceLoading ? <Loader2 size={14} className="animate-spin" /> : <Volume2 size={14} />}创建声音</button>
                </div>
                {!voiceStatus?.consent_id && <p className="font-archive-mono text-[11px] text-muted-foreground">请先上传有效的同意声明录音。</p>}
              </div>

              {(voiceStatus?.custom_voice_id || customStatus === 'ready') && (
                <button type="button" onClick={unbindCustomVoice} disabled={voiceLoading} className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded border border-destructive/30 text-xs font-archive-mono text-destructive hover:bg-destructive/5 disabled:opacity-40"><X size={14} />解绑 Custom Voice</button>
              )}
            </div>
          )}

          {voiceStatus?.error && !voiceError && (
            <div className="font-archive-mono text-xs leading-5 text-destructive">{voiceStatus.error_category ? `[${voiceStatus.error_category}] ` : ''}{voiceStatus.error}</div>
          )}
        </div>
      )}
    </div>
  );
}
