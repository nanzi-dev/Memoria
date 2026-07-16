import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  CalendarClock,
  Check,
  ClockArrowUp,
  Contact,
  Edit3,
  Link,
  Loader2,
  LogOut,
  Mic,
  Pause,
  RotateCw,
  Save,
  Sunrise,
  Upload,
  User,
  Volume2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import { userApi } from '../api/memoria';
import { useUser } from '../context/UserContext';

const GENDERS = [
  { value: 'unknown', label: '保密' },
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

function validateUsername(name) {
  if (!name.trim()) return '用户名不能为空';
  if (name.trim().length < 2) return '用户名至少 2 个字符';
  if (name.trim().length > 20) return '用户名不超过 20 个字符';
  if (!/^[\w\u4e00-\u9fff-]+$/.test(name.trim())) return '只能包含字母、数字、中文、下划线和连字符';
  return null;
}

function worldDateTimeInput(date) {
  if (!date) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function formatClockDate(value) {
  if (!value) return '暂无';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '暂无';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function formatOffset(seconds) {
  const value = Number(seconds) || 0;
  const sign = value < 0 ? '-' : '+';
  const absolute = Math.abs(value);
  const days = Math.floor(absolute / 86400);
  const hours = Math.floor((absolute % 86400) / 3600);
  const minutes = Math.floor((absolute % 3600) / 60);
  const parts = [];
  if (days) parts.push(`${days} 天`);
  if (hours) parts.push(`${hours} 小时`);
  if (minutes || !parts.length) parts.push(`${minutes} 分钟`);
  return `${sign}${parts.join(' ')}`;
}

function syncPreview(seconds) {
  const value = Math.round(Number(seconds) || 0);
  if (Math.abs(value) < 60) return '世界时间与现实时间基本一致';
  return value > 0
    ? `世界时间将倒退 ${formatOffset(value).slice(1)}`
    : `世界时间将前进 ${formatOffset(value).slice(1)}`;
}

function nextMorningLocal(date) {
  const target = new Date(date);
  if (target.getHours() >= 6) target.setDate(target.getDate() + 1);
  target.setHours(6, 0, 0, 0);
  return worldDateTimeInput(target);
}

function PreferenceSwitch({
  checked,
  description,
  disabled,
  icon: Icon,
  label,
  onCheckedChange,
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      disabled={disabled}
      className="flex min-h-14 w-full min-w-0 items-center justify-between gap-3 rounded-lg border border-border bg-card/55 px-3 py-2 text-left transition-colors duration-200 hover:border-primary/40 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-45"
    >
      <span className="flex min-w-0 items-center gap-3">
        <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-sm text-foreground">{label}</span>
          <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{description}</span>
        </span>
      </span>
      <span
        className={`relative h-7 w-12 shrink-0 rounded-md border transition-colors duration-200 ${
          checked ? 'border-primary/60 bg-primary/25' : 'border-border bg-muted'
        }`}
        aria-hidden="true"
      >
        <span
          className={`absolute top-1 h-5 w-5 rounded-sm transition-[left,background-color] duration-200 ${
            checked ? 'left-6 bg-primary' : 'left-1 bg-muted-foreground'
          }`}
        />
      </span>
    </button>
  );
}

export default function UserSettingsModal({ onClose }) {
  const navigate = useNavigate();
  const {
    user,
    worldClock,
    logout,
    refresh,
    getWorldNow,
    clockStatus,
    updateWorldClock,
    syncWorldClock,
    setWorldClock,
    advanceWorldClock,
  } = useUser();
  const [username, setUsername] = useState(user?.username || '');
  const [gender, setGender] = useState(user?.gender || 'unknown');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [clockLoading, setClockLoading] = useState(false);
  const [worldDateTime, setWorldDateTime] = useState(() => (
    worldDateTimeInput(getWorldNow?.() || new Date(worldClock?.world_now || Date.now()))
  ));
  const [activeSection, setActiveSection] = useState('account');
  const [syncConfirming, setSyncConfirming] = useState(false);
  const [speechLoading, setSpeechLoading] = useState(false);
  const [ttsAutoPlay, setTtsAutoPlay] = useState(Boolean(user?.tts_auto_play));
  const [sttAutoSend, setSttAutoSend] = useState(Boolean(user?.stt_auto_send));
  const fileRef = useRef(null);
  const usernameRef = useRef(null);

  const [usernameError, setUsernameError] = useState(null);

  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(null), 4000);
    return () => clearTimeout(t);
  }, [success]);

  useEffect(() => {
    if (!worldClock) return;
    setWorldDateTime(worldDateTimeInput(getWorldNow() || new Date(worldClock.world_now)));
  }, [worldClock?.clock_revision, getWorldNow]);

  useEffect(() => {
    setTtsAutoPlay(Boolean(user?.tts_auto_play));
    setSttAutoSend(Boolean(user?.stt_auto_send));
  }, [user?.tts_auto_play, user?.stt_auto_send]);

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setApiError(null);
    setSuccess(null);

    const ue = validateUsername(username);
    setSubmitted(true);
    setUsernameError(ue);
    if (ue) {
      usernameRef.current?.focus();
      return;
    }

    setLoading(true);
    try {
      const updated = await userApi.updateProfile(username.trim() || null, gender);
      await refresh();
      setSuccess('资料已保存');
      setUsername(updated.username);
      setGender(updated.gender);
    } catch (err) {
      setApiError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAvatarUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setApiError(null);
    setSuccess(null);
    setLoading(true);
    try {
      await userApi.uploadAvatar(file);
      await refresh();
      setSuccess('头像已更新');
    } catch (err) {
      setApiError(err.message);
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleAvatarUrl = async () => {
    const url = avatarUrl.trim();
    if (!url) return;
    setApiError(null);
    setSuccess(null);
    setLoading(true);
    try {
      await userApi.setAvatarUrl(url);
      await refresh();
      setSuccess('头像已更新');
      setAvatarUrl('');
    } catch (err) {
      setApiError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    onClose();
  };

  const handleOpenPersona = () => {
    onClose();
    navigate('/persona');
  };

  const handleScaleChange = async (timeScale) => {
    setApiError(null);
    setSuccess(null);
    setClockLoading(true);
    try {
      await updateWorldClock({ timeScale });
      setSuccess(timeScale === 0 ? '世界时间已暂停' : `世界时间已切换至 ${timeScale}x`);
    } catch (err) {
      setApiError(err.clockRecovered ? '设置发生冲突，已加载其他页面的最新修改，请重试' : err.message);
    } finally {
      setClockLoading(false);
    }
  };

  const handleClockSync = async () => {
    setApiError(null);
    setSuccess(null);
    setClockLoading(true);
    try {
      await syncWorldClock();
      setSuccess('世界时间已同步至现实时间');
      setSyncConfirming(false);
    } catch (err) {
      setApiError(err.clockRecovered ? '同步发生冲突，已加载最新世界时间，请重新确认' : err.message);
    } finally {
      setClockLoading(false);
    }
  };

  const handleSetWorldTime = async (value = worldDateTime) => {
    setSuccess(null);
    if (!value) {
      setApiError('请选择世界日期和时间');
      return;
    }
    const localDate = new Date(value);
    if (Number.isNaN(localDate.getTime())) {
      setApiError('请选择有效的世界日期和时间');
      return;
    }
    setApiError(null);
    setClockLoading(true);
    try {
      await setWorldClock(localDate.toISOString());
      setSuccess('世界日期和时间已更新');
    } catch (err) {
      setApiError(err.clockRecovered ? '时间设置发生冲突，已加载最新时间，请重试' : err.message);
    } finally {
      setClockLoading(false);
    }
  };

  const handleAdvance = async (seconds, label) => {
    setApiError(null);
    setSuccess(null);
    setClockLoading(true);
    try {
      await advanceWorldClock(seconds);
      setSuccess(`世界时间已前进${label}`);
    } catch (err) {
      setApiError(err.clockRecovered ? '快进发生冲突，已加载最新时间，请重试' : err.message);
    } finally {
      setClockLoading(false);
    }
  };

  const handleNextMorning = async () => {
    const current = getWorldNow();
    if (!current) return;
    const target = nextMorningLocal(current);
    setWorldDateTime(target);
    await handleSetWorldTime(target);
  };

  const handleSaveSpeechSettings = async () => {
    setApiError(null);
    setSuccess(null);
    setSpeechLoading(true);
    try {
      await userApi.updateSpeechSettings(ttsAutoPlay, sttAutoSend);
      await refresh();
      setSuccess('语音偏好已保存');
    } catch (err) {
      setApiError(err.message);
    } finally {
      setSpeechLoading(false);
    }
  };

  return (
    <Dialog open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="flex h-dvh w-screen max-w-none flex-col gap-0 overflow-hidden rounded-none border-0 p-0 sm:h-auto sm:max-h-[min(90dvh,800px)] sm:w-[calc(100%-2rem)] sm:max-w-2xl sm:rounded-lg sm:border">
        <DialogHeader className="shrink-0 border-b border-border px-4 py-4 pr-16 sm:px-6 sm:py-5 sm:pr-16">
          <DialogTitle>用户设置</DialogTitle>
          <DialogDescription>
            管理账户资料、世界时间和语音交互偏好。
          </DialogDescription>
        </DialogHeader>

        {(apiError || success) && (
          <div className="shrink-0 px-4 pt-3 sm:px-6">
            {apiError ? (
              <div
                className="flex min-h-11 items-start gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 text-sm leading-6 text-destructive"
                role="alert"
                aria-live="assertive"
                aria-atomic="true"
              >
                <AlertCircle className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="min-w-0 break-words">{apiError}</span>
              </div>
            ) : (
              <div
                className="flex min-h-11 items-center gap-2 rounded-md border border-primary/35 bg-primary/10 px-3 py-2 text-sm text-foreground"
                role="status"
                aria-live="polite"
                aria-atomic="true"
              >
                <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                <span>{success}</span>
              </div>
            )}
          </div>
        )}

        <Tabs
          value={activeSection}
          onValueChange={setActiveSection}
          className="flex min-h-0 min-w-0 flex-1 flex-col"
        >
          <TabsList className="mx-4 mt-3 grid min-h-12 shrink-0 grid-cols-3 sm:mx-6" aria-label="设置分类">
            <TabsTrigger value="account" className="min-h-11 min-w-0 gap-2 px-2">
              <User className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">账户</span>
            </TabsTrigger>
            <TabsTrigger value="clock" className="min-h-11 min-w-0 gap-2 px-2">
              <CalendarClock className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">世界时间</span>
            </TabsTrigger>
            <TabsTrigger value="speech" className="min-h-11 min-w-0 gap-2 px-2">
              <Volume2 className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">语音</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value="account"
            className="min-h-0 min-w-0 flex-1 space-y-5 overflow-x-hidden overflow-y-auto px-4 pb-6 pt-3 sm:px-6"
          >
            <section className="rounded-lg border border-border bg-card/55 p-4">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted">
                    {user?.role_summary?.avatar_url ? (
                      <img
                        src={user.role_summary.avatar_url}
                        alt={`${user.role_summary.display_name}的扮演头像`}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <Contact className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs text-muted-foreground">扮演身份</div>
                    <div className="mt-1 truncate text-sm font-medium text-foreground">
                      {user?.role_summary?.display_name || user?.username || '未设置'}
                    </div>
                    <div className="mt-1 truncate font-archive-mono text-[10px] tabular-nums text-muted-foreground">
                      {user?.role_summary?.node_id || '-'}
                    </div>
                  </div>
                </div>
                <Button type="button" size="lg" variant="outline" onClick={handleOpenPersona}>
                  <Edit3 aria-hidden="true" />
                  编辑
                </Button>
              </div>
            </section>

            <fieldset className="min-w-0 rounded-lg border border-border p-4">
              <legend className="px-1 text-sm font-medium text-foreground">账户头像</legend>
              <div className="mt-1 flex min-w-0 flex-col gap-4 sm:flex-row sm:items-center">
                <div className="group relative h-20 w-20 shrink-0 overflow-hidden rounded-md border border-border bg-muted">
                  {user?.avatar_url ? (
                    <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                      <User className="h-7 w-7" aria-hidden="true" />
                    </div>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => fileRef.current?.click()}
                    className="absolute inset-0 h-auto min-h-11 w-auto rounded-none bg-background/80 opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100"
                    aria-label="上传头像"
                  >
                    <Upload aria-hidden="true" />
                    <span className="sr-only">上传</span>
                  </Button>
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp"
                    onChange={handleAvatarUpload}
                    className="hidden"
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    点击头像上传，支持 PNG / JPEG / GIF / WebP。
                  </p>
                  <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
                    <label htmlFor="settings-avatar-url" className="sr-only">头像图片 URL</label>
                    <Input
                      id="settings-avatar-url"
                      type="text"
                      value={avatarUrl}
                      onChange={event => setAvatarUrl(event.target.value)}
                      onKeyDown={event => event.key === 'Enter' && handleAvatarUrl()}
                      placeholder="或粘贴图片 URL 设置头像"
                      className="min-w-0 flex-1"
                    />
                    <Button
                      type="button"
                      size="lg"
                      variant="secondary"
                      onClick={handleAvatarUrl}
                      disabled={!avatarUrl.trim() || loading}
                    >
                      <Link aria-hidden="true" />
                      设置链接
                    </Button>
                  </div>
                </div>
              </div>
            </fieldset>

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <fieldset className="space-y-4 rounded-lg border border-border p-4">
                <legend className="px-1 text-sm font-medium text-foreground">资料</legend>

                <div className="space-y-2">
                  <label htmlFor="settings-username" className="text-sm font-medium text-foreground">
                    用户名 <span className="text-destructive" aria-hidden="true">*</span>
                  </label>
                  <Input
                    ref={usernameRef}
                    id="settings-username"
                    type="text"
                    value={username}
                    onChange={event => setUsername(event.target.value)}
                    autoComplete="username"
                    aria-invalid={Boolean(submitted && usernameError)}
                    aria-describedby={submitted && usernameError ? 'settings-username-err' : undefined}
                    className={submitted && usernameError ? 'border-destructive focus-visible:ring-destructive' : undefined}
                  />
                  {submitted && usernameError && (
                    <p
                      id="settings-username-err"
                      className="flex items-start gap-1.5 text-xs leading-5 text-destructive"
                      role="alert"
                    >
                      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      <span>{usernameError}</span>
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <label htmlFor="settings-gender" className="text-sm font-medium text-foreground">性别</label>
                  <Select value={gender} onValueChange={setGender}>
                    <SelectTrigger id="settings-gender" className="min-h-11">
                      <SelectValue placeholder="选择性别" />
                    </SelectTrigger>
                    <SelectContent>
                      {GENDERS.map(option => (
                        <SelectItem key={option.value} value={option.value} className="min-h-11">
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </fieldset>

              <Button type="submit" size="lg" className="w-full" disabled={loading}>
                {loading ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Edit3 aria-hidden="true" />}
                {loading ? '保存中...' : '保存资料'}
              </Button>
            </form>

            <div className="space-y-3 border-t border-border pt-4">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-muted-foreground">用户 ID</span>
                <code className="max-w-full break-all rounded bg-muted px-2 py-1 font-archive-mono text-xs tabular-nums text-foreground">
                  {user?.user_id || '-'}
                </code>
              </div>
              <Button
                type="button"
                size="lg"
                variant="outline"
                onClick={handleLogout}
                className="w-full border-destructive/35 text-destructive hover:text-destructive"
              >
                <LogOut aria-hidden="true" />
                退出登录
              </Button>
            </div>
          </TabsContent>

          <TabsContent
            value="clock"
            className="min-h-0 min-w-0 flex-1 space-y-5 overflow-x-hidden overflow-y-auto px-4 pb-6 pt-3 sm:px-6"
          >
            <div className="grid grid-cols-2 gap-3" aria-busy={clockLoading}>
              <div className="rounded-lg border border-border bg-card/55 p-3">
                <div className="text-xs text-muted-foreground">与现实偏移</div>
                <div className="mt-2 break-words font-archive-mono text-sm tabular-nums text-primary">
                  {formatOffset(worldClock?.real_offset_seconds)}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card/55 p-3">
                <div className="text-xs text-muted-foreground">当前流速</div>
                <div className="mt-2 font-archive-mono text-sm tabular-nums text-primary">
                  {Number(worldClock?.time_scale) === 0 ? '已暂停' : `${worldClock?.time_scale ?? 1}x`}
                </div>
              </div>
            </div>

            {['error', 'offline', 'stale', 'conflict'].includes(clockStatus?.state) && clockStatus?.message && (
              <div
                className="flex items-start gap-2 rounded-md border border-primary/35 bg-primary/10 px-3 py-3 text-sm leading-6 text-foreground"
                role="status"
                aria-live="polite"
              >
                <AlertCircle className="mt-1 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                <span className="min-w-0 break-words">{clockStatus.message}</span>
              </div>
            )}

            <section className="space-y-3">
              <h3 className="flex items-center gap-2 font-archive-serif text-base font-semibold text-foreground">
                <ClockArrowUp className="h-4 w-4 text-primary" aria-hidden="true" />
                时间流速
              </h3>
              <div className="grid grid-cols-5 overflow-hidden rounded-md border border-border bg-muted/35">
                {[0, 1, 2, 5, 10].map(scale => {
                  const selected = Number(worldClock?.time_scale) === scale;
                  return (
                    <Button
                      key={scale}
                      type="button"
                      variant="ghost"
                      onClick={() => handleScaleChange(scale)}
                      disabled={clockLoading}
                      className={`h-11 min-h-11 min-w-0 rounded-none border-r border-border px-1 font-archive-mono text-xs tabular-nums last:border-r-0 ${
                        selected ? 'bg-primary/15 text-primary' : 'text-muted-foreground'
                      }`}
                      aria-pressed={selected}
                      aria-label={scale === 0 ? '暂停世界时间' : `${scale}倍世界时间`}
                    >
                      {scale === 0 ? <Pause aria-hidden="true" /> : `${scale}x`}
                    </Button>
                  );
                })}
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                0x 暂停世界时间；高倍速会同步重算事件的预计现实触发时间。
              </p>
            </section>

            <section className="space-y-3">
              <h3 className="flex items-center gap-2 font-archive-serif text-base font-semibold text-foreground">
                <CalendarClock className="h-4 w-4 text-primary" aria-hidden="true" />
                设置世界日期和时间
              </h3>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
                <label htmlFor="settings-world-datetime" className="sr-only">世界日期和时间</label>
                <Input
                  id="settings-world-datetime"
                  type="datetime-local"
                  value={worldDateTime}
                  onChange={event => setWorldDateTime(event.target.value)}
                  disabled={clockLoading}
                  className="min-w-0 flex-1 font-archive-mono tabular-nums"
                />
                <Button
                  type="button"
                  size="lg"
                  variant="secondary"
                  onClick={() => handleSetWorldTime()}
                  disabled={clockLoading || !worldDateTime}
                >
                  设置
                </Button>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <Button
                  type="button"
                  size="lg"
                  variant="outline"
                  onClick={() => handleAdvance(3600, ' 1 小时')}
                  disabled={clockLoading}
                  className="font-archive-mono tabular-nums"
                >
                  +1 小时
                </Button>
                <Button
                  type="button"
                  size="lg"
                  variant="outline"
                  onClick={() => handleAdvance(86400, ' 1 天')}
                  disabled={clockLoading}
                  className="font-archive-mono tabular-nums"
                >
                  +1 天
                </Button>
                <Button
                  type="button"
                  size="lg"
                  variant="outline"
                  onClick={handleNextMorning}
                  disabled={clockLoading}
                  className="font-archive-mono tabular-nums"
                >
                  <Sunrise aria-hidden="true" />
                  清晨 06:00
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card/55 p-4">
              <h3 className="text-sm font-medium text-muted-foreground">下一计划事件</h3>
              {worldClock?.next_event ? (
                <div className="mt-2 min-w-0 space-y-1 break-words font-archive-mono text-xs leading-5 tabular-nums text-muted-foreground">
                  <div className="truncate font-sans text-sm font-medium text-foreground">
                    {worldClock.next_event.event_name || worldClock.next_event.event_id}
                  </div>
                  <div>世界：{formatClockDate(worldClock.next_event.next_run_at)}</div>
                  <div>
                    现实：{worldClock.next_event.next_due_real_at
                      ? formatClockDate(worldClock.next_event.next_due_real_at)
                      : '世界时间已暂停'}
                  </div>
                  {worldClock.next_event.missed_count > 0 && (
                    <div className="text-primary">待补偿 {worldClock.next_event.missed_count} 次</div>
                  )}
                </div>
              ) : (
                <div className="mt-2 font-archive-mono text-xs tabular-nums text-muted-foreground">
                  暂无已排期事件
                </div>
              )}
            </section>

            <section className="border-t border-border pt-4">
              {syncConfirming ? (
                <div className="space-y-3 rounded-lg border border-primary/35 bg-primary/10 p-4">
                  <div className="font-archive-mono text-sm tabular-nums text-foreground">
                    {syncPreview(worldClock?.real_offset_seconds)}
                  </div>
                  <p className="text-xs leading-5 text-muted-foreground">
                    同步会重置世界日期和时间，并立即重算全部计划事件。
                  </p>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button
                      type="button"
                      size="lg"
                      onClick={handleClockSync}
                      disabled={clockLoading}
                      className="flex-1"
                    >
                      {clockLoading
                        ? <Loader2 className="animate-spin" aria-hidden="true" />
                        : <RotateCw aria-hidden="true" />}
                      确认同步
                    </Button>
                    <Button
                      type="button"
                      size="lg"
                      variant="outline"
                      onClick={() => setSyncConfirming(false)}
                      disabled={clockLoading}
                    >
                      取消
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  type="button"
                  size="lg"
                  variant="outline"
                  onClick={() => setSyncConfirming(true)}
                  disabled={clockLoading}
                  className="w-full border-primary/35 text-primary hover:text-primary"
                >
                  <RotateCw aria-hidden="true" />
                  同步至现实时间
                </Button>
              )}
            </section>
          </TabsContent>

          <TabsContent
            value="speech"
            className="min-h-0 min-w-0 flex-1 space-y-5 overflow-x-hidden overflow-y-auto px-4 pb-6 pt-3 sm:px-6"
          >
            <section className="space-y-3">
              <h3 className="font-archive-serif text-base font-semibold text-foreground">语音偏好</h3>
              <PreferenceSwitch
                checked={ttsAutoPlay}
                onCheckedChange={setTtsAutoPlay}
                disabled={speechLoading}
                icon={Volume2}
                label="自动播放回复"
                description="仅播放当前收到的新回复"
              />
              <PreferenceSwitch
                checked={sttAutoSend}
                onCheckedChange={setSttAutoSend}
                disabled={speechLoading}
                icon={Mic}
                label="转写后自动发送"
                description="录音完成后直接发送识别文本"
              />
            </section>

            <Button
              type="button"
              size="lg"
              onClick={handleSaveSpeechSettings}
              disabled={speechLoading}
              className="w-full"
            >
              {speechLoading ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
              {speechLoading ? '保存中...' : '保存语音偏好'}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
