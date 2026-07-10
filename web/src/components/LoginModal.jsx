import { useState, useRef, useEffect } from 'react';
import { useUser } from '../context/UserContext';
import { X, Loader2, LogIn, UserPlus, Eye, EyeOff, AlertCircle, Check } from 'lucide-react';

const GENDERS = [
  { value: 'unknown', label: '保密' },
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const PWD_RULES = {
  minLength: 8,
  hasLetter: /[A-Za-z]/,
  hasDigit: /\d/,
};

function validatePassword(pwd) {
  const errors = [];
  if (pwd.length < PWD_RULES.minLength) errors.push('至少 8 个字符');
  if (!PWD_RULES.hasLetter.test(pwd)) errors.push('至少包含一个字母');
  if (!PWD_RULES.hasDigit.test(pwd)) errors.push('至少包含一个数字');
  return errors;
}

function validateUsername(name) {
  if (!name.trim()) return '用户名不能为空';
  if (name.trim().length < 2) return '用户名至少 2 个字符';
  if (name.trim().length > 20) return '用户名不超过 20 个字符';
  if (!/^[\w\u4e00-\u9fff-]+$/.test(name.trim())) return '只能包含字母、数字、中文、下划线和连字符';
  return null;
}

export default function LoginModal({ onClose }) {
  const { login, register } = useUser();
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [gender, setGender] = useState('unknown');
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState(null);

  // Validation errors — only shown after submit attempt
  const [usernameError, setUsernameError] = useState(null);
  const [passwordErrors, setPasswordErrors] = useState([]);
  const [submitted, setSubmitted] = useState(false);

  const usernameRef = useRef(null);
  const passwordRef = useRef(null);

  // Focus username & reset on mount / mode switch
  useEffect(() => {
    usernameRef.current?.focus();
    setSubmitted(false);
    setUsernameError(null);
    setPasswordErrors([]);
    setApiError(null);
  }, [mode]);

  // Password rules checklist (real-time, no errors)
  const pwChecks = (() => {
    const p = password;
    return [
      { label: '至少 8 个字符', pass: p.length >= PWD_RULES.minLength },
      { label: '至少一个字母', pass: PWD_RULES.hasLetter.test(p) },
      { label: '至少一个数字', pass: PWD_RULES.hasDigit.test(p) },
    ];
  })();

  const allPwPassed = pwChecks.every(c => c.pass);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setApiError(null);

    const ue = validateUsername(username);
    const pe = validatePassword(password);
    setSubmitted(true);
    setUsernameError(ue);
    setPasswordErrors(pe);

    if (ue || pe.length > 0) {
      if (ue) usernameRef.current?.focus();
      else passwordRef.current?.focus();
      return;
    }

    setLoading(true);
    try {
      if (mode === 'login') {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password, gender);
      }
      onClose();
    } catch (err) {
      setApiError(err.message);
      usernameRef.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />

      <div
        className="relative w-full max-w-sm bg-[#0d0d14] border border-cyber-green/20 rounded-xl shadow-[0_0_60px_rgba(167,239,158,0.06)] overflow-hidden font-mono animate-fade-up"
        role="dialog"
        aria-modal="true"
        aria-label={mode === 'login' ? '登录' : '注册'}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-cyber-green/10">
          <div className="flex gap-1" role="tablist">
            <button
              role="tab"
              aria-selected={mode === 'login'}
              onClick={() => setMode('login')}
              className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-200 ${
                mode === 'login'
                  ? 'border-cyber-green/40 bg-cyber-green/10 text-cyber-green shadow-[0_0_12px_rgba(167,239,158,0.1)]'
                  : 'border-transparent text-cyber-green/35 hover:text-cyber-green/60 hover:border-cyber-green/15'
              }`}
            >
              <LogIn size={12} className="inline mr-1" />登录
            </button>
            <button
              role="tab"
              aria-selected={mode === 'register'}
              onClick={() => setMode('register')}
              className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-200 ${
                mode === 'register'
                  ? 'border-cyber-green/40 bg-cyber-green/10 text-cyber-green shadow-[0_0_12px_rgba(167,239,158,0.1)]'
                  : 'border-transparent text-cyber-green/35 hover:text-cyber-green/60 hover:border-cyber-green/15'
              }`}
            >
              <UserPlus size={12} className="inline mr-1" />注册
            </button>
          </div>
          <button
            onClick={onClose}
            className="text-cyber-green/25 hover:text-cyber-green/70 transition-colors p-1 rounded-full hover:bg-cyber-green/5"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-5 py-5 space-y-4" noValidate>
          {apiError && (
            <div className="flex items-start gap-2 text-[11px] text-red-400/85 bg-red-500/5 border border-red-500/10 rounded-lg px-3 py-2.5" role="alert">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{apiError}</span>
            </div>
          )}

          {/* Username */}
          <div>
            <label htmlFor="login-username" className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-1.5 block">
              用户名 <span className="text-red-400/70">*</span>
            </label>
            <input
              ref={usernameRef}
              id="login-username"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="输入用户名"
              autoComplete="username"
              aria-invalid={!!(submitted && usernameError)}
              className={`w-full bg-[#0b0b0c] border rounded-lg px-3 py-2.5 text-sm text-zinc-300 placeholder:text-cyber-green/12 focus:outline-none focus:border-cyber-green/40 transition-colors ${
                submitted && usernameError ? 'border-red-500/30' : 'border-cyber-green/15'
              }`}
            />
            {submitted && usernameError && (
              <p className="text-[10px] text-red-400/70 mt-1 flex items-center gap-1" role="alert">
                <AlertCircle size={10} />{usernameError}
              </p>
            )}
          </div>

          {/* Password */}
          <div>
            <label htmlFor="login-password" className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-1.5 block">
              密码 <span className="text-red-400/70">*</span>
            </label>
            <div className="relative">
              <input
                ref={passwordRef}
                id="login-password"
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={mode === 'register' ? '8位以上，含字母和数字' : '输入密码'}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                aria-invalid={submitted && passwordErrors.length > 0}
                className={`w-full bg-[#0b0b0c] border rounded-lg px-3 py-2.5 pr-10 text-sm text-zinc-300 placeholder:text-cyber-green/12 focus:outline-none focus:border-cyber-green/40 transition-colors ${
                  submitted && passwordErrors.length > 0 ? 'border-red-500/30' : 'border-cyber-green/15'
                }`}
              />
              <button
                type="button"
                onClick={() => setShowPwd(!showPwd)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-cyber-green/30 hover:text-cyber-green/60 p-1.5 transition-colors"
                aria-label={showPwd ? '隐藏密码' : '显示密码'}
                tabIndex={-1}
              >
                {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>

            {/* Password rules checklist (register mode, always visible in real-time) */}
            {mode === 'register' && (
              <div className="mt-2 space-y-1">
                {pwChecks.map((rule, i) => (
                  <div
                    key={i}
                    className={`flex items-center gap-1.5 text-[10px] transition-colors duration-200 ${
                      password.length === 0
                        ? 'text-cyber-green/20'
                        : rule.pass
                        ? 'text-emerald-400/70'
                        : 'text-cyber-green/30'
                    }`}
                  >
                    {rule.pass ? <Check size={10} /> : <div className="w-2.5 h-2.5 rounded-full border border-current opacity-40" />}
                    {rule.label}
                  </div>
                ))}
              </div>
            )}

            {/* Validation error — only after submit */}
            {submitted && passwordErrors.length > 0 && (
              <p className="text-[10px] text-red-400/70 mt-1 flex items-center gap-1" role="alert">
                <AlertCircle size={10} />{passwordErrors.join('，')}
              </p>
            )}
          </div>

          {/* Gender (register only) */}
          {mode === 'register' && (
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
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-cyber-green/10 hover:bg-cyber-green/[0.18] active:scale-[0.98] border border-cyber-green/20 rounded-lg text-sm font-bold text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed disabled:active:scale-100 transition-all duration-200 flex items-center justify-center gap-2 min-h-[44px]"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={16} />
            ) : mode === 'login' ? (
              <LogIn size={16} />
            ) : (
              <UserPlus size={16} />
            )}
            {loading ? '处理中...' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>
      </div>
    </div>
  );
}
