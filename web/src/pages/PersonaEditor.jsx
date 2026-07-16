import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
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
import { useArchiveShell } from '@/archive/ArchiveShell';
import ArchiveEditorWorkspace from '@/archive/ArchiveEditorWorkspace';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

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

const PROFILE_FIELDS = [
  'display_name',
  'gender',
  'pronouns',
  'age',
  'species',
  'occupation',
  'appearance',
  'personality',
  'background',
  'goals',
];

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
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-xs font-medium text-foreground">
          {label}
        </label>
        {limit && (
          <span
            className={`font-archive-mono text-[10px] tabular-nums ${
              String(value || '').length > limit ? 'text-destructive' : 'text-muted-foreground'
            }`}
          >
            {String(value || '').length}/{limit}
          </span>
        )}
      </div>
      {children}
      {error && (
        <p className="mt-1.5 flex items-center gap-1 text-xs text-destructive" role="alert">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}

function SectionTitle({ icon: Icon, title, detail }) {
  return (
    <div className="flex items-start gap-3 border-b border-border pb-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/35 text-primary">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <h2 className="font-archive-serif text-base font-semibold text-foreground">{title}</h2>
        {detail && <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>}
      </div>
    </div>
  );
}

function SummaryRow({ label, value, mono = false }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-3 border-b border-border py-3 last:border-b-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`min-w-0 break-words text-right text-xs text-foreground ${mono ? 'font-archive-mono tabular-nums' : ''}`}>
        {value || '未填写'}
      </dd>
    </div>
  );
}

