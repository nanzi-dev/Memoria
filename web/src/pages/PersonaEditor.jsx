import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  Check,
  Contact,
  ImagePlus,
  Link,
  Loader2,
  RefreshCw,
  Save,
  Upload,
  User,
} from 'lucide-react';
import { userApi } from '../api/memoria';
import { useUser } from '../context/UserContext';

const EMPTY_CARD = {
  display_name: '',
  avatar_url: null,
  gender: '',
  pronouns: '',
  age: '',
  species: '',
  occupation: '',
  appearance: '',
  personality: '',
  background: '',
  goals: '',
};

const TEXT_LIMITS = {
  display_name: 50,
  gender: 30,
  pronouns: 50,
  species: 80,
  occupation: 120,
  appearance: 4000,
  personality: 4000,
  background: 8000,
  goals: 4000,
};

const inputClass = 'min-h-[44px] w-full rounded-lg border border-cyber-green/15 bg-[#0b0b0c] px-3 text-sm text-zinc-200 outline-none transition-colors placeholder:text-zinc-700 focus:border-cyber-green/45 focus:ring-2 focus:ring-cyber-green/10 disabled:opacity-45';
const textareaClass = `${inputClass} min-h-[132px] resize-y py-3 font-character leading-6`;

function normalizeCard(card) {
  return {
    ...EMPTY_CARD,
    ...card,
    age: card?.age ?? '',
  };
}

function validateCard(card) {
  const errors = {};
  if (!card.display_name.trim()) errors.display_name = '角色名称不能为空';

  for (const [field, limit] of Object.entries(TEXT_LIMITS)) {
    if (String(card[field] || '').length > limit) {
      errors[field] = `不能超过 ${limit} 个字符`;
    }
  }

  if (card.age !== '') {
    const age = Number(card.age);
    if (!Number.isInteger(age) || age < 0 || age > 10000) {
      errors.age = '年龄必须是 0 到 10000 之间的整数';
    }
  }
  return errors;
}

function Field({ id, label, error, limit, value, children }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-[11px] font-medium text-cyber-green/65">
          {label}
        </label>
        {limit && (
          <span className={`text-[9px] tabular-nums ${String(value || '').length > limit ? 'text-red-300' : 'text-zinc-700'}`}>
            {String(value || '').length}/{limit}
          </span>
        )}
      </div>
      {children}
      {error && (
        <p className="mt-1.5 flex items-center gap-1 text-[10px] text-red-300/85" role="alert">
          <AlertCircle size={11} />
          {error}
        </p>
      )}
    </div>
  );
}

function SectionTitle({ icon: Icon, title }) {
  return (
    <div className="flex items-center gap-2 border-b border-white/[0.06] pb-3">
      <Icon size={15} className="text-cyan-200/70" />
      <h2 className="text-xs font-bold tracking-wider text-zinc-200">{title}</h2>
    </div>
  );
}

