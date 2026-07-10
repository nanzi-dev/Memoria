import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Trash2, X } from 'lucide-react';

const DialogContext = createContext(null);

const VARIANT = {
  info: {
    Icon: Info,
    panel: 'border-cyber-green/20 shadow-[0_0_70px_rgba(167,239,158,0.08)]',
    icon: 'text-cyber-green bg-cyber-green/10 border-cyber-green/20',
    confirm: 'bg-cyber-green/10 border-cyber-green/35 text-cyber-green hover:bg-cyber-green/20',
  },
  success: {
    Icon: CheckCircle2,
    panel: 'border-emerald-400/20 shadow-[0_0_70px_rgba(52,211,153,0.08)]',
    icon: 'text-emerald-300 bg-emerald-400/10 border-emerald-400/20',
    confirm: 'bg-emerald-400/10 border-emerald-400/35 text-emerald-300 hover:bg-emerald-400/20',
  },
  warning: {
    Icon: AlertTriangle,
    panel: 'border-amber-400/20 shadow-[0_0_70px_rgba(251,191,36,0.08)]',
    icon: 'text-amber-300 bg-amber-400/10 border-amber-400/20',
    confirm: 'bg-amber-400/10 border-amber-400/35 text-amber-300 hover:bg-amber-400/20',
  },
  danger: {
    Icon: Trash2,
    panel: 'border-red-400/20 shadow-[0_0_70px_rgba(248,113,113,0.08)]',
    icon: 'text-red-300 bg-red-400/10 border-red-400/20',
    confirm: 'bg-red-500/10 border-red-400/35 text-red-300 hover:bg-red-500/20',
  },
};

function normalizeOptions(options, fallbackTitle) {
  if (typeof options === 'string') return { title: fallbackTitle, message: options };
  return { title: fallbackTitle, ...options };
}

export function DialogProvider({ children }) {
  const [dialog, setDialog] = useState(null);

  const close = useCallback((result) => {
    setDialog((current) => {
      current?.resolve(result);
      return null;
    });
  }, []);

  const confirm = useCallback((options) => new Promise((resolve) => {
    setDialog({
      type: 'confirm',
      variant: 'warning',
      confirmText: '确认',
      cancelText: '取消',
      ...normalizeOptions(options, '确认操作'),
      resolve,
    });
  }), []);

  const alert = useCallback((options) => new Promise((resolve) => {
    setDialog({
      type: 'alert',
      variant: 'info',
      confirmText: '知道了',
      ...normalizeOptions(options, '提示'),
      resolve,
    });
  }), []);

  useEffect(() => {
    if (!dialog) return;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') close(dialog.type === 'confirm' ? false : undefined);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [close, dialog]);

  const value = useMemo(() => ({ alert, confirm }), [alert, confirm]);
  const variant = dialog ? VARIANT[dialog.variant] || VARIANT.info : null;
  const Icon = variant?.Icon;

  return (
    <DialogContext.Provider value={value}>
      {children}
      {dialog && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center p-4 font-mono">
          <div
            className="absolute inset-0 bg-black/78 backdrop-blur-md"
            onClick={() => close(dialog.type === 'confirm' ? false : undefined)}
          />
          <div
            className={`relative w-full max-w-md overflow-hidden rounded-xl border bg-[#0d0d14]/95 animate-fade-up ${variant.panel}`}
            role={dialog.type === 'confirm' ? 'alertdialog' : 'dialog'}
            aria-modal="true"
            aria-labelledby="app-dialog-title"
            aria-describedby="app-dialog-message"
          >
            <div className="absolute inset-0 pointer-events-none opacity-[0.04]" style={{
              backgroundImage: 'linear-gradient(#A7EF9E 1px, transparent 1px), linear-gradient(90deg, #A7EF9E 1px, transparent 1px)',
              backgroundSize: '20px 20px',
            }} />
            <div className="relative flex items-start gap-4 px-5 py-5">
              <div className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${variant.icon}`}>
                <Icon size={19} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <h2 id="app-dialog-title" className="text-sm font-bold tracking-wider text-zinc-100">
                    {dialog.title}
                  </h2>
                  <button
                    type="button"
                    onClick={() => close(dialog.type === 'confirm' ? false : undefined)}
                    className="rounded-full p-1 text-cyber-green/25 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/70"
                    aria-label="关闭"
                  >
                    <X size={16} />
                  </button>
                </div>
                <p id="app-dialog-message" className="mt-3 whitespace-pre-line text-sm leading-6 text-zinc-300/80">
                  {dialog.message}
                </p>
              </div>
            </div>
            <div className="relative flex justify-end gap-2 border-t border-white/[0.04] bg-black/15 px-5 py-4">
              {dialog.type === 'confirm' && (
                <button
                  type="button"
                  onClick={() => close(false)}
                  className="rounded-lg border border-cyber-green/12 px-4 py-2 text-sm text-cyber-green/55 transition-all hover:border-cyber-green/25 hover:bg-cyber-green/5 hover:text-cyber-green/80 active:scale-[0.98]"
                >
                  {dialog.cancelText}
                </button>
              )}
              <button
                type="button"
                onClick={() => close(dialog.type === 'confirm' ? true : undefined)}
                className={`rounded-lg border px-4 py-2 text-sm font-bold transition-all active:scale-[0.98] ${variant.confirm}`}
                autoFocus
              >
                {dialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  );
}

export function useDialog() {
  const context = useContext(DialogContext);
  if (!context) throw new Error('useDialog must be used within DialogProvider');
  return context;
}