export default function PersonaEditor() {
  const navigate = useNavigate();
  const { setPrimaryAction } = useArchiveShell();
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
    event?.preventDefault();
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

  const saveAction = useMemo(() => (
    <Button
      type="submit"
      form="persona-form"
      size="lg"
      disabled={saving || avatarSaving || loading || userLoading}
    >
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存角色卡'}
    </Button>
  ), [avatarSaving, loading, saving, userLoading]);

  useEffect(() => {
    setPrimaryAction(saveAction);
    return () => setPrimaryAction(null);
  }, [saveAction, setPrimaryAction]);

  if (userLoading || loading) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center text-muted-foreground" role="status">
        <Loader2 className="h-7 w-7 animate-spin" aria-hidden="true" />
        <span className="sr-only">正在加载角色卡</span>
      </div>
    );
  }

  if (error && !card.display_name) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center px-4">
        <div className="w-full max-w-md border border-destructive/30 bg-card p-6 text-center" role="alert">
          <AlertCircle className="mx-auto h-7 w-7 text-destructive" aria-hidden="true" />
          <p className="mt-3 break-words text-sm text-destructive">{error}</p>
          <div className="mt-5 flex justify-center gap-2">
            <Button type="button" variant="outline" onClick={() => navigate('/')}>返回</Button>
            <Button type="button" onClick={() => setReloadVersion(value => value + 1)}>
              <RefreshCw aria-hidden="true" /> 重试
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const completedFields = PROFILE_FIELDS.filter(field => String(card[field] ?? '').trim()).length;
  const completion = Math.round((completedFields / PROFILE_FIELDS.length) * 100);
  const nodeId = card.node_id || user?.role_summary?.node_id || '';
  const notice = (error || success) ? (
    <div
      className={`mb-4 flex items-start gap-2 border px-3 py-3 text-sm ${
        error
          ? 'border-destructive/30 bg-destructive/5 text-destructive'
          : 'border-primary/30 bg-primary/5 text-foreground'
      }`}
      role={error ? 'alert' : 'status'}
      aria-live={error ? 'assertive' : 'polite'}
    >
      {error
        ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        : <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />}
      <span>{error || success}</span>
    </div>
  ) : null;

  const directory = (
    <div className="p-4">
      <SectionTitle icon={ImagePlus} title="头像与身份" detail="聊天窗口中的角色名片" />
      <div className="mt-5 flex flex-col items-center">
        <div className="relative h-28 w-28 overflow-hidden rounded-md border border-border bg-muted/35">
          {card.avatar_url ? (
            <img src={card.avatar_url} alt={`${card.display_name || '角色'}的扮演头像`} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-muted-foreground">
              <Contact className="h-11 w-11" aria-hidden="true" />
            </div>
          )}
          {avatarSaving && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/80" role="status">
              <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden="true" />
              <span className="sr-only">正在更新头像</span>
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
        <Button
          type="button"
          variant="outline"
          onClick={() => fileRef.current?.click()}
          disabled={avatarSaving}
          className="mt-4 w-full"
        >
          <Upload aria-hidden="true" /> 上传头像
        </Button>
        <div className="mt-2 flex w-full gap-2">
          <label htmlFor="persona-avatar-url" className="sr-only">扮演头像网络地址</label>
          <Input
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
            className="min-w-0 flex-1 font-archive-mono text-xs"
          />
          <Button
            type="button"
            size="icon"
            variant="outline"
            onClick={handleAvatarUrl}
            disabled={avatarSaving || (!avatarUrl.trim() && !card.avatar_url)}
            aria-label={avatarUrl.trim() ? '从链接设置扮演头像' : '清除扮演头像'}
            title={avatarUrl.trim() ? '设置头像链接' : '清除头像'}
          >
            <Link aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">账户身份</span>
          <BadgeCheck className="h-4 w-4 text-primary" aria-hidden="true" />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted/35">
            {user?.avatar_url ? (
              <img src={user.avatar_url} alt={`${user.username}的账户头像`} className="h-full w-full object-cover" />
            ) : (
              <User className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
            )}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm text-foreground">{user?.username}</div>
            <div className="mt-1 truncate font-archive-mono text-[10px] text-muted-foreground">{user?.user_id}</div>
          </div>
        </div>
      </div>
    </div>
  );

  const editor = (
    <form id="persona-form" onSubmit={handleSave} className="min-w-0">
      <div className="border-b border-border bg-muted/20 px-4 py-4 sm:px-6">
        <p className="font-archive-mono text-[10px] uppercase text-muted-foreground">Persona manuscript</p>
        <h2 className="mt-1 font-archive-serif text-lg font-semibold text-foreground">身份与人物小传</h2>
      </div>

      <div className="space-y-7 p-4 font-archive-serif sm:p-6">
        <section>
          <SectionTitle icon={Contact} title="身份信息" detail="用于聊天署名与角色识别" />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field id="persona-display_name" label="角色名称 *" error={submitted && errors.display_name} limit={TEXT_LIMITS.display_name} value={card.display_name}>
              <Input
                id="persona-display_name"
                value={card.display_name}
                maxLength={TEXT_LIMITS.display_name}
                onChange={event => updateField('display_name', event.target.value)}
                aria-invalid={Boolean(submitted && errors.display_name)}
                autoComplete="nickname"
              />
            </Field>
            <Field id="persona-age" label="年龄" error={submitted && errors.age}>
              <Input
                id="persona-age"
                type="number"
                min="0"
                max="10000"
                step="1"
                value={card.age}
                onChange={event => updateField('age', event.target.value)}
                aria-invalid={Boolean(submitted && errors.age)}
                className="font-archive-mono tabular-nums"
              />
            </Field>
            <Field id="persona-gender" label="性别" error={submitted && errors.gender} limit={TEXT_LIMITS.gender} value={card.gender}>
              <Input id="persona-gender" value={card.gender} maxLength={TEXT_LIMITS.gender} onChange={event => updateField('gender', event.target.value)} />
            </Field>
            <Field id="persona-pronouns" label="称谓 / 代词" error={submitted && errors.pronouns} limit={TEXT_LIMITS.pronouns} value={card.pronouns}>
              <Input id="persona-pronouns" value={card.pronouns} maxLength={TEXT_LIMITS.pronouns} onChange={event => updateField('pronouns', event.target.value)} />
            </Field>
            <Field id="persona-species" label="种族 / 物种" error={submitted && errors.species} limit={TEXT_LIMITS.species} value={card.species}>
              <Input id="persona-species" value={card.species} maxLength={TEXT_LIMITS.species} onChange={event => updateField('species', event.target.value)} />
            </Field>
            <Field id="persona-occupation" label="职业 / 身份" error={submitted && errors.occupation} limit={TEXT_LIMITS.occupation} value={card.occupation}>
              <Input id="persona-occupation" value={card.occupation} maxLength={TEXT_LIMITS.occupation} onChange={event => updateField('occupation', event.target.value)} />
            </Field>
          </div>
        </section>

        {[
          ['appearance', '外貌', User, '镜头初次看见这个角色时的细节'],
          ['personality', '性格', BadgeCheck, '对话节奏、习惯与情绪反应'],
          ['background', '背景经历', Contact, '塑造角色立场的关键往事'],
          ['goals', '当前目标', Check, '推动当下剧情的愿望与行动'],
        ].map(([field, label, Icon, detail]) => (
          <section key={field}>
            <SectionTitle icon={Icon} title={label} detail={detail} />
            <div className="mt-4">
              <Field
                id={`persona-${field}`}
                label={label}
                error={submitted && errors[field]}
                limit={TEXT_LIMITS[field]}
                value={card[field]}
              >
                <Textarea
                  id={`persona-${field}`}
                  value={card[field]}
                  maxLength={TEXT_LIMITS[field]}
                  onChange={event => updateField(field, event.target.value)}
                  className="min-h-36 font-archive-serif text-base leading-7"
                />
              </Field>
            </div>
          </section>
        ))}
      </div>
    </form>
  );

  const summary = (
    <div className="p-4">
      <SectionTitle icon={Contact} title="角色侧写" detail="随稿件实时更新" />
      <dl className="mt-3">
        <SummaryRow label="姓名" value={card.display_name} />
        <SummaryRow label="职业" value={card.occupation} />
        <SummaryRow label="代词" value={card.pronouns} />
        <SummaryRow label="完成度" value={`${completion}% (${completedFields}/${PROFILE_FIELDS.length})`} mono />
        <SummaryRow label="Node ID" value={nodeId} mono />
      </dl>
      <div className="mt-4 border border-border bg-muted/25 p-3">
        <p className="text-xs font-medium text-foreground">聊天署名预览</p>
        <div className="mt-3 flex items-end gap-2">
          <div className="h-8 w-8 shrink-0 overflow-hidden rounded-md border border-border bg-background">
            {card.avatar_url ? (
              <img src={card.avatar_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <User className="m-1.5 h-5 w-5 text-muted-foreground" aria-hidden="true" />
            )}
          </div>
          <div className="min-w-0 rounded-md border border-border bg-background px-3 py-2">
            <p className="truncate text-[10px] text-muted-foreground">{card.display_name || '未命名角色'}</p>
            <p className="mt-1 font-archive-serif text-sm leading-5 text-foreground">人物小传将在对话中塑造我的回应。</p>
          </div>
        </div>
      </div>
    </div>
  );

  const mobileAction = (
    <Button type="submit" form="persona-form" size="lg" disabled={saving || avatarSaving} className="w-full">
      {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
      {saving ? '保存中' : '保存角色卡'}
    </Button>
  );

  return (
    <ArchiveEditorWorkspace
      indexLabel="Player persona / editable archive"
      title="玩家角色档案"
      description="将聊天身份与剧本文稿集中在同一份角色侧写中。"
      directory={directory}
      editor={editor}
      summary={summary}
      mobileAction={mobileAction}
      notice={notice}
    />
  );
}
