import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUser } from '../context/UserContext';
import { userApi } from '../api/memoria';
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
  Pause,
  RotateCw,
  Sunrise,
  Upload,
  User,
  X,
  Volume2,
  Mic,
  Save,
} from 'lucide-react';

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

  // Per-field validation
  const [usernameError, setUsernameError] = useState(null);

  // Auto-clear success after 4s
  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(null), 4000);
    return () => clearTimeout(t);
  }, [success]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

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
      // Reset file input so same file can be re-selected
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
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-0 sm:p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />

      <div
        className="relative flex h-dvh w-full flex-col overflow-hidden border-cyber-green/20 bg-[#0d0d14] font-mono shadow-[0_0_60px_rgba(167,239,158,0.06)] sm:h-auto sm:max-h-[min(88dvh,760px)] sm:max-w-xl sm:rounded-lg sm:border"
        role="dialog"
        aria-modal="true"
        aria-label="用户设置"
      >
        {/* Header */}
        <div className="flex min-h-16 items-center justify-between border-b border-cyber-green/10 px-4 sm:px-5">
          <h2 className="text-sm font-bold text-cyber-green">用户设置</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/35 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/30"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="grid grid-cols-3 border-b border-white/[0.06] bg-black/15 px-3 sm:px-5" aria-label="设置分类">
          {[
            { id: 'account', label: '账户', icon: User },
            { id: 'clock', label: '世界时间', icon: CalendarClock },
            { id: 'speech', label: '语音', icon: Volume2 },
          ].map(item => {
            const Icon = item.icon;
            const active = activeSection === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveSection(item.id)}
                aria-current={active ? 'page' : undefined}
                className={`relative flex min-h-12 items-center justify-center gap-2 border-b-2 px-2 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyber-green/30 ${
                  active
                    ? 'border-cyber-green text-cyber-green'
                    : 'border-transparent text-zinc-500 hover:text-zinc-300'
                }`}
              >
                <Icon size={14} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 [scrollbar-gutter:stable] sm:px-5 sm:py-5">
          <section className={`${activeSection === 'account' ? '' : 'hidden'} rounded-lg border border-cyan-300/15 bg-cyan-300/[0.035] px-4 py-4`}>
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-cyan-300/30 bg-[#0b0b0c]">
                  {user?.role_summary?.avatar_url ? (
                    <img
                      src={user.role_summary.avatar_url}
                      alt={`${user.role_summary.display_name}的扮演头像`}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <Contact size={21} className="text-cyan-200/35" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="text-[9px] uppercase tracking-wider text-cyan-200/45">扮演身份</div>
                  <div className="mt-1 truncate text-sm text-zinc-200">
                    {user?.role_summary?.display_name || user?.username || '未设置'}
                  </div>
                  <div className="mt-0.5 truncate text-[9px] text-zinc-600">
                    {user?.role_summary?.node_id || '-'}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={handleOpenPersona}
                className="flex min-h-[44px] shrink-0 items-center gap-2 rounded-lg border border-cyan-300/20 px-3 text-xs text-cyan-100/80 transition-colors hover:bg-cyan-300/10"
              >
                <Edit3 size={14} /> 编辑
              </button>
            </div>
          </section>

          {/* ── Avatar Section ── */}
          <fieldset className={`${activeSection === 'account' ? '' : 'hidden'} rounded-lg border border-cyber-green/10 px-4 py-4`}>
            <legend className="text-[10px] text-cyber-green/50 uppercase tracking-wider px-1.5">账户头像</legend>
            <div className="flex flex-col items-center gap-3">
              <div className="w-[72px] h-[72px] rounded-full overflow-hidden border-2 border-cyber-green/25 bg-[#0b0b0c] relative group">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-cyber-green/25">
                    <User size={30} />
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="absolute inset-0 flex cursor-pointer flex-col items-center justify-center gap-1 bg-black/55 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100"
                  aria-label="上传头像"
                >
                  <Upload size={16} className="text-cyber-green" />
                  <span className="text-[9px] text-cyber-green/70">上传</span>
                </button>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                onChange={handleAvatarUpload}
                className="hidden"
              />
              <p className="text-[9px] text-cyber-green/20">点击头像上传，支持 PNG / JPEG / WebP</p>

              {/* Avatar URL input */}
              <div className="flex gap-1.5 w-full">
                <input
                  type="text"
                  value={avatarUrl}
                  onChange={e => setAvatarUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAvatarUrl()}
                  placeholder="或粘贴图片 URL 设置头像"
                  className="flex-1 bg-[#0b0b0c] border border-cyber-green/15 rounded-lg px-3 py-2 text-[11px] text-zinc-300 placeholder:text-cyber-green/12 focus:outline-none focus:border-cyber-green/40 transition-colors"
                />
                <button
                  type="button"
                  onClick={handleAvatarUrl}
                  disabled={!avatarUrl.trim() || loading}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-cyber-green/20 bg-cyber-green/10 text-cyber-green transition-colors hover:bg-cyber-green/20 disabled:cursor-not-allowed disabled:opacity-25"
                  aria-label="设置头像链接"
                >
                  <Link size={14} />
                </button>
              </div>
            </div>
          </fieldset>

          {/* ── Profile Form ── */}
          <form onSubmit={handleSaveProfile} className={`${activeSection === 'account' ? '' : 'hidden'} space-y-4`}>
            <fieldset className="border border-cyber-green/10 rounded-lg px-4 py-4 space-y-4">
              <legend className="text-[10px] text-cyber-green/50 uppercase tracking-wider px-1.5">资料</legend>

              {/* Username */}
              <div>
                <label htmlFor="settings-username" className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-1.5 block">
                  用户名 <span className="text-red-400/70">*</span>
                </label>
                <input
                  ref={usernameRef}
                  id="settings-username"
                  type="text"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  autoComplete="username"
                  aria-invalid={!!(submitted && usernameError)}
                  className={`w-full bg-[#0b0b0c] border rounded-lg px-3 py-2.5 text-sm text-zinc-300 placeholder:text-cyber-green/12 focus:outline-none focus:border-cyber-green/40 transition-colors ${
                    submitted && usernameError ? 'border-red-500/30' : 'border-cyber-green/15'
                  }`}
                />
                {submitted && usernameError && (
                  <p id="settings-username-err" className="text-[10px] text-red-400/70 mt-1 flex items-center gap-1" role="alert">
                    <AlertCircle size={10} />{usernameError}
                  </p>
                )}
              </div>

              {/* Gender */}
              <div>
                <label className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-1.5 block">性别</label>
                <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-cyber-green/15 bg-black/15">
                  {GENDERS.map(g => (
                    <button
                      key={g.value}
                      type="button"
                      onClick={() => setGender(g.value)}
                      aria-pressed={gender === g.value}
                      className={`min-h-11 border-r border-cyber-green/10 px-3 text-xs transition-colors last:border-r-0 ${
                        gender === g.value
                          ? 'bg-cyber-green/10 text-cyber-green'
                          : 'text-cyber-green/40 hover:bg-cyber-green/[0.04] hover:text-cyber-green/70'
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </div>
            </fieldset>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-cyber-green/10 hover:bg-cyber-green/[0.18] active:scale-[0.98] border border-cyber-green/20 rounded-lg text-sm font-bold text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed disabled:active:scale-100 transition-all duration-200 flex items-center justify-center gap-2 min-h-[44px]"
            >
              {loading ? <Loader2 className="animate-spin" size={16} /> : <Edit3 size={14} />}
              {loading ? '保存中...' : '保存资料'}
            </button>
          </form>

          <fieldset
            aria-busy={clockLoading}
            className={`${activeSection === 'clock' ? '' : 'hidden'} space-y-4 rounded-lg border border-cyan-300/12 px-4 py-4`}
          >
            <legend className="text-[10px] text-cyan-200/50 uppercase tracking-wider px-1.5">世界时间</legend>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-b border-white/[0.06] pb-3 text-[10px]">
              <div>
                <div className="text-zinc-600">与现实偏移</div>
                <div className="mt-1 tabular-nums text-amber-200/80">{formatOffset(worldClock?.real_offset_seconds)}</div>
              </div>
              <div>
                <div className="text-zinc-600">当前流速</div>
                <div className={`mt-1 tabular-nums ${Number(worldClock?.time_scale) === 0 ? 'text-amber-300' : 'text-cyan-200/75'}`}>
                  {Number(worldClock?.time_scale) === 0 ? '已暂停' : `${worldClock?.time_scale ?? 1}x`}
                </div>
              </div>
            </div>
            {['error', 'offline', 'stale', 'conflict'].includes(clockStatus.state) && clockStatus.message && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300/15 bg-amber-300/[0.035] px-3 py-2.5 text-[10px] leading-4 text-amber-100/75" role="status">
                <AlertCircle size={13} className="mt-0.5 shrink-0" />
                <span>{clockStatus.message}</span>
              </div>
            )}

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] text-zinc-300">
                <ClockArrowUp size={13} className="text-cyan-200/60" />
                时间流速
              </div>
            <div className="grid grid-cols-5 overflow-hidden rounded-md border border-white/10 bg-black/20">
              {[0, 1, 2, 5, 10].map(scale => {
                const selected = Number(worldClock?.time_scale) === scale;
                return (
                  <button
                    key={scale}
                    type="button"
                    onClick={() => handleScaleChange(scale)}
                    disabled={clockLoading}
                    className={`flex min-h-[44px] min-w-0 items-center justify-center gap-1 border-r border-white/10 px-1 text-[10px] last:border-r-0 disabled:cursor-wait ${
                      selected
                        ? 'bg-cyan-300/12 text-cyan-100'
                        : 'text-zinc-500 hover:bg-white/[0.03] hover:text-zinc-300'
                    }`}
                    aria-pressed={selected}
                    aria-label={scale === 0 ? '暂停世界时间' : `${scale}倍世界时间`}
                  >
                    {scale === 0 ? <Pause size={11} /> : `${scale}x`}
                  </button>
                );
              })}
            </div>
              <p className="text-[10px] leading-4 text-zinc-600">0x 暂停世界时间；高倍速会同步重算事件的预计现实触发时间。</p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] text-zinc-300">
                <CalendarClock size={13} className="text-cyan-200/60" />
                设置世界日期和时间
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <label htmlFor="settings-world-datetime" className="sr-only">世界日期和时间</label>
                <input
                  id="settings-world-datetime"
                  type="datetime-local"
                  value={worldDateTime}
                  onChange={event => setWorldDateTime(event.target.value)}
                  disabled={clockLoading}
                  className="min-h-[44px] min-w-0 flex-1 rounded-md border border-cyan-300/15 bg-[#0b0b0c] px-3 text-xs text-zinc-300 outline-none focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/10 disabled:cursor-wait disabled:opacity-100 disabled:text-zinc-300"
                />
                <button
                  type="button"
                  onClick={() => handleSetWorldTime()}
                  disabled={clockLoading || !worldDateTime}
                  className="min-h-[44px] rounded-md border border-cyan-300/20 px-3 text-[11px] text-cyan-100/80 hover:bg-cyan-300/8 disabled:cursor-wait"
                >
                  设置
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => handleAdvance(3600, ' 1 小时')}
                  disabled={clockLoading}
                  className="min-h-[44px] rounded-md border border-white/10 text-[10px] text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200 disabled:cursor-wait"
                >
                  +1 小时
                </button>
                <button
                  type="button"
                  onClick={() => handleAdvance(86400, ' 1 天')}
                  disabled={clockLoading}
                  className="min-h-[44px] rounded-md border border-white/10 text-[10px] text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200 disabled:cursor-wait"
                >
                  +1 天
                </button>
                <button
                  type="button"
                  onClick={handleNextMorning}
                  disabled={clockLoading}
                  className="flex min-h-[44px] items-center justify-center gap-1 rounded-md border border-amber-300/15 text-[10px] text-amber-200/70 hover:bg-amber-300/[0.05] disabled:cursor-wait"
                >
                  <Sunrise size={12} /> 清晨 06:00
                </button>
              </div>
            </div>

            <div className="border-t border-white/[0.06] pt-3">
              <div className="text-[10px] text-zinc-600">下一计划事件</div>
              {worldClock?.next_event ? (
                <div className="mt-1.5 space-y-1 text-[10px] leading-4 text-zinc-400">
                  <div className="truncate text-zinc-300">{worldClock.next_event.event_name || worldClock.next_event.event_id}</div>
                  <div>世界：{formatClockDate(worldClock.next_event.next_run_at)}</div>
                  <div>现实：{worldClock.next_event.next_due_real_at ? formatClockDate(worldClock.next_event.next_due_real_at) : '世界时间已暂停'}</div>
                  {worldClock.next_event.missed_count > 0 && <div className="text-amber-300/75">待补偿 {worldClock.next_event.missed_count} 次</div>}
                </div>
              ) : (
                <div className="mt-1 text-[10px] text-zinc-600">暂无已排期事件</div>
              )}
            </div>

            <div className="border-t border-white/[0.06] pt-3">
              {syncConfirming ? (
                <div className="space-y-2 rounded-md border border-amber-300/15 bg-amber-300/[0.035] p-3">
                  <div className="text-[11px] text-amber-100/80">{syncPreview(worldClock?.real_offset_seconds)}</div>
                  <p className="text-[10px] leading-4 text-zinc-500">同步会重置世界日期和时间，并立即重算全部计划事件。</p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={handleClockSync}
                      disabled={clockLoading}
                      className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-md border border-amber-300/25 bg-amber-300/8 text-[11px] text-amber-100 disabled:cursor-wait"
                    >
                      {clockLoading ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
                      确认同步
                    </button>
                    <button
                      type="button"
                      onClick={() => setSyncConfirming(false)}
                      disabled={clockLoading}
                      className="min-h-[44px] px-4 text-[11px] text-zinc-500 hover:text-zinc-300 disabled:cursor-wait"
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setSyncConfirming(true)}
                  disabled={clockLoading}
                  className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-md border border-amber-300/15 text-[11px] text-amber-200/70 hover:bg-amber-300/[0.04] disabled:cursor-wait"
                >
                  <RotateCw size={14} /> 同步至现实时间
                </button>
              )}
            </div>
          </fieldset>

          <fieldset className={`${activeSection === 'speech' ? '' : 'hidden'} space-y-4 rounded-lg border border-cyber-green/10 px-4 py-4`}>
            <legend className="text-[10px] text-cyber-green/50 uppercase tracking-wider px-1.5">语音</legend>
            <div className="space-y-2">
              <button
                type="button"
                role="switch"
                aria-checked={ttsAutoPlay}
                onClick={() => setTtsAutoPlay(value => !value)}
                disabled={speechLoading}
                className="flex min-h-[52px] w-full items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-black/15 px-3 text-left transition-colors hover:border-cyber-green/20 hover:bg-cyber-green/[0.025] disabled:opacity-40"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <Volume2 size={16} className="shrink-0 text-cyber-green/60" />
                  <span className="min-w-0">
                    <span className="block text-[11px] text-zinc-300">自动播放回复</span>
                    <span className="mt-0.5 block text-[9px] leading-4 text-zinc-600">仅播放当前收到的新回复</span>
                  </span>
                </span>
                <span className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors ${
                  ttsAutoPlay
                    ? 'border-cyber-green/40 bg-cyber-green/20'
                    : 'border-white/10 bg-white/[0.035]'
                }`}>
                  <span className={`absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full transition-all ${
                    ttsAutoPlay ? 'left-6 bg-cyber-green' : 'left-1 bg-zinc-600'
                  }`} />
                </span>
              </button>

              <button
                type="button"
                role="switch"
                aria-checked={sttAutoSend}
                onClick={() => setSttAutoSend(value => !value)}
                disabled={speechLoading}
                className="flex min-h-[52px] w-full items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-black/15 px-3 text-left transition-colors hover:border-cyber-green/20 hover:bg-cyber-green/[0.025] disabled:opacity-40"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <Mic size={16} className="shrink-0 text-cyan-200/60" />
                  <span className="min-w-0">
                    <span className="block text-[11px] text-zinc-300">转写后自动发送</span>
                    <span className="mt-0.5 block text-[9px] leading-4 text-zinc-600">录音完成后直接发送识别文本</span>
                  </span>
                </span>
                <span className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors ${
                  sttAutoSend
                    ? 'border-cyan-200/40 bg-cyan-200/15'
                    : 'border-white/10 bg-white/[0.035]'
                }`}>
                  <span className={`absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full transition-all ${
                    sttAutoSend ? 'left-6 bg-cyan-200' : 'left-1 bg-zinc-600'
                  }`} />
                </span>
              </button>
            </div>
            <button
              type="button"
              onClick={handleSaveSpeechSettings}
              disabled={speechLoading}
              className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg border border-cyber-green/20 bg-cyber-green/10 text-xs font-bold text-cyber-green transition-colors hover:bg-cyber-green/[0.18] disabled:cursor-not-allowed disabled:opacity-35"
            >
              {speechLoading ? <Loader2 size={15} className="animate-spin" /> : <Save size={14} />}
              {speechLoading ? '保存中...' : '保存语音偏好'}
            </button>
          </fieldset>

          {/* ── Account Info & Logout ── */}
          <div className={`${activeSection === 'account' ? '' : 'hidden'} space-y-3 border-t border-cyber-green/10 pt-2`}>
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-cyber-green/20 uppercase">用户 ID</span>
              <code className="text-cyber-green/35 bg-[#0b0b0c] px-2 py-0.5 rounded">{user?.user_id || '-'}</code>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-lg border border-red-500/15 py-2.5 text-xs text-red-400/70 transition-all duration-200 hover:border-red-500/25 hover:bg-red-500/5 hover:text-red-400 active:scale-[0.98]"
            >
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        </div>

        <div
          data-settings-feedback
          className="pointer-events-none absolute inset-x-0 top-[7.125rem] z-20 flex h-9 justify-center px-4 sm:px-5"
        >
          {apiError && (
            <div
              className="flex min-h-9 w-full max-w-md items-start gap-2 rounded-lg border border-red-400/20 bg-[#181014]/95 px-3 py-2 text-[11px] leading-4 text-red-300 shadow-[0_8px_28px_rgba(0,0,0,0.45)] backdrop-blur-md"
              role="alert"
            >
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{apiError}</span>
            </div>
          )}
          {!apiError && success && (
            <div
              className="flex min-h-9 w-full max-w-md items-center gap-2 rounded-lg border border-emerald-300/20 bg-[#0f1814]/95 px-3 py-2 text-[11px] leading-4 text-emerald-300 shadow-[0_8px_28px_rgba(0,0,0,0.45)] backdrop-blur-md"
              role="status"
              aria-live="polite"
            >
              <Check size={14} className="shrink-0" />
              <span>{success}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
