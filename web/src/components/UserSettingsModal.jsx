import { useState, useRef, useEffect } from 'react';
import { useUser } from '../context/UserContext';
import { userApi } from '../api/memoria';
import { X, Loader2, Upload, Link, User, LogOut, AlertCircle, Check, Edit3 } from 'lucide-react';

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

const GENDER_LABEL = { male: '男', female: '女', unknown: '保密' };

export default function UserSettingsModal({ onClose }) {
  const { user, logout, refresh } = useUser();
  const [username, setUsername] = useState(user?.username || '');
  const [gender, setGender] = useState(user?.gender || 'unknown');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [submitted, setSubmitted] = useState(false);
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

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />

      <div
        className="relative w-full max-w-sm bg-[#0d0d14] border border-cyber-green/20 rounded-xl shadow-[0_0_60px_rgba(167,239,158,0.06)] overflow-hidden font-mono"
        role="dialog"
        aria-label="用户设置"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-cyber-green/10">
          <h2 className="text-xs font-bold text-cyber-green uppercase tracking-wider">用户设置</h2>
          <button
            onClick={onClose}
            className="text-cyber-green/25 hover:text-cyber-green/70 transition-colors p-1 rounded-full hover:bg-cyber-green/5"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
          {/* Notifications */}
          {apiError && (
            <div className="flex items-start gap-2 text-[11px] text-red-400/85 bg-red-500/5 border border-red-500/10 rounded-lg px-3 py-2.5" role="alert">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{apiError}</span>
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 text-[11px] text-emerald-400/85 bg-emerald-500/5 border border-emerald-500/10 rounded-lg px-3 py-2.5 animate-in fade-in" role="status">
              <Check size={14} className="shrink-0" />
              <span>{success}</span>
            </div>
          )}

          {/* ── Avatar Section ── */}
          <fieldset className="border border-cyber-green/10 rounded-lg px-4 py-4">
            <legend className="text-[10px] text-cyber-green/50 uppercase tracking-wider px-1.5">头像</legend>
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
                  className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
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
                  className="px-3 py-2 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-cyber-green disabled:opacity-25 disabled:cursor-not-allowed transition-colors shrink-0"
                  aria-label="设置头像链接"
                >
                  <Link size={14} />
                </button>
              </div>
            </div>
          </fieldset>

          {/* ── Profile Form ── */}
          <form onSubmit={handleSaveProfile} className="space-y-4">
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
                <div className="flex gap-1.5">
                  {GENDERS.map(g => (
                    <button
                      key={g.value}
                      type="button"
                      onClick={() => setGender(g.value)}
                      className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-200 ${
                        gender === g.value
                          ? 'border-cyber-green/40 bg-cyber-green/10 text-cyber-green shadow-[0_0_10px_rgba(167,239,158,0.08)]'
                          : 'border-cyber-green/10 text-cyber-green/35 hover:border-cyber-green/25 hover:text-cyber-green/55'
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

          {/* ── Account Info & Logout ── */}
          <div className="pt-2 border-t border-cyber-green/10 space-y-3">
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-cyber-green/20 uppercase">用户 ID</span>
              <code className="text-cyber-green/35 bg-[#0b0b0c] px-2 py-0.5 rounded">{user?.user_id || '-'}</code>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="w-full py-2.5 border border-red-500/15 rounded-lg text-xs text-red-400/70 hover:bg-red-500/5 hover:text-red-400 hover:border-red-500/25 transition-all duration-200 flex items-center justify-center gap-1.5 active:scale-[0.98] min-h-[40px]"
            >
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