export default function PersonaEditor() {
  const navigate = useNavigate();
  const { user, loading: userLoading, refresh } = useUser();
  const fileRef = useRef(null);
  const [card, setCard] = useState(EMPTY_CARD);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [avatarSaving, setAvatarSaving] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);

  const errors = useMemo(() => validateCard(card), [card]);

  useEffect(() => {
    if (userLoading) return;
    if (!user) {
      navigate('/', { replace: true });
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError('');
    userApi.getCharacterCard()
      .then(nextCard => {
        if (!cancelled) setCard(normalizeCard(nextCard));
      })
      .catch(err => {
        if (!cancelled) setError(err.message || '角色卡加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [navigate, reloadVersion, user?.user_id, userLoading]);

  useEffect(() => {
    if (!success) return undefined;
    const timer = window.setTimeout(() => setSuccess(''), 4000);
    return () => window.clearTimeout(timer);
  }, [success]);

  const updateField = (field, value) => {
    setCard(current => ({ ...current, [field]: value }));
  };

  const handleSave = async (event) => {
    event.preventDefault();
    setSubmitted(true);
    setError('');
    setSuccess('');
    if (Object.keys(errors).length) {
      document.getElementById(`persona-${Object.keys(errors)[0]}`)?.focus();
      return;
    }

    setSaving(true);
    try {
      const payload = {
        display_name: card.display_name.trim(),
        gender: card.gender.trim(),
        pronouns: card.pronouns.trim(),
        age: card.age === '' ? null : Number(card.age),
        species: card.species.trim(),
        occupation: card.occupation.trim(),
        appearance: card.appearance.trim(),
        personality: card.personality.trim(),
        background: card.background.trim(),
        goals: card.goals.trim(),
      };
      const updated = await userApi.updateCharacterCard(payload);
      setCard(normalizeCard(updated));
      await refresh();
      setSubmitted(false);
      setSuccess('角色卡已保存，将从下一条消息开始生效');
    } catch (err) {
      setError(err.message || '角色卡保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      setError('头像文件不能超过 8 MB');
      event.target.value = '';
      return;
    }

    setAvatarSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await userApi.uploadCharacterCardAvatar(file);
      setCard(normalizeCard(updated));
      await refresh();
      setSuccess('扮演头像已更新');
    } catch (err) {
      setError(err.message || '头像上传失败');
    } finally {
      setAvatarSaving(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleAvatarUrl = async () => {
    setAvatarSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await userApi.setCharacterCardAvatarUrl(avatarUrl.trim());
      setCard(normalizeCard(updated));
      setAvatarUrl('');
      await refresh();
      setSuccess(avatarUrl.trim() ? '扮演头像已更新' : '扮演头像已清除');
    } catch (err) {
      setError(err.message || '头像设置失败');
    } finally {
      setAvatarSaving(false);
    }
  };

  if (userLoading || loading) {
    return (
      <div className="min-h-dvh character-editor-page flex items-center justify-center" role="status">
        <Loader2 className="animate-spin text-cyber-green" size={32} />
        <span className="sr-only">正在加载角色卡</span>
      </div>
    );
  }

  if (error && !card.display_name) {
    return (
      <div className="min-h-dvh character-editor-page flex items-center justify-center px-4">
        <div className="w-full max-w-md rounded-lg border border-red-400/25 bg-[#120f17] p-6 text-center">
          <AlertCircle className="mx-auto text-red-300/70" size={28} />
          <p className="mt-3 break-words text-sm text-red-200/80">{error}</p>
          <div className="mt-5 flex justify-center gap-2">
            <button type="button" onClick={() => navigate('/')} className="min-h-[44px] rounded-lg border border-white/10 px-4 text-xs text-zinc-400">
              返回
            </button>
            <button type="button" onClick={() => setReloadVersion(value => value + 1)} className="flex min-h-[44px] items-center gap-2 rounded-lg border border-cyber-green/25 bg-cyber-green/10 px-4 text-xs text-cyber-green">
              <RefreshCw size={14} /> 重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh character-editor-page font-mono">
      <header className="sticky top-0 z-20 border-b border-cyber-green/18 bg-[#100d14]/92 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-3 py-3 sm:px-5">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] items-center gap-2 rounded-lg px-2 text-sm text-cyber-green/60 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green"
          >
            <ArrowLeft size={17} /> 返回
          </button>
          <div className="order-first basis-full text-center sm:order-none sm:basis-auto sm:text-left">
            <h1 className="font-display text-base tracking-widest text-cyber-green">PLAYER PERSONA</h1>
            <p className="mt-1 text-[10px] text-cyan-200/40">{card.node_id || user?.role_summary?.node_id}</p>
          </div>
          <button
            type="submit"
            form="persona-form"
            disabled={saving || avatarSaving}
            className="flex min-h-[44px] items-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-4 text-sm font-bold text-cyber-green transition-colors hover:bg-cyber-green/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            {saving ? '保存中' : '保存角色卡'}
          </button>
        </div>
      </header>

      <main className="relative z-[1] mx-auto grid max-w-6xl gap-5 px-3 py-5 sm:px-5 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
        <aside className="space-y-4 lg:sticky lg:top-[86px]">
          <section className="memoria-glass rounded-lg p-4">
            <SectionTitle icon={ImagePlus} title="扮演头像" />
            <div className="mt-5 flex flex-col items-center">
              <div className="relative h-32 w-32 overflow-hidden rounded-full border-2 border-cyan-300/45 bg-[#08090b] shadow-[0_0_28px_rgba(103,232,249,0.1)]">
                {card.avatar_url ? (
                  <img src={card.avatar_url} alt={`${card.display_name || '角色'}的扮演头像`} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-cyan-200/25">
                    <Contact size={52} />
                  </div>
                )}
                {avatarSaving && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/70">
                    <Loader2 size={24} className="animate-spin text-cyan-200" />
                  </div>
                )}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                onChange={handleAvatarUpload}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={avatarSaving}
                className="mt-4 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg border border-cyan-300/20 bg-cyan-300/[0.06] text-xs text-cyan-100/80 transition-colors hover:bg-cyan-300/10 disabled:opacity-40"
              >
                <Upload size={15} /> 上传扮演头像
              </button>
              <div className="mt-2 flex w-full gap-2">
                <label htmlFor="persona-avatar-url" className="sr-only">扮演头像网络地址</label>
                <input
                  id="persona-avatar-url"
                  type="url"
                  value={avatarUrl}
                  onChange={event => setAvatarUrl(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      handleAvatarUrl();
                    }
                  }}
                  placeholder="图片 URL"
                  className={`${inputClass} min-w-0 flex-1 text-xs`}
                />
                <button
                  type="button"
                  onClick={handleAvatarUrl}
                  disabled={avatarSaving || (!avatarUrl.trim() && !card.avatar_url)}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 text-cyan-100/70 hover:bg-cyan-300/10 disabled:opacity-30"
                  aria-label={avatarUrl.trim() ? '从链接设置扮演头像' : '清除扮演头像'}
                  title={avatarUrl.trim() ? '设置头像链接' : '清除头像'}
                >
                  <Link size={16} />
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-white/[0.07] bg-black/15 p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] tracking-wider text-zinc-600">账户身份</span>
              <BadgeCheck size={14} className="text-cyber-green/45" />
            </div>
            <div className="mt-3 flex items-center gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full border border-cyber-green/20 bg-[#0b0b0c]">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt={`${user.username}的账户头像`} className="h-full w-full object-cover" />
                ) : (
                  <User size={18} className="text-cyber-green/25" />
                )}
              </div>
              <div className="min-w-0">
                <div className="truncate text-xs text-zinc-300">{user?.username}</div>
                <div className="mt-1 truncate text-[9px] text-zinc-700">{user?.user_id}</div>
              </div>
            </div>
          </section>
        </aside>

        <form id="persona-form" onSubmit={handleSave} className="space-y-5">
          {(error || success) && (
            <div
              className={`flex items-start gap-2 rounded-lg border px-3 py-3 text-xs ${
                error
                  ? 'border-red-400/20 bg-red-400/[0.055] text-red-200/85'
                  : 'border-emerald-300/20 bg-emerald-300/[0.05] text-emerald-200/85'
              }`}
              role={error ? 'alert' : 'status'}
            >
              {error ? <AlertCircle size={15} className="mt-0.5 shrink-0" /> : <Check size={15} className="shrink-0" />}
              <span>{error || success}</span>
            </div>
          )}

          <section className="memoria-glass rounded-lg p-4 sm:p-5">
            <SectionTitle icon={Contact} title="身份信息" />
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field id="persona-display_name" label="角色名称 *" error={submitted && errors.display_name} limit={TEXT_LIMITS.display_name} value={card.display_name}>
                <input
                  id="persona-display_name"
                  value={card.display_name}
                  maxLength={TEXT_LIMITS.display_name}
                  onChange={event => updateField('display_name', event.target.value)}
                  className={`${inputClass} ${submitted && errors.display_name ? 'border-red-400/35' : ''}`}
                  autoComplete="nickname"
                />
              </Field>
              <Field id="persona-age" label="年龄" error={submitted && errors.age}>
                <input
                  id="persona-age"
                  type="number"
                  min="0"
                  max="10000"
                  step="1"
                  value={card.age}
                  onChange={event => updateField('age', event.target.value)}
                  className={`${inputClass} ${submitted && errors.age ? 'border-red-400/35' : ''}`}
                />
              </Field>
              <Field id="persona-gender" label="性别" error={submitted && errors.gender} limit={TEXT_LIMITS.gender} value={card.gender}>
                <input id="persona-gender" value={card.gender} maxLength={TEXT_LIMITS.gender} onChange={event => updateField('gender', event.target.value)} className={inputClass} />
              </Field>
              <Field id="persona-pronouns" label="称谓 / 代词" error={submitted && errors.pronouns} limit={TEXT_LIMITS.pronouns} value={card.pronouns}>
                <input id="persona-pronouns" value={card.pronouns} maxLength={TEXT_LIMITS.pronouns} onChange={event => updateField('pronouns', event.target.value)} className={inputClass} />
              </Field>
              <Field id="persona-species" label="种族 / 物种" error={submitted && errors.species} limit={TEXT_LIMITS.species} value={card.species}>
                <input id="persona-species" value={card.species} maxLength={TEXT_LIMITS.species} onChange={event => updateField('species', event.target.value)} className={inputClass} />
              </Field>
              <Field id="persona-occupation" label="职业 / 身份" error={submitted && errors.occupation} limit={TEXT_LIMITS.occupation} value={card.occupation}>
                <input id="persona-occupation" value={card.occupation} maxLength={TEXT_LIMITS.occupation} onChange={event => updateField('occupation', event.target.value)} className={inputClass} />
              </Field>
            </div>
          </section>

          {[
            ['appearance', '外貌', User],
            ['personality', '性格', BadgeCheck],
            ['background', '背景经历', Contact],
            ['goals', '当前目标', Check],
          ].map(([field, label, Icon]) => (
            <section key={field} className="memoria-glass rounded-lg p-4 sm:p-5">
              <SectionTitle icon={Icon} title={label} />
              <div className="mt-4">
                <Field
                  id={`persona-${field}`}
                  label={label}
                  error={submitted && errors[field]}
                  limit={TEXT_LIMITS[field]}
                  value={card[field]}
                >
                  <textarea
                    id={`persona-${field}`}
                    value={card[field]}
                    maxLength={TEXT_LIMITS[field]}
                    onChange={event => updateField(field, event.target.value)}
                    className={textareaClass}
                  />
                </Field>
              </div>
            </section>
          ))}

          <div className="flex justify-end pb-8">
            <button
              type="submit"
              disabled={saving || avatarSaving}
              className="flex min-h-[48px] w-full items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-5 text-sm font-bold text-cyber-green transition-colors hover:bg-cyber-green/20 disabled:opacity-40 sm:w-auto"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              {saving ? '保存中' : '保存角色卡'}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
